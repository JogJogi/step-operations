"""
STEP file loading and tessellation with face-ID mapping.
"""
import cadquery as cq
import numpy as np
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRep import BRep_Tool
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.gp import gp_Trsf
import os
import tempfile
import uuid


def load_step(file_path: str) -> cq.Shape:
    """Load a STEP file and return a CadQuery Shape."""
    result = cq.importers.importStep(file_path)
    # importStep returns a CadQuery Workplane - get the underlying shape
    if hasattr(result, 'val'):
        return result.val()
    return result


def tessellate_shape(shape: cq.Shape, linear_deflection: float = 0.1, angular_deflection: float = 0.1):
    """
    Tessellate a CadQuery shape into triangles with face-ID mapping.

    Returns:
        dict with:
          - vertices: flat list [x,y,z, x,y,z, ...]
          - indices: flat list [i,j,k, ...] (triangles)
          - face_map: {triangle_index: face_id}
          - face_ids: sorted list of unique face IDs
          - face_colors: {face_id: color_index} for visualization
    """
    occ_shape = shape.wrapped if hasattr(shape, 'wrapped') else shape

    # Mesh the shape
    mesh = BRepMesh_IncrementalMesh(occ_shape, linear_deflection, False, angular_deflection, True)
    mesh.Perform()

    all_vertices = []
    all_indices = []
    face_map = {}  # triangle_index -> face_id
    face_id_to_index = {}  # face_id -> int index
    face_index_counter = 0
    triangle_counter = 0
    vertex_offset = 0

    explorer = TopExp_Explorer(occ_shape, TopAbs_FACE)
    while explorer.More():
        face = explorer.Current()
        location = TopLoc_Location()
        triangulation = BRep_Tool.Triangulation_s(face, location)

        if triangulation is not None:
            # Generate stable face ID from face hash
            face_id = str(face.__hash__())
            if face_id not in face_id_to_index:
                face_id_to_index[face_id] = face_index_counter
                face_index_counter += 1

            # Get transformation matrix
            trsf = location.IsIdentity() and gp_Trsf() or location.IsIdentity() and gp_Trsf()
            if not location.IsIdentity():
                trsf = location.IsIdentity()

            is_reversed = face.Orientation() == TopAbs_REVERSED
            num_nodes = triangulation.NbNodes()

            # Collect vertices
            for i in range(1, num_nodes + 1):
                node = triangulation.Node(i)
                # Apply location transformation
                if not location.IsIdentity():
                    node.Transform(location.IsIdentity() and gp_Trsf() or location.IsIdentity() and gp_Trsf())
                all_vertices.extend([node.X(), node.Y(), node.Z()])

            # Collect triangles
            num_triangles = triangulation.NbTriangles()
            for i in range(1, num_triangles + 1):
                tri = triangulation.Triangle(i)
                n1, n2, n3 = tri.Get()
                # Convert to 0-based and apply vertex offset
                if is_reversed:
                    all_indices.extend([
                        vertex_offset + n1 - 1,
                        vertex_offset + n3 - 1,
                        vertex_offset + n2 - 1,
                    ])
                else:
                    all_indices.extend([
                        vertex_offset + n1 - 1,
                        vertex_offset + n2 - 1,
                        vertex_offset + n3 - 1,
                    ])
                face_map[triangle_counter] = face_id
                triangle_counter += 1

            vertex_offset += num_nodes

        explorer.Next()

    return {
        "vertices": all_vertices,
        "indices": all_indices,
        "face_map": face_map,
        "face_ids": list(face_id_to_index.keys()),
        "num_faces": face_index_counter,
    }


def get_face_by_id(shape: cq.Shape, face_id: str):
    """Find a TopoDS_Face by its hash-based ID."""
    occ_shape = shape.wrapped if hasattr(shape, 'wrapped') else shape
    explorer = TopExp_Explorer(occ_shape, TopAbs_FACE)
    while explorer.More():
        face = explorer.Current()
        if str(face.__hash__()) == face_id:
            return face
        explorer.Next()
    return None


def get_all_face_ids(shape: cq.Shape) -> list[str]:
    """Return list of all face IDs in the shape."""
    occ_shape = shape.wrapped if hasattr(shape, 'wrapped') else shape
    ids = []
    explorer = TopExp_Explorer(occ_shape, TopAbs_FACE)
    while explorer.More():
        face = explorer.Current()
        ids.append(str(face.__hash__()))
        explorer.Next()
    return ids
