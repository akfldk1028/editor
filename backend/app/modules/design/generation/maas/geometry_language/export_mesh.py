"""Exact export-grid cleanup without moving vertices or opening local surfaces."""
from collections import defaultdict
from decimal import Decimal
from math import dist

from backend.app.modules.design.generation.maas.geometry_language.gate import GeometryGatePolicy


EXPORT_DECIMAL_PLACES = 8


def _cross(vertices, triangle):
    a, b, c = (vertices[index] for index in triangle)
    ab = tuple(b[axis] - a[axis] for axis in range(3))
    ac = tuple(c[axis] - a[axis] for axis in range(3))
    return (ab[1]*ac[2]-ab[2]*ac[1], ab[2]*ac[0]-ab[0]*ac[2],
            ab[0]*ac[1]-ab[1]*ac[0])


def _area(vertices, triangle):
    return sum(value*value for value in _cross(vertices, triangle))**0.5 * 0.5


def _edges(triangle):
    return tuple(zip(triangle, (*triangle[1:], triangle[0])))


def repair_export_collinearity(vertices, triangles):
    """Retriangulate a closed collinear face and its long-edge neighbor.

    Only integer-exact collinearity on the existing decimal export grid is
    repairable. A merely small nonzero face stays for the unchanged hard gate.
    The two replacement triangles retain every original boundary edge and
    coordinate; the inserted diagonal replaces the collinear long edge.
    Unattached exact-zero export artifacts retain the legacy removal behavior.
    """
    policy = GeometryGatePolicy()
    candidates = [i for i, triangle in enumerate(triangles)
                  if _area(vertices, triangle) < policy.minimum_triangle_area]
    if not candidates:
        return triangles

    grid = {}
    scale = 10**EXPORT_DECIMAL_PLACES
    def point(index):
        if index not in grid:
            grid[index] = tuple(int(Decimal(str(value))*scale) for value in vertices[index])
        return grid[index]

    result = list(triangles)
    def adjacency():
        incident = defaultdict(list)
        for index, triangle in enumerate(result):
            for a, b in _edges(triangle):
                incident[tuple(sorted((a, b)))].append(index)
        return incident
    incident = adjacency()
    for index in candidates:
        triangle = result[index]
        integer_points = tuple(point(i) for i in triangle)
        if _cross(integer_points, (0, 1, 2)) != (0, 0, 0):
            continue
        # Require the preexisting local surface to be consistently oriented
        # and manifold. Otherwise a retriangulation cannot certify its topology.
        if any(len(incident[tuple(sorted((a,b)))]) != 2 or
               not any(j != index and (b,a) in _edges(result[j])
                       for j in incident[tuple(sorted((a,b)))])
               for a,b in _edges(triangle)):
            continue
        a, c = max(_edges(triangle), key=lambda edge:
                   sum((point(edge[0])[axis]-point(edge[1])[axis])**2 for axis in range(3)))
        middle = next(i for i in triangle if i not in (a,c))
        neighbor = next(j for j in incident[tuple(sorted((a,c)))] if j != index)
        other = result[neighbor]
        # Its shared edge has the opposite direction by the check above.
        u, v = c, a
        tip = next(i for i in other if i not in (u,v))
        if tip == middle or tuple(sorted((middle,tip))) in incident:
            continue
        children = ((u,middle,tip),(middle,v,tip))
        if any(_area(vertices,child) < policy.minimum_triangle_area or
               min(dist(vertices[x],vertices[y]) for x,y in _edges(child)) < policy.minimum_edge_length
               for child in children):
            continue
        result[index], result[neighbor] = children
        incident = adjacency()

    # Repair before this old cleanup so a zero face that closes a split edge
    # does not disappear and leave an unmatched long edge behind.
    return [triangle for triangle in result
            if _cross(vertices, triangle) != (0.0, 0.0, 0.0)]
