"""
Tessellation utilities: BRep faces -> triangle mesh with proper location transforms.
"""
import numpy as np
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRep import BRep_Tool
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location


def tessellate_faces(occ_shape, linear_deflection: float = 0.1, angular_deflection: float = 0.1) -> dict:
    """
    Tessellate all faces of an OCC shape.

    Returns dict with vertices (Nx3 numpy), indices (Mx3 numpy), face_map (triangle_idx->face_hash).
    """
    mesh = BRepMesh_IncrementalMesh(occ_shape, linear_deflection, False, angular_deflection, True)
    mesh.Perform()

    all_vertices = []
    all_normals = []
    all_indices = []
    face_map = {}
    triangle_idx = 0
    vertex_offset = 0

    explorer = TopExp_Explorer(occ_shape, TopAbs_FACE)
    while explorer.More():
        face = explorer.Current()
        location = TopLoc_Location()
        triangulation = BRep_Tool.Triangulation_s(face, location)

        if triangulation is not None:
            face_hash = str(face.__hash__())
            is_reversed = face.Orientation() == TopAbs_REVERSED
            num_nodes = triangulation.NbNodes()

            # Vertices with location transform applied
            local_verts = []
            for i in range(1, num_nodes + 1):
                node = triangulation.Node(i)
                if not location.IsIdentity():
                    node.Transform(location.IsIdentity())
                local_verts.append([node.X(), node.Y(), node.Z()])
            all_vertices.extend(local_verts)

            # Triangles
            for i in range(1, triangulation.NbTriangles() + 1):
                tri = triangulation.Triangle(i)
                n1, n2, n3 = tri.Get()
                if is_reversed:
                    idx = [vertex_offset + n1 - 1, vertex_offset + n3 - 1, vertex_offset + n2 - 1]
                else:
                    idx = [vertex_offset + n1 - 1, vertex_offset + n2 - 1, vertex_offset + n3 - 1]
                all_indices.append(idx)
                face_map[triangle_idx] = face_hash
                triangle_idx += 1

            vertex_offset += num_nodes
        explorer.Next()

    verts = np.array(all_vertices, dtype=np.float32) if all_vertices else np.zeros((0, 3), dtype=np.float32)
    idxs = np.array(all_indices, dtype=np.int32) if all_indices else np.zeros((0, 3), dtype=np.int32)

    return {
        "vertices": verts,
        "indices": idxs,
        "face_map": face_map,
    }


def mesh_to_frontend_json(mesh_data: dict) -> dict:
    """Convert numpy mesh to JSON-serializable format for frontend."""
    verts = mesh_data["vertices"]
    idxs = mesh_data["indices"]
    face_map = mesh_data["face_map"]

    # Compute flat-shading normals (per triangle)
    normals = np.zeros_like(verts)
    if len(idxs) > 0:
        v0 = verts[idxs[:, 0]]
        v1 = verts[idxs[:, 1]]
        v2 = verts[idxs[:, 2]]
        tri_normals = np.cross(v1 - v0, v2 - v0)
        norms = np.linalg.norm(tri_normals, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        tri_normals = tri_normals / norms
        for i, tri in enumerate(idxs):
            for v_idx in tri:
                normals[v_idx] = tri_normals[i]

    return {
        "vertices": verts.flatten().tolist(),
        "indices": idxs.flatten().tolist(),
        "normals": normals.flatten().tolist(),
        "face_map": face_map,
    }
