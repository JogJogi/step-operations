"""
FastAPI backend for STEP ring manipulator.

Endpoints:
  POST /api/upload          - Upload STEP file, get mesh_id + tessellated mesh JSON
  GET  /api/mesh/{mesh_id}  - Get tessellated mesh JSON
  WS   /ws/preview          - WebSocket live preview
  POST /api/export          - Full-quality processing + STEP/STL download
"""
import asyncio
import json
import os
import tempfile
import uuid
from typing import Optional

import cadquery as cq
import numpy as np
from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel

from step_loader import load_step, tessellate_shape
from tessellator import tessellate_faces, mesh_to_frontend_json
from effects.polygonize import polygonize
from effects.y2k import apply_y2k
from constraints import check_wall_thickness, quick_thickness_check
from exporter import shape_to_step_bytes, shape_to_stl_bytes

app = FastAPI(title="STEP Ring Manipulator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory shape store (mesh_id -> cq.Shape)
shape_store: dict[str, cq.Shape] = {}
# Mesh cache (mesh_id -> mesh_json)
mesh_cache: dict[str, dict] = {}

UPLOAD_DIR = "/data/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Upload endpoint
# ---------------------------------------------------------------------------

@app.post("/api/upload")
async def upload_step(file: UploadFile = File(...)):
    """Upload a STEP/STP file. Returns mesh_id and tessellated mesh."""
    if not file.filename.lower().endswith((".step", ".stp")):
        raise HTTPException(400, "Only STEP/STP files are accepted")

    mesh_id = str(uuid.uuid4())
    file_path = os.path.join(UPLOAD_DIR, f"{mesh_id}.step")

    # Save file
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    # Load and tessellate
    try:
        shape = load_step(file_path)
        shape_store[mesh_id] = shape

        mesh_data = _tessellate_for_preview(shape, quality="high")
        mesh_cache[mesh_id] = mesh_data

        return {
            "mesh_id": mesh_id,
            "filename": file.filename,
            "num_faces": mesh_data["num_faces"],
            "num_triangles": len(mesh_data["indices"]) // 3,
            "mesh": mesh_data,
        }
    except Exception as e:
        os.unlink(file_path)
        raise HTTPException(500, f"Failed to process STEP file: {str(e)}")


@app.get("/api/mesh/{mesh_id}")
async def get_mesh(mesh_id: str):
    """Get tessellated mesh JSON for a previously uploaded file."""
    if mesh_id not in mesh_cache:
        raise HTTPException(404, "Mesh not found")
    return mesh_cache[mesh_id]


# ---------------------------------------------------------------------------
# Export endpoint
# ---------------------------------------------------------------------------

class ExportRequest(BaseModel):
    mesh_id: str
    locked_face_ids: list[str] = []
    effect: Optional[str] = None  # "polygonize", "crystal", "voronoi", "grid"
    params: dict = {}
    format: str = "step"  # "step" or "stl"
    min_thickness_mm: float = 0.8


@app.post("/api/export")
async def export_shape(req: ExportRequest):
    """Process shape with effects and return STEP/STL file."""
    if req.mesh_id not in shape_store:
        raise HTTPException(404, "Shape not found")

    shape = shape_store[req.mesh_id]

    try:
        result_shape = _apply_effect(shape, req.effect, req.locked_face_ids, req.params, preview=False)

        # Thickness check
        thickness_result = check_wall_thickness(result_shape, req.min_thickness_mm)

        if req.format == "stl":
            data = shape_to_stl_bytes(result_shape)
            media_type = "model/stl"
            filename = "ring_modified.stl"
        else:
            data = shape_to_step_bytes(result_shape)
            media_type = "application/step"
            filename = "ring_modified.step"

        headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Thickness-Check": json.dumps({
                "passes": thickness_result["passes"],
                "min_found_mm": thickness_result["min_found_mm"],
            }),
        }
        return Response(content=data, media_type=media_type, headers=headers)

    except Exception as e:
        raise HTTPException(500, f"Export failed: {str(e)}")


# ---------------------------------------------------------------------------
# WebSocket live preview
# ---------------------------------------------------------------------------

@app.websocket("/ws/preview")
async def websocket_preview(ws: WebSocket):
    """
    WebSocket endpoint for live preview.

    Client sends:
      { "mesh_id": "...", "effect": "...", "params": {...}, "locked_faces": [...], "min_thickness": 0.8 }

    Server responds:
      { "vertices": [...], "indices": [...], "normals": [...], "face_map": {...},
        "thin_triangle_indices": [...], "min_found_mm": float, "passes": bool }
    """
    await ws.accept()
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_json({"error": "Invalid JSON"})
                continue

            mesh_id = msg.get("mesh_id")
            if not mesh_id or mesh_id not in shape_store:
                await ws.send_json({"error": "Unknown mesh_id"})
                continue

            shape = shape_store[mesh_id]
            effect = msg.get("effect")
            params = msg.get("params", {})
            locked_faces = msg.get("locked_faces", [])
            min_thickness = msg.get("min_thickness", 0.8)

            print(f"[WS] preview: effect={effect!r} params={params}", flush=True)
            try:
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: _preview_pipeline(shape, effect, locked_faces, params, min_thickness)
                )
                print(f"[WS] preview done: {len(result.get('vertices', []))} verts", flush=True)
                await ws.send_json(result)
            except Exception as e:
                import traceback
                print(f"[WS] preview error: {e}\n{traceback.format_exc()}", flush=True)
                await ws.send_json({"error": str(e)})

    except WebSocketDisconnect:
        pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _apply_effect(shape, effect, locked_face_ids, params, preview: bool):
    """Apply the selected effect to the shape."""
    if effect == "polygonize":
        # Scale up deflection for preview (faster, rougher)
        p = dict(params)
        if preview:
            p["triangle_size_mm"] = p.get("triangle_size_mm", 2.0) * 2
        return polygonize(shape, locked_face_ids, **p)

    elif effect in ("crystal", "voronoi", "grid"):
        p = dict(params)
        if preview and effect == "voronoi":
            p["num_seeds"] = max(10, p.get("num_seeds", 80) // 3)
        return apply_y2k(shape, locked_face_ids, mode=effect, **p)

    return shape  # No effect - return original


def _tessellate_for_preview(shape: cq.Shape, quality: str = "preview") -> dict:
    """Tessellate shape for frontend display."""
    deflection = 0.05 if quality == "high" else 0.2
    occ_shape = shape.wrapped if hasattr(shape, 'wrapped') else shape
    raw = tessellate_faces(occ_shape, linear_deflection=deflection, angular_deflection=0.2)
    mesh_json = mesh_to_frontend_json(raw)
    mesh_json["num_faces"] = len(set(raw["face_map"].values()))
    return mesh_json


def _preview_pipeline(shape, effect, locked_faces, params, min_thickness):
    """Fast preview pipeline (blocking - run in executor). No thickness check."""
    result_shape = _apply_effect(shape, effect, locked_faces, params, preview=True)
    mesh_data = _tessellate_for_preview(result_shape, quality="preview")
    return {
        **mesh_data,
        "thin_triangle_indices": [],
        "thin_face_ids": [],
        "min_found_mm": None,
        "passes": None,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
