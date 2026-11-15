"""
geo.py — REAL BORDERS FOR THE REGION FILTER

A region with a "boundary" in config.REGIONS is counted by the real border of the
country or state (geodata/boundaries.geojson, Natural Earth 1:10m), not by its rectangle.

The test is exact for every single detection and cheap enough for 267 million of them:

  1. The border is laid over the 0.1° grid once. Every cell becomes one of
       OUTSIDE   no part of the cell is inside the border,
       INSIDE    the whole cell is inside,
       EDGE      the border passes through the cell.
  2. A detection in an OUTSIDE / INSIDE cell is decided by the cell alone.
  3. A detection in an EDGE cell is tested against the border itself: we know whether the
     cell centre is inside, and count how many border segments the straight line from the
     centre to the detection crosses (an odd number flips the answer). Only the few
     segments that pass through that cell are looked at.

So a cell on a border is never given to a country as a whole: only the detections that
really lie inside are counted, and the cell is "active" for the region only if it has one.

Everything is numpy; no GIS package is needed. Rings follow the even-odd rule, so holes
and many separate parts (islands, exclaves) work without special cases.
"""

import hashlib
import json
import threading

import numpy as np

import config

OUTSIDE, INSIDE, EDGE = 0, 1, 2
VERSION = "1"            # part of the regions signature: change it when the algorithm changes
_GRID_X, _GRID_Y = 3600, 1800


def _repeat_range(first, count):
    """For every item i: the integers first[i], first[i]+1, … (count[i] of them), plus the item index."""
    index = np.repeat(np.arange(len(count)), count)
    offset = np.arange(count.sum()) - np.repeat(np.cumsum(count) - count, count)
    return index, np.repeat(first, count) + offset


class Shape:
    """A border (list of rings of (lon, lat) degrees), optionally cut by a rectangle of whole cells."""

    def __init__(self, rings, clip_cells=None):
        edges = []
        for ring in rings:
            ring = np.asarray(ring, dtype=np.float64)
            if len(ring) < 3:
                continue
            if not np.array_equal(ring[0], ring[-1]):
                ring = np.vstack([ring, ring[:1]])
            # grid units: one unit = one 0.1° cell, origin (-180°, -90°) like store.cell_ids
            u, v = (ring[:, 0] + 180.0) * 10.0, (ring[:, 1] + 90.0) * 10.0
            edges.append(np.column_stack([u[:-1], v[:-1], u[1:], v[1:]]))
        if not edges:
            raise ValueError("A border needs at least one ring.")
        edges = np.concatenate(edges)
        edges = edges[(edges[:, 0] != edges[:, 2]) | (edges[:, 1] != edges[:, 3])]
        self.rings = [np.asarray(r, dtype=np.float64) for r in rings]
        x_from = int(np.clip(np.floor(edges[:, [0, 2]].min()), 0, _GRID_X - 1))
        x_to = int(np.clip(np.ceil(edges[:, [0, 2]].max()) - 1, x_from, _GRID_X - 1))
        y_from = int(np.clip(np.floor(edges[:, [1, 3]].min()), 0, _GRID_Y - 1))
        y_to = int(np.clip(np.ceil(edges[:, [1, 3]].max()) - 1, y_from, _GRID_Y - 1))
        if clip_cells is not None:
            cy_from, cy_to, cx_from, cx_to = clip_cells
            y_from, y_to = max(y_from, cy_from), min(y_to, cy_to)
            x_from, x_to = max(x_from, cx_from), min(x_to, cx_to)
            if y_from > y_to or x_from > x_to:
                raise ValueError("The rectangle does not touch the border it should cut.")
        self.cells = (y_from, y_to, x_from, x_to)          # same form as store.cell_range
        self._ny, self._nx = y_to - y_from + 1, x_to - x_from + 1
        self._edges = edges
        self._center_in = self._fill_centers()
        self._class, self._start, self._cell_edges = self._lay_edges()

    # ---------- building ----------

    def _fill_centers(self):
        """For every cell of the range: is its centre inside the border (even-odd scanline)?"""
        y_from, _, x_from, _ = self.cells
        e = self._edges
        low, high = np.minimum(e[:, 1], e[:, 3]), np.maximum(e[:, 1], e[:, 3])
        # centre lines are at v = j + 0.5; an edge crosses line j when low <= j + 0.5 < high
        first = np.ceil(low - 0.5).astype(np.int64)
        count = np.maximum(0, np.ceil(high - 0.5).astype(np.int64) - first)
        index, row = _repeat_range(first, count)
        keep = (row >= y_from) & (row < y_from + self._ny)
        index, row = index[keep], row[keep]
        u0, v0, u1, v1 = e[index].T
        x = u0 + (row + 0.5 - v0) * (u1 - u0) / (v1 - v0)
        order = np.lexsort((x, row))
        row, x = row[order], x[order]
        bounds = np.searchsorted(row, np.arange(y_from, y_from + self._ny + 1))
        centers = x_from + np.arange(self._nx) + 0.5
        inside = np.zeros((self._ny, self._nx), dtype=bool)
        for j in range(self._ny):
            crossings = x[bounds[j]:bounds[j + 1]]
            if len(crossings):
                inside[j] = np.searchsorted(crossings, centers) % 2 == 1
        return inside

    def _lay_edges(self):
        """Which cells every border segment passes through → cell classes and segments per EDGE cell."""
        y_from, _, x_from, _ = self.cells
        e = self._edges
        n = len(e)
        index_parts, t_parts = [np.arange(n), np.arange(n)], [np.zeros(n), np.ones(n)]
        for a, b in ((0, 2), (1, 3)):            # crossings with vertical, then horizontal grid lines
            lo, hi = np.minimum(e[:, a], e[:, b]), np.maximum(e[:, a], e[:, b])
            first = np.floor(lo).astype(np.int64) + 1
            count = np.maximum(0, np.ceil(hi).astype(np.int64) - first)
            index, line = _repeat_range(first, count)
            index_parts.append(index)
            t_parts.append((line - e[index, a]) / (e[index, b] - e[index, a]))
        index, t = np.concatenate(index_parts), np.concatenate(t_parts)
        order = np.lexsort((t, index))
        index, t = index[order], t[order]
        same = index[1:] == index[:-1]
        piece, middle = index[:-1][same], (t[:-1][same] + t[1:][same]) / 2
        u = e[piece, 0] + middle * (e[piece, 2] - e[piece, 0])
        v = e[piece, 1] + middle * (e[piece, 3] - e[piece, 1])
        gx, gy = np.floor(u).astype(np.int64) - x_from, np.floor(v).astype(np.int64) - y_from
        keep = (gx >= 0) & (gx < self._nx) & (gy >= 0) & (gy < self._ny)
        local = gy[keep] * self._nx + gx[keep]
        pairs = np.unique(np.column_stack([local, piece[keep]]), axis=0)      # sorted by cell, then segment
        classes = np.where(self._center_in, INSIDE, OUTSIDE).astype(np.uint8).ravel()
        classes[pairs[:, 0]] = EDGE
        start = np.searchsorted(pairs[:, 0], np.arange(self._ny * self._nx + 1))
        return classes.reshape(self._ny, self._nx), start, pairs[:, 1]

    # ---------- using ----------

    def cell_class(self, ids):
        """OUTSIDE / INSIDE / EDGE for cell numbers (row × 3600 + column, like store.cell_ids)."""
        ids = np.asarray(ids, dtype=np.int64)
        y_from, y_to, x_from, x_to = self.cells
        gy, gx = ids // _GRID_X, ids % _GRID_X
        result = np.zeros(len(ids), dtype=np.uint8)
        inside = (gy >= y_from) & (gy <= y_to) & (gx >= x_from) & (gx <= x_to)
        result[inside] = self._class[gy[inside] - y_from, gx[inside] - x_from]
        return result

    def contains(self, lat, lon):
        """
        Boolean mask for detections. lat / lon are the stored whole numbers (degrees × 100 000),
        so the cell of a detection is exactly the one store.cell_ids gives it.
        """
        lat, lon = np.asarray(lat, dtype=np.int64), np.asarray(lon, dtype=np.int64)
        y_from, y_to, x_from, x_to = self.cells
        gy = np.minimum((lat + 9_000_000) // 10_000, _GRID_Y - 1)
        gx = np.minimum((lon + 18_000_000) // 10_000, _GRID_X - 1)
        result = np.zeros(len(lat), dtype=bool)
        in_range = np.flatnonzero((gy >= y_from) & (gy <= y_to) & (gx >= x_from) & (gx <= x_to))
        if not len(in_range):
            return result
        ly, lx = gy[in_range] - y_from, gx[in_range] - x_from
        classes = self._class[ly, lx]
        result[in_range[classes == INSIDE]] = True
        edge = np.flatnonzero(classes == EDGE)
        if len(edge):
            at = in_range[edge]
            ly, lx = ly[edge], lx[edge]
            local = ly * self._nx + lx
            cx, cy = lx + x_from + 0.5, ly + y_from + 0.5                    # the cell centre
            px, py = (lon[at] + 18_000_000) / 10_000.0, (lat[at] + 9_000_000) / 10_000.0
            count = self._start[local + 1] - self._start[local]
            point, segment = _repeat_range(self._start[local], count)
            ax, ay, bx, by = self._edges[self._cell_edges[segment]].T
            cx, cy, px, py = cx[point], cy[point], px[point], py[point]
            # the centre→detection line and the border segment cross when each one has the ends
            # of the other on different sides (">" on one side only, so a shared corner counts once)
            d1 = (px - cx) * (ay - cy) - (py - cy) * (ax - cx)
            d2 = (px - cx) * (by - cy) - (py - cy) * (bx - cx)
            d3 = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
            d4 = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
            crossed = ((d1 > 0) != (d2 > 0)) & ((d3 > 0) != (d4 > 0))
            flips = np.bincount(point[crossed], minlength=len(edge)) % 2 == 1
            result[at] = self._center_in[ly, lx] ^ flips
        return result

    def outline(self, tolerance=0.0):
        """The rings as lists of [lon, lat]; with a tolerance (degrees) small details are dropped."""
        result = []
        for ring in self.rings:
            if tolerance:
                span = np.ptp(ring, axis=0)
                if max(span) < tolerance * 4:
                    continue                      # an islet smaller than a few pixels
                step = np.abs(np.diff(ring, axis=0)).sum(axis=1)
                keep = np.r_[True, np.diff(np.floor(np.r_[0.0, np.cumsum(step)] / tolerance)) > 0]
                keep[[0, -1]] = True
                ring = ring[keep]
                if len(ring) < 4:
                    continue
            result.append(np.round(ring, 4).tolist())
        return result


# ---------------------------------------------------------------------------
# Borders of the configured regions
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_file = {}
_shapes = {}


def _boundaries():
    """{boundary id: rings} from the bundled file (read once)."""
    path = config.BOUNDARIES_FILE
    with _lock:
        if _file.get("path") != str(path):
            raw = path.read_bytes()
            features = {}
            for feature in json.loads(raw)["features"]:
                features[feature["id"]] = [ring for polygon in feature["geometry"]["coordinates"]
                                           for ring in polygon]
            _file.update(path=str(path), features=features, digest=hashlib.sha256(raw).hexdigest()[:16])
            _shapes.clear()
        return _file["features"]


def region_shape(region):
    """The Shape of a configured region, or None when the region is a plain rectangle / the world."""
    info = config.REGIONS[region]
    boundary = info.get("boundary")
    if not boundary:
        return None
    key = (region, boundary, bool(info.get("clip")), tuple(info["bbox"] or ()))
    features = _boundaries()
    with _lock:
        if key in _shapes:
            return _shapes[key]
    if boundary not in features:
        raise ValueError(f"Region '{region}': the border '{boundary}' is not in {config.BOUNDARIES_FILE.name}. "
                         "Add it with: python tools/build_boundaries.py")
    clip = None
    if info.get("clip"):
        import store                                   # late import: store imports this module
        clip = store.cell_range(info["bbox"])
    shape = Shape(features[boundary], clip)
    with _lock:
        _shapes[key] = shape
    return shape


def signature():
    """Changes whenever a border, the way regions use it or the algorithm changes."""
    used = {key: [info.get("boundary"), bool(info.get("clip"))] for key, info in config.REGIONS.items()
            if info.get("boundary")}
    if not used:
        return "none"
    _boundaries()
    return f"{VERSION}:{_file['digest']}:{json.dumps(used, sort_keys=True)}"
