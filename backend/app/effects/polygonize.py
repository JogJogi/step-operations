"""
Polygonization effect: converts smooth B-Rep faces into flat triangular faces.

The algorithm:
1. Tessellate unlocked faces with configurable deflection (controls triangle size)
2. Convert each triangle back into a flat planar TopoDS_Face
3. Keep locked faces unchanged
4. Sew everything together into a watertight solid
"""
import cadquery as cq
import numpy as np
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRep import BRep_Tool, BRep_Builder
from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_MakePolygon,
    BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_Sewing,
    BRepBuilderAPI_MakeSolid,
    BRepBuilderAPI_MakeShell,
)
from OCP.TopoDS import TopoDS_Compound, TopoDS_Shell, TopoDS_Solid, TopoDS_Shape, TopoDS
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.gp import gp_Pnt
from OCP.BRepTools import BRepTools


def polygonize(
    shape: cq.Shape,
    locked_face_ids: list[str],
    triangle_size_mm: float = 2.0,
    angular_deflection: float = 0.5,
    uniform: bool = True,
) -> cq.Shape:
    """
    Polygonize a shape by converting smooth surfaces to flat triangle faces.

    Args:
        shape: CadQuery shape (ring)
        locked_face_ids: face IDs that must not be modified
        triangle_size_mm: controls triangle size (linear deflection for meshing)
        angular_deflection: angular deflection for meshing (lower = finer for curved areas)
        uniform: if True, use fixed deflection; if False, angular deflection varies by curvature

    Returns:
        New CadQuery shape with polygonized geometry
    """
    occ_shape = shape.wrapped if hasattr(shape, 'wrapped') else shape

    # Clear cached tessellation so our deflection setting takes effect
    BRepTools.Clean_s(occ_shape)

    # Tessellate the whole shape first
    mesh = BRepMesh_IncrementalMesh(
        occ_shape,
        triangle_size_mm,
        False,
        angular_deflection if not uniform else 0.5,
        True
    )
    mesh.Perform()

    sewing = BRepBuilderAPI_Sewing(1e-3)

    explorer = TopExp_Explorer(occ_shape, TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        face_hash = str(face.__hash__())

        if face_hash in locked_face_ids:
            # Keep original face unchanged
            sewing.Add(face)
        else:
            # Convert tessellation triangles to flat faces
            location = TopLoc_Location()
            triangulation = BRep_Tool.Triangulation_s(face, location)

            if triangulation is not None:
                is_reversed = face.Orientation() == TopAbs_REVERSED
                num_nodes = triangulation.NbNodes()

                # Gather nodes with transform applied
                nodes = []
                for i in range(1, num_nodes + 1):
                    node = triangulation.Node(i)
                    if not location.IsIdentity():
                        node.Transform(location.IsIdentity())
                    nodes.append(gp_Pnt(node.X(), node.Y(), node.Z()))

                # Create flat face for each triangle
                for i in range(1, triangulation.NbTriangles() + 1):
                    tri = triangulation.Triangle(i)
                    n1, n2, n3 = tri.Get()

                    p1 = nodes[n1 - 1]
                    p2 = nodes[n2 - 1]
                    p3 = nodes[n3 - 1]

                    if is_reversed:
                        p2, p3 = p3, p2

                    flat_face = _make_triangular_face(p1, p2, p3)
                    if flat_face is not None:
                        sewing.Add(flat_face)
            else:
                # No triangulation available, keep original
                sewing.Add(face)

        explorer.Next()

    sewing.Perform()
    sewn_shape = sewing.SewedShape()

    # Wrap in solid
    solid = _make_solid_from_sewn(sewn_shape)
    if solid is not None:
        return cq.Shape(solid)

    return cq.Shape(sewn_shape)


def _make_triangular_face(p1: gp_Pnt, p2: gp_Pnt, p3: gp_Pnt):
    """Create a flat triangular TopoDS_Face from 3 points."""
    try:
        # Check for degenerate triangle
        v1 = np.array([p2.X() - p1.X(), p2.Y() - p1.Y(), p2.Z() - p1.Z()])
        v2 = np.array([p3.X() - p1.X(), p3.Y() - p1.Y(), p3.Z() - p1.Z()])
        cross = np.cross(v1, v2)
        area = np.linalg.norm(cross)
        if area < 1e-10:
            return None  # Degenerate triangle

        wire_builder = BRepBuilderAPI_MakePolygon(p1, p2, p3, True)
        if not wire_builder.IsDone():
            return None
        wire = wire_builder.Wire()

        face_builder = BRepBuilderAPI_MakeFace(wire, True)
        if not face_builder.IsDone():
            return None
        return face_builder.Face()
    except Exception:
        return None


def _make_solid_from_sewn(sewn_shape: TopoDS_Shape):
    """Try to create a solid from a sewn shell."""
    try:
        # Find shells in sewn shape
        shell_explorer = TopExp_Explorer(sewn_shape, BRepBuilderAPI_MakeShell.__class__)

        # Try direct solid creation
        solid_builder = BRepBuilderAPI_MakeSolid()
        found_shell = False

        from OCP.TopAbs import TopAbs_SHELL
        explorer = TopExp_Explorer(sewn_shape, TopAbs_SHELL)
        while explorer.More():
            shell = explorer.Current()
            from OCP.TopoDS import TopoDS
            solid_builder.Add(TopoDS.Shell_s(shell))
            found_shell = True
            explorer.Next()

        if found_shell:
            solid_builder.Build()
            if solid_builder.IsDone():
                return solid_builder.Solid()

        return None
    except Exception:
        return None
