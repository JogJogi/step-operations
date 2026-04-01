"""
Export modified shapes to STEP or STL.
"""
import cadquery as cq
import tempfile
import os


def export_step(shape: cq.Shape, output_path: str) -> str:
    """Export shape to STEP file. Returns the path."""
    cq.exporters.export(shape, output_path, exportType="STEP")
    return output_path


def export_stl(shape: cq.Shape, output_path: str, tolerance: float = 0.01) -> str:
    """Export shape to STL file. Returns the path."""
    cq.exporters.export(shape, output_path, exportType="STL", tolerance=tolerance)
    return output_path


def shape_to_step_bytes(shape: cq.Shape) -> bytes:
    """Export shape to STEP and return as bytes."""
    with tempfile.NamedTemporaryFile(suffix=".step", delete=False) as f:
        tmp_path = f.name
    try:
        export_step(shape, tmp_path)
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def shape_to_stl_bytes(shape: cq.Shape, tolerance: float = 0.01) -> bytes:
    """Export shape to STL and return as bytes."""
    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f:
        tmp_path = f.name
    try:
        export_stl(shape, tmp_path, tolerance)
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
