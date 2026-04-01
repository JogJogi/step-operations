"""
Y2K aesthetic effects for ring geometry.

Three modes:
1. crystal  - large sharp facets like a cut gemstone (coarse tessellation + normal clustering)
2. voronoi  - organic low-poly pattern using Voronoi on surface UV space
3. grid     - regular grid subdivision of surfaces
"""
import cadquery as cq
import numpy as np
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRep import BRep_Tool
from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_MakePolygon,
    BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_Sewing,
    BRepBuilderAPI_MakeSolid,
)
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED, TopAbs_SHELL
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.gp import gp_Pnt
from OCP.TopoDS import TopoDS
from scipy.spatial import Voronoi, cKDTree


def apply_y2k(
    shape: cq.Shape,
    locked_face_ids: list[str],
    mode: str = "crystal",
    **params,
) -> cq.Shape:
    """
    Apply Y2K aesthetic to a shape.

    Args:
        shape: CadQuery shape
        locked_face_ids: face IDs to preserve unchanged
        mode: "crystal", "voronoi", or "grid"
        **params: mode-specific parameters

    Returns:
        Modified CadQuery shape
    """
    if mode == "crystal":
        return _crystal(shape, locked_face_ids, **params)
    elif mode == "voronoi":
        return _voronoi(shape, locked_face_ids, **params)
    elif mode == "grid":
        return _grid(shape, locked_face_ids, **params)
    else:
        raise ValueError(f"Unknown Y2K mode: {mode}")


# ---------------------------------------------------------------------------
# Mode 1: Crystal
# ---------------------------------------------------------------------------

def _crystal(
    shape: cq.Shape,
    locked_face_ids: list[str],
    facet_size_mm: float = 3.0,
    sharpness: float = 0.3,
) -> cq.Shape:
    """
    Crystal/gemstone facet effect.

    Uses coarse tessellation + merges triangles with similar normals into
    larger planar facets (like facets on a cut stone).

    sharpness: 0.0 = very smooth merging, 1.0 = every triangle stays separate
    """
    occ_shape = shape.wrapped if hasattr(shape, 'wrapped') else shape

    # Angular threshold for merging: sharpness 0→large angle tolerance, 1→small
    merge_angle_deg = 60.0 * (1.0 - sharpness)
    merge_cos = np.cos(np.radians(merge_angle_deg))

    mesh = BRepMesh_IncrementalMesh(occ_shape, facet_size_mm, False, 0.7, True)
    mesh.Perform()

    sewing = BRepBuilderAPI_Sewing(1e-3)

    explorer = TopExp_Explorer(occ_shape, TopAbs_FACE)
    while explorer.More():
        face = explorer.Current()
        face_hash = str(face.__hash__())

        if face_hash in locked_face_ids:
            sewing.Add(face)
        else:
            location = TopLoc_Location()
            triangulation = BRep_Tool.Triangulation_s(face, location)
            if triangulation is not None:
                nodes, tris = _extract_mesh(triangulation, location, face.Orientation() == TopAbs_REVERSED)
                # Cluster triangles by normal similarity
                clusters = _cluster_by_normals(nodes, tris, merge_cos)
                # Build faces from clusters (convex hull of cluster vertices projected to plane)
                for cluster_tris in clusters:
                    faces = _cluster_to_faces(nodes, cluster_tris)
                    for f in faces:
                        sewing.Add(f)
            else:
                sewing.Add(face)

        explorer.Next()

    return _sew_to_shape(sewing)


# ---------------------------------------------------------------------------
# Mode 2: Voronoi
# ---------------------------------------------------------------------------

def _voronoi(
    shape: cq.Shape,
    locked_face_ids: list[str],
    num_seeds: int = 80,
    randomness: float = 0.5,
    seed: int = 42,
) -> cq.Shape:
    """
    Voronoi low-poly effect.

    Projects surface to 2D UV space, computes Voronoi cells,
    then maps back to 3D and creates flat faces per cell.
    """
    occ_shape = shape.wrapped if hasattr(shape, 'wrapped') else shape
    rng = np.random.default_rng(seed)

    # Fine tessellation for source geometry
    mesh = BRepMesh_IncrementalMesh(occ_shape, 0.3, False, 0.2, True)
    mesh.Perform()

    sewing = BRepBuilderAPI_Sewing(1e-3)

    explorer = TopExp_Explorer(occ_shape, TopAbs_FACE)
    while explorer.More():
        face = explorer.Current()
        face_hash = str(face.__hash__())

        if face_hash in locked_face_ids:
            sewing.Add(face)
        else:
            location = TopLoc_Location()
            triangulation = BRep_Tool.Triangulation_s(face, location)
            if triangulation is not None and triangulation.NbNodes() > 3:
                nodes, tris = _extract_mesh(triangulation, location, face.Orientation() == TopAbs_REVERSED)

                # Number of seeds for this face proportional to area
                face_area = _mesh_area(nodes, tris)
                n = max(3, int(num_seeds * face_area / max(face_area, 1e-6)))
                n = min(n, num_seeds)

                faces = _voronoi_face(nodes, tris, n, randomness, rng)
                for f in faces:
                    sewing.Add(f)
            else:
                sewing.Add(face)

        explorer.Next()

    return _sew_to_shape(sewing)


def _voronoi_face(nodes: np.ndarray, tris: np.ndarray, n_seeds: int, randomness: float, rng) -> list:
    """Build Voronoi cells on a triangulated surface and return flat faces."""
    # Sample random points on mesh surface as seeds
    seeds_3d = _sample_surface_points(nodes, tris, n_seeds, rng)
    if len(seeds_3d) < 3:
        return _tris_to_faces(nodes, tris)

    # Find centroid and normal of face for projection
    centroid = nodes.mean(axis=0)
    face_normal = _dominant_normal(nodes, tris)

    # Build local 2D coordinate system
    u, v = _local_axes(face_normal)

    # Project all vertices and seeds to 2D
    verts_2d = np.column_stack([
        (nodes - centroid) @ u,
        (nodes - centroid) @ v,
    ])
    seeds_2d = np.column_stack([
        (seeds_3d - centroid) @ u,
        (seeds_3d - centroid) @ v,
    ])

    # Assign each vertex to nearest seed (Voronoi cell)
    tree = cKDTree(seeds_2d)
    _, assignments = tree.query(verts_2d)

    # Build a flat face for each cell (average z = centroid on surface)
    result_faces = []
    for cell_id in range(len(seeds_2d)):
        cell_vert_indices = np.where(assignments == cell_id)[0]
        if len(cell_vert_indices) < 3:
            continue

        cell_verts = nodes[cell_vert_indices]
        # Find triangles fully within this cell
        cell_tris = []
        for tri in tris:
            if all(a in cell_vert_indices for a in tri):
                cell_tris.append(tri)

        if len(cell_tris) == 0:
            continue

        # Average all cell vertices to a plane, then flatten
        cell_faces = _cluster_to_faces(nodes, cell_tris)
        result_faces.extend(cell_faces)

    return result_faces if result_faces else _tris_to_faces(nodes, tris)


# ---------------------------------------------------------------------------
# Mode 3: Grid
# ---------------------------------------------------------------------------

def _grid(
    shape: cq.Shape,
    locked_face_ids: list[str],
    grid_size_mm: float = 2.0,
    rotation_deg: float = 0.0,
) -> cq.Shape:
    """
    Regular grid pattern on surfaces.
    """
    occ_shape = shape.wrapped if hasattr(shape, 'wrapped') else shape

    mesh = BRepMesh_IncrementalMesh(occ_shape, grid_size_mm * 0.5, False, 0.3, True)
    mesh.Perform()

    sewing = BRepBuilderAPI_Sewing(1e-3)
    rotation_rad = np.radians(rotation_deg)
    cos_r, sin_r = np.cos(rotation_rad), np.sin(rotation_rad)

    explorer = TopExp_Explorer(occ_shape, TopAbs_FACE)
    while explorer.More():
        face = explorer.Current()
        face_hash = str(face.__hash__())

        if face_hash in locked_face_ids:
            sewing.Add(face)
        else:
            location = TopLoc_Location()
            triangulation = BRep_Tool.Triangulation_s(face, location)
            if triangulation is not None and triangulation.NbNodes() >= 3:
                nodes, tris = _extract_mesh(triangulation, location, face.Orientation() == TopAbs_REVERSED)
                faces = _grid_face(nodes, tris, grid_size_mm, cos_r, sin_r)
                for f in faces:
                    sewing.Add(f)
            else:
                sewing.Add(face)

        explorer.Next()

    return _sew_to_shape(sewing)


def _grid_face(nodes: np.ndarray, tris: np.ndarray, cell_size: float, cos_r: float, sin_r: float) -> list:
    """Subdivide a triangulated surface into grid cells."""
    centroid = nodes.mean(axis=0)
    face_normal = _dominant_normal(nodes, tris)
    u, v = _local_axes(face_normal)

    # Rotate u,v by rotation angle
    u_rot = cos_r * u + sin_r * v
    v_rot = -sin_r * u + cos_r * v

    # Project all vertices to 2D
    coords_u = (nodes - centroid) @ u_rot
    coords_v = (nodes - centroid) @ v_rot

    # Assign each vertex to grid cell
    cell_u = np.floor(coords_u / cell_size).astype(int)
    cell_v = np.floor(coords_v / cell_size).astype(int)
    cell_ids = cell_u * 100000 + cell_v  # Simple hash

    # Group triangles by their majority cell
    tri_cells = {}
    for tri in tris:
        # Majority vote on cell
        cells = [cell_ids[i] for i in tri]
        majority = max(set(cells), key=cells.count)
        if majority not in tri_cells:
            tri_cells[majority] = []
        tri_cells[majority].append(tri)

    result_faces = []
    for cell_tris in tri_cells.values():
        if len(cell_tris) == 0:
            continue
        faces = _cluster_to_faces(nodes, cell_tris)
        result_faces.extend(faces)

    return result_faces if result_faces else _tris_to_faces(nodes, tris)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _extract_mesh(triangulation, location, is_reversed: bool):
    """Extract nodes and triangles from OCC triangulation."""
    num_nodes = triangulation.NbNodes()
    nodes = []
    for i in range(1, num_nodes + 1):
        node = triangulation.Node(i)
        if not location.IsIdentity():
            node.Transform(location.IsIdentity())
        nodes.append([node.X(), node.Y(), node.Z()])
    nodes = np.array(nodes, dtype=np.float64)

    tris = []
    for i in range(1, triangulation.NbTriangles() + 1):
        tri = triangulation.Triangle(i)
        n1, n2, n3 = tri.Get()
        if is_reversed:
            tris.append([n1 - 1, n3 - 1, n2 - 1])
        else:
            tris.append([n1 - 1, n2 - 1, n3 - 1])
    tris = np.array(tris, dtype=np.int32)

    return nodes, tris


def _dominant_normal(nodes: np.ndarray, tris: np.ndarray) -> np.ndarray:
    """Compute area-weighted average normal of a triangle set."""
    v0 = nodes[tris[:, 0]]
    v1 = nodes[tris[:, 1]]
    v2 = nodes[tris[:, 2]]
    normals = np.cross(v1 - v0, v2 - v0)
    norms = np.linalg.norm(normals, axis=1, keepdims=True)
    norms = np.where(norms < 1e-12, 1, norms)
    normals = normals / norms
    avg = normals.sum(axis=0)
    n = np.linalg.norm(avg)
    if n < 1e-12:
        return np.array([0.0, 0.0, 1.0])
    return avg / n


def _local_axes(normal: np.ndarray):
    """Build two orthogonal axes perpendicular to normal."""
    n = normal / np.linalg.norm(normal)
    # Find a vector not parallel to n
    ref = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(n, ref)
    u = u / np.linalg.norm(u)
    v = np.cross(n, u)
    return u, v


def _mesh_area(nodes: np.ndarray, tris: np.ndarray) -> float:
    """Total surface area of a triangle mesh."""
    v0 = nodes[tris[:, 0]]
    v1 = nodes[tris[:, 1]]
    v2 = nodes[tris[:, 2]]
    cross = np.cross(v1 - v0, v2 - v0)
    return 0.5 * np.linalg.norm(cross, axis=1).sum()


def _sample_surface_points(nodes: np.ndarray, tris: np.ndarray, n: int, rng) -> np.ndarray:
    """Sample n random points uniformly on the surface."""
    v0 = nodes[tris[:, 0]]
    v1 = nodes[tris[:, 1]]
    v2 = nodes[tris[:, 2]]
    areas = 0.5 * np.linalg.norm(np.cross(v1 - v0, v2 - v0), axis=1)
    total = areas.sum()
    if total < 1e-12:
        return nodes[:n] if len(nodes) >= n else nodes

    probs = areas / total
    chosen = rng.choice(len(tris), size=n, p=probs)
    r1 = rng.random(n)
    r2 = rng.random(n)
    # Barycentric sampling
    mask = (r1 + r2) > 1
    r1[mask] = 1 - r1[mask]
    r2[mask] = 1 - r2[mask]
    pts = (
        nodes[tris[chosen, 0]] * (1 - r1 - r2)[:, None]
        + nodes[tris[chosen, 1]] * r1[:, None]
        + nodes[tris[chosen, 2]] * r2[:, None]
    )
    return pts


def _cluster_by_normals(nodes: np.ndarray, tris: np.ndarray, merge_cos: float) -> list:
    """
    Cluster triangles by similar normals (greedy).

    Returns list of lists of triangle indices.
    """
    if len(tris) == 0:
        return []

    v0 = nodes[tris[:, 0]]
    v1 = nodes[tris[:, 1]]
    v2 = nodes[tris[:, 2]]
    raw_normals = np.cross(v1 - v0, v2 - v0)
    norms = np.linalg.norm(raw_normals, axis=1, keepdims=True)
    norms = np.where(norms < 1e-12, 1, norms)
    tri_normals = raw_normals / norms

    assigned = np.full(len(tris), -1, dtype=int)
    clusters = []
    cluster_normals = []

    for i in range(len(tris)):
        if assigned[i] != -1:
            continue
        # Try to join an existing cluster
        best_cluster = -1
        for ci, cn in enumerate(cluster_normals):
            if np.dot(tri_normals[i], cn) >= merge_cos:
                best_cluster = ci
                break

        if best_cluster == -1:
            best_cluster = len(clusters)
            clusters.append([])
            cluster_normals.append(tri_normals[i].copy())

        clusters[best_cluster].append(i)
        assigned[i] = best_cluster
        # Update cluster normal (running average)
        n = len(clusters[best_cluster])
        cluster_normals[best_cluster] = (cluster_normals[best_cluster] * (n - 1) + tri_normals[i]) / n
        nn = np.linalg.norm(cluster_normals[best_cluster])
        if nn > 1e-12:
            cluster_normals[best_cluster] /= nn

    return clusters


def _cluster_to_faces(nodes: np.ndarray, tri_indices) -> list:
    """
    Convert a cluster of triangles into one or more flat faces.

    Approach: project all vertices to the best-fit plane and triangulate.
    """
    if len(tri_indices) == 0:
        return []

    tris_sub = np.array(tri_indices) if not isinstance(tri_indices[0], (list, np.ndarray)) else np.array(tri_indices)

    # Collect unique vertices
    unique_indices = np.unique(tris_sub.flatten())
    cluster_verts = nodes[unique_indices]

    if len(cluster_verts) < 3:
        return []

    # Build centroid + normal
    centroid = cluster_verts.mean(axis=0)
    if len(tris_sub) > 0 and tris_sub.ndim == 1:
        # tris_sub contains triangle indices into full nodes array
        v0 = nodes[tris_sub]
        normal = _dominant_normal(nodes, np.array([[i, i, i] for i in tris_sub[:1]]))
    else:
        normal = _dominant_normal(nodes, tris_sub if isinstance(tris_sub[0], (list, np.ndarray)) else np.reshape(tris_sub, (-1, 3)) if len(tris_sub) % 3 == 0 else np.array([tris_sub[:3]]))

    # Flatten all cluster vertices to the best-fit plane
    flat_verts = cluster_verts - np.outer((cluster_verts - centroid) @ normal, normal)

    # Return individual triangles as flat faces
    result = []
    if tris_sub.ndim == 2 and tris_sub.shape[1] == 3:
        for tri in tris_sub:
            p1 = gp_Pnt(*nodes[tri[0]].tolist())
            p2 = gp_Pnt(*nodes[tri[1]].tolist())
            p3 = gp_Pnt(*nodes[tri[2]].tolist())
            f = _make_tri_face(p1, p2, p3)
            if f is not None:
                result.append(f)
    else:
        # Fall back to individual triangles
        for idx in range(0, len(tris_sub) - 2, 3):
            p1 = gp_Pnt(*nodes[tris_sub[idx]].tolist())
            p2 = gp_Pnt(*nodes[tris_sub[idx + 1]].tolist())
            p3 = gp_Pnt(*nodes[tris_sub[idx + 2]].tolist())
            f = _make_tri_face(p1, p2, p3)
            if f is not None:
                result.append(f)

    return result


def _tris_to_faces(nodes: np.ndarray, tris: np.ndarray) -> list:
    """Convert each triangle to a flat face (no clustering)."""
    result = []
    for tri in tris:
        p1 = gp_Pnt(*nodes[tri[0]].tolist())
        p2 = gp_Pnt(*nodes[tri[1]].tolist())
        p3 = gp_Pnt(*nodes[tri[2]].tolist())
        f = _make_tri_face(p1, p2, p3)
        if f is not None:
            result.append(f)
    return result


def _make_tri_face(p1: gp_Pnt, p2: gp_Pnt, p3: gp_Pnt):
    """Create a flat triangular TopoDS_Face from 3 points."""
    try:
        v1 = np.array([p2.X() - p1.X(), p2.Y() - p1.Y(), p2.Z() - p1.Z()])
        v2 = np.array([p3.X() - p1.X(), p3.Y() - p1.Y(), p3.Z() - p1.Z()])
        if np.linalg.norm(np.cross(v1, v2)) < 1e-10:
            return None

        wire = BRepBuilderAPI_MakePolygon(p1, p2, p3, True)
        if not wire.IsDone():
            return None
        face = BRepBuilderAPI_MakeFace(wire.Wire(), True)
        if not face.IsDone():
            return None
        return face.Face()
    except Exception:
        return None


def _sew_to_shape(sewing: BRepBuilderAPI_Sewing) -> cq.Shape:
    """Finalize sewing and return a CadQuery shape (solid if possible)."""
    sewing.Perform()
    sewn = sewing.SewedShape()

    # Try to make solid
    solid_builder = BRepBuilderAPI_MakeSolid()
    found = False
    explorer = TopExp_Explorer(sewn, TopAbs_SHELL)
    while explorer.More():
        solid_builder.Add(TopoDS.Shell_s(explorer.Current()))
        found = True
        explorer.Next()

    if found:
        solid_builder.Build()
        if solid_builder.IsDone():
            return cq.Shape(solid_builder.Solid())

    return cq.Shape(sewn)
