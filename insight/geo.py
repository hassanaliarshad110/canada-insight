"""Geometry for access analysis, with no third-party GIS libraries.

All distances are straight-line metres on a local equirectangular projection centred on the city. Over a city-sized
area (under 60 km across) the error against true geodesic distance is well under 0.5%, far smaller than the gap
between straight-line and walking distance (see docs/methodology/access.md).

Polygons are GeoJSON-style coordinate lists: a MultiPolygon is [polygon, ...], a polygon is [outer ring, hole, ...],
a ring is [[lon, lat], ...].
"""
import math

EARTH_M_PER_DEG_LAT = 111_132.0


class Projection:
    """Longitude/latitude to metres around a reference latitude."""

    def __init__(self, lat0):
        self.lat0 = lat0
        self.kx = EARTH_M_PER_DEG_LAT * math.cos(math.radians(lat0))
        self.ky = EARTH_M_PER_DEG_LAT

    def xy(self, lon, lat):
        return lon * self.kx, lat * self.ky

    def lonlat(self, x, y):
        return x / self.kx, y / self.ky

    def ring(self, ring):
        return [self.xy(p[0], p[1]) for p in ring]

    def multipolygon(self, mp):
        return [[self.ring(r) for r in poly] for poly in mp]


def as_multipolygon(geom):
    """GeoJSON geometry (Polygon or MultiPolygon) to MultiPolygon coordinates, or None."""
    if not geom:
        return None
    t, c = geom.get('type'), geom.get('coordinates')
    if not c:
        return None
    if t == 'MultiPolygon':
        return c
    if t == 'Polygon':
        return [c]
    return None


def point_in_ring(x, y, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def point_in_multipolygon(x, y, mp):
    for poly in mp:
        if poly and point_in_ring(x, y, poly[0]) and not any(point_in_ring(x, y, h) for h in poly[1:]):
            return True
    return False


def bbox(mp):
    xs = [p[0] for poly in mp for ring in poly[:1] for p in ring]
    ys = [p[1] for poly in mp for ring in poly[:1] for p in ring]
    return min(xs), min(ys), max(xs), max(ys)


def ring_area(ring):
    a = 0.0
    for i in range(len(ring)):
        x1, y1 = ring[i - 1]
        x2, y2 = ring[i]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2


def area(mp_xy):
    """Area of a projected MultiPolygon in square metres (holes subtracted)."""
    return max(sum(ring_area(p[0]) - sum(ring_area(h) for h in p[1:]) for p in mp_xy if p), 0.0)


def centroid(ring):
    """Mean of a ring's vertices (closing vertex not repeated). Used to place a parcel at one point."""
    pts = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
    n = len(pts)
    return sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n


def seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    if L == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


class PointIndex:
    """Nearest-point distance with a uniform grid. cell: grid size in metres."""

    def __init__(self, points, cell=500.0):
        self.cell = cell
        self.grid = {}
        self.n = 0
        for x, y in points:
            self.grid.setdefault((int(x // cell), int(y // cell)), []).append((x, y))
            self.n += 1

    def nearest(self, x, y, max_dist):
        """Distance to the nearest point, or None if none within max_dist."""
        if not self.n:
            return None
        r = int(math.ceil(max_dist / self.cell))
        gx, gy = int(x // self.cell), int(y // self.cell)
        best = None
        for i in range(gx - r, gx + r + 1):
            for j in range(gy - r, gy + r + 1):
                for px, py in self.grid.get((i, j), ()):
                    d = math.hypot(px - x, py - y)
                    if best is None or d < best:
                        best = d
        return best if best is not None and best <= max_dist else None


class PolygonIndex:
    """Distance from a point to the nearest polygon (0 if inside), with a grid of edges and polygon bounding boxes."""

    def __init__(self, polygons_xy, cell=500.0):
        self.cell = cell
        self.edges = {}
        self.polys = polygons_xy
        self.boxes = {}
        for k, mp in enumerate(polygons_xy):
            x0, y0, x1, y1 = bbox(mp)
            for i in range(int(x0 // cell), int(x1 // cell) + 1):
                for j in range(int(y0 // cell), int(y1 // cell) + 1):
                    self.boxes.setdefault((i, j), set()).add(k)
            for poly in mp:
                for ring in poly:
                    for a in range(len(ring)):
                        (ax, ay), (bx, by) = ring[a - 1], ring[a]
                        lo_i, hi_i = int(min(ax, bx) // cell), int(max(ax, bx) // cell)
                        lo_j, hi_j = int(min(ay, by) // cell), int(max(ay, by) // cell)
                        for i in range(lo_i, hi_i + 1):
                            for j in range(lo_j, hi_j + 1):
                                self.edges.setdefault((i, j), []).append((ax, ay, bx, by))
        self.n = len(polygons_xy)

    def distance(self, x, y, max_dist):
        """Distance to the nearest polygon edge, 0 if inside a polygon, None if farther than max_dist."""
        if not self.n:
            return None
        gx, gy = int(x // self.cell), int(y // self.cell)
        for k in self.boxes.get((gx, gy), ()):
            if point_in_multipolygon(x, y, self.polys[k]):
                return 0.0
        r = int(math.ceil(max_dist / self.cell))
        best = None
        seen = set()
        for i in range(gx - r, gx + r + 1):
            for j in range(gy - r, gy + r + 1):
                for e in self.edges.get((i, j), ()):
                    if e in seen:
                        continue
                    seen.add(e)
                    d = seg_dist(x, y, *e)
                    if best is None or d < best:
                        best = d
        return best if best is not None and best <= max_dist else None


class AreaLocator:
    """Which area (e.g. community) holds a point. areas: {code: projected MultiPolygon}."""

    def __init__(self, areas_xy, cell=1000.0):
        self.areas = areas_xy
        self.cell = cell
        self.grid = {}
        for code, mp in areas_xy.items():
            x0, y0, x1, y1 = bbox(mp)
            for i in range(int(x0 // cell), int(x1 // cell) + 1):
                for j in range(int(y0 // cell), int(y1 // cell) + 1):
                    self.grid.setdefault((i, j), []).append(code)

    def find(self, x, y):
        for code in self.grid.get((int(x // self.cell), int(y // self.cell)), ()):
            if point_in_multipolygon(x, y, self.areas[code]):
                return code
        return None


def simplify_ring(ring, tol):
    """Douglas-Peucker on one ring (in the ring's own units). Keeps at least 4 points for a valid closed ring."""
    if len(ring) <= 4:
        return ring

    def dp(pts):
        if len(pts) < 3:
            return pts
        (ax, ay), (bx, by) = pts[0], pts[-1]
        idx, dmax = 0, -1.0
        for i in range(1, len(pts) - 1):
            d = seg_dist(pts[i][0], pts[i][1], ax, ay, bx, by)
            if d > dmax:
                idx, dmax = i, d
        if dmax > tol:
            return dp(pts[:idx + 1])[:-1] + dp(pts[idx:])
        return [pts[0], pts[-1]]

    # split a closed ring at its farthest point from the start so both halves simplify well
    far = max(range(len(ring)), key=lambda i: (ring[i][0] - ring[0][0]) ** 2 + (ring[i][1] - ring[0][1]) ** 2)
    out = dp(ring[:far + 1])[:-1] + dp(ring[far:])
    if len(out) < 4:
        return ring
    if out[0] != out[-1]:
        out.append(out[0])
    return out


def simplify_multipolygon(mp, tol, digits=5):
    out = []
    for poly in mp:
        rings = [[[round(x, digits), round(y, digits)] for x, y in simplify_ring(r, tol)] for r in poly]
        if rings and len(rings[0]) >= 4:
            out.append(rings)
    return out
