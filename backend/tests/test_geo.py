"""Real borders: the exact point-in-border test (geo.py) and its use by the regions."""

import numpy as np
import pytest

from conftest import border_rings, inside_border


def _ints(lat, lon):
    return np.round(np.asarray(lat) * 100000).astype(np.int64), np.round(np.asarray(lon) * 100000).astype(np.int64)


def test_square_with_a_hole_and_a_second_part(app_env):
    geo = app_env["store"].geo
    outer = [[10.0, 10.0], [11.0, 10.0], [11.0, 11.0], [10.0, 11.0], [10.0, 10.0]]
    hole = [[10.42, 10.42], [10.58, 10.42], [10.58, 10.58], [10.42, 10.58], [10.42, 10.42]]
    island = [[20.03, 20.03], [20.07, 20.03], [20.05, 20.07], [20.03, 20.03]]      # smaller than one cell
    shape = geo.Shape([outer, hole, island])
    lat = [10.2, 10.5, 10.95, 9.99, 20.04, 20.065, 20.08]
    lon = [10.2, 10.5, 10.95, 10.5, 20.05, 20.035, 20.05]
    assert shape.contains(*_ints(lat, lon)).tolist() == [True, False, True, False, True, False, False]


def test_a_cell_cut_by_the_border_is_decided_per_detection(app_env):
    """The cell 10.0–10.1°N / 10.0–10.1°E is cut diagonally; its centre is inside."""
    geo = app_env["store"].geo
    triangle = [[10.0, 10.0], [12.0, 10.0], [10.0, 12.0], [10.0, 10.0]]   # inside: lon + lat < 22 … and cut cells
    cut = [[10.0, 9.0], [10.11, 9.0], [10.07, 10.1], [10.0, 10.1], [10.0, 9.0]]   # crosses lat 10.05 at lon ≈ 10.072
    shape = geo.Shape([cut])
    cell = (10.0 + 90) * 10 * 3600 + (10.0 + 180) * 10
    assert shape.cell_class(np.array([int(cell)]))[0] == geo.EDGE
    # centre (10.05, 10.05) is inside; a detection near the east edge of the same cell is outside
    assert shape.contains(*_ints([10.05, 10.09], [10.05, 10.095])).tolist() == [True, False]
    assert geo.Shape([triangle]).contains(*_ints([10.5], [10.5])).tolist() == [True]


@pytest.mark.parametrize("region", ["ukraine", "argentina", "california", "amazonas", "australia"])
def test_configured_borders_agree_with_plain_ray_casting(app_env, region):
    geo, config = app_env["store"].geo, app_env["config"]
    shape = geo.region_shape(region)
    rings = border_rings(config.REGIONS[region]["boundary"])
    rng = np.random.default_rng(3)
    vertices = np.concatenate([np.asarray(r) for r in rings])
    near = vertices[rng.integers(0, len(vertices), 300)] + rng.normal(0, 0.02, (300, 2))   # close to the border
    w, s, e, n = config.REGIONS[region]["bbox"]
    anywhere = np.column_stack([rng.uniform(w, e, 300), rng.uniform(s, n, 300)])
    points = np.round(np.concatenate([near, anywhere]), 5)
    lat, lon = _ints(points[:, 1], points[:, 0])
    got = shape.contains(lat, lon)
    want = [inside_border(rings, la / 100000, lo / 100000) for la, lo in zip(lat, lon)]
    assert got.tolist() == want


def test_ukraine_does_not_take_its_neighbours(app_env):
    shape = app_env["store"].geo.region_shape("ukraine")
    places = {  # (lat, lon): inside Ukraine?
        (50.45, 30.52): True,    # Kyiv
        (44.95, 34.10): True,    # Simferopol (internationally recognised borders)
        (48.62, 22.30): True,    # Uzhhorod, near the border
        (47.01, 28.86): False,   # Chișinău, Moldova
        (52.09, 23.69): False,   # Brest, Belarus
        (51.25, 22.57): False,   # Lublin, Poland
        (47.23, 39.72): False,   # Rostov-on-Don, Russia
        (45.44, 28.05): False,   # Galați, Romania
    }
    lat, lon = _ints([p[0] for p in places], [p[1] for p in places])
    assert shape.contains(lat, lon).tolist() == list(places.values())


def test_siberia_is_russia_cut_by_its_rectangle(app_env):
    shape = app_env["store"].geo.region_shape("siberia")
    # Yakutsk (Russia) in; Ulaanbaatar is south of 50°N anyway; a point in Mongolia inside the rectangle is out
    lat, lon = _ints([62.03, 50.5, 55.75], [129.73, 100.0, 37.62])
    assert shape.contains(lat, lon).tolist() == [True, False, False]         # Moscow is outside the rectangle
