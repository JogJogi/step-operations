"""
Manufacturing constraints: minimum wall thickness checking.
"""
import cadquery as cq
import numpy as np
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeThickSolid
from OCP.TopTools import TopTools_ListOfShape
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRep import BRep_Tool
from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.gp import gp_Pnt


def check_wall_thickness(shape: cq.Shape, min_thickness_mm: float = 0.8) -> dict:
    """
    Check minimum wall thickness of a shape.

    Uses ray casting through the shape: for each surface triangle,
    cast a ray inward along the face normal and find where it exits.
    The distance is the local wall thickness.

    Returns:
        {
            "passes": bool,
            "min_found_mm": float,
            "thin_triangle_indices": list[int],  # indices into the tessellation
            "thin_face_ids": list[str],
        }
    """
    occ_shape = shape.wrapped if hasattr(shape, 'wrapped') else shape

    # Tessellate for analysis
    mesh = BRepMesh_IncrementalMesh(occ_shape, 0.3, False, 0.2, True)
    mesh.Perform()

    classifier = BRepClass3d_SolidClassifier(occ_shape)

    thin_triangle_indices = []
    thin_face_ids = set()
    all_thicknesses = []
    triangle_idx = 0

    explorer = TopExp_Explorer(occ_shape, TopAbs_FACE)
    while explorer.More():
        face = explorer.Current()
        face_hash = str(face.__hash__())
        location = TopLoc_Location()
        triangulation = BRep_Tool.Triangulation_s(face, location)

        if triangulation is not None:
            nodes = []
            for i in range(1, triangulation.NbNodes() + 1):
                node = triangulation.Node(i)
                nodes.append([node.X(), node.Y(), node.Z()])
            nodes = np.array(nodes)

            for i in range(1, triangulation.NbTriangles() + 1):
                tri = triangulation.Triangle(i)
                n1, n2, n3 = tri.Get()

                # Triangle centroid
                v0 = nodes[n1 - 1]
                v1 = nodes[n2 - 1]
                v2 = nodes[n3 - 1]
                centroid = (v0 + v1 + v2) / 3.0

                # Triangle normal
                edge1 = v1 - v0
                edge2 = v2 - v0
                normal = np.cross(edge1, edge2)
                norm_len = np.linalg.norm(normal)
                if norm_len < 1e-10:
                    triangle_idx += 1
                    continue
                normal = normal / norm_len

                # Cast ray inward - sample thickness at multiple depths
                thickness = _ray_thickness(classifier, centroid, -normal, min_thickness_mm * 3)

                all_thicknesses.append(thickness)
                if thickness < min_thickness_mm:
                    thin_triangle_indices.append(triangle_idx)
                    thin_face_ids.add(face_hash)

                triangle_idx += 1

        explorer.Next()

    min_found = float(np.min(all_thicknesses)) if all_thicknesses else 0.0

    return {
        "passes": len(thin_triangle_indices) == 0,
        "min_found_mm": round(min_found, 3),
        "thin_triangle_indices": thin_triangle_indices,
        "thin_face_ids": list(thin_face_ids),
    }


def _ray_thickness(classifier: BRepClass3d_SolidClassifier, origin: np.ndarray, direction: np.ndarray, max_dist: float) -> float:
    """
    Estimate wall thickness at a point by sampling along a ray.

    Samples points along the ray and finds where the classifier
    transitions from inside to outside the solid.
    """
    steps = 20
    step_size = max_dist / steps

    last_inside = False
    for i in range(1, steps + 1):
        pt = origin + direction * (i * step_size)
        gp_pt = gp_Pnt(float(pt[0]), float(pt[1]), float(pt[2]))
        try:
            classifier.Perform(gp_pt, 1e-3)
            from OCP.TopAbs import TopAbs_IN
            is_inside = classifier.State() == TopAbs_IN
            if last_inside and not is_inside:
                return i * step_size
            last_inside = is_inside
        except Exception:
            pass

    return max_dist  # Full depth reached = thick enough


def quick_thickness_check(shape: cq.Shape, min_thickness_mm: float = 0.8) -> bool:
    """
    Fast but approximate thickness check using BRepOffset.

    Attempts to offset the solid inward by min_thickness. If it fails or
    produces no valid result, the shape likely has thin walls.
    """
    try:
        occ_shape = shape.wrapped if hasattr(shape, 'wrapped') else shape
        faces_to_remove = TopTools_ListOfShape()
        offset_maker = BRepOffsetAPI_MakeThickSolid()
        offset_maker.MakeThickSolidBySimple(occ_shape, -min_thickness_mm)
        offset_maker.Build()
        return offset_maker.IsDone()
    except Exception:
        return False
