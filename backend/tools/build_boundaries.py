"""
build_boundaries.py — (RE)BUILD geodata/boundaries.geojson FROM NATURAL EARTH

The real borders used by the region filter (geo.py) are a small extract of the public-domain
Natural Earth 1:10m data. Run this only to add a region or refresh the borders:

    python tools/build_boundaries.py                      # downloads Natural Earth from GitHub
    python tools/build_boundaries.py --from-folder DIR    # uses already downloaded *.geojson files

Which borders are extracted is decided by config.REGIONS: every "boundary" value
("country:UKR" = ISO 3166-1 alpha-3, "state:US-CA" = ISO 3166-2).

Countries come from the `ne_10m_admin_0_countries_ukr` variant: Natural Earth publishes several
"points of view"; this one draws Ukraine in its internationally recognised borders (with Crimea).
"""

import argparse
import json
import sys
import urllib.request
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
import config  # noqa: E402

BASE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
FILES = {"country": "ne_10m_admin_0_countries_ukr.geojson", "state": "ne_10m_admin_1_states_provinces.geojson"}
KEYS = {"country": ("ADM0_A3",), "state": ("iso_3166_2",)}
OUTPUT = BACKEND / "geodata" / "boundaries.geojson"


def load(kind, folder):
    name = FILES[kind]
    if folder:
        return json.loads((Path(folder) / name).read_text(encoding="utf-8"))
    print(f"downloading {name} …")
    with urllib.request.urlopen(BASE + name, timeout=300) as response:
        return json.load(response)


def rounded(geometry):
    polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    return {"type": "MultiPolygon",
            "coordinates": [[[[round(x, 5), round(y, 5)] for x, y, *_ in ring] for ring in polygon]
                            for polygon in polygons]}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Extract the region borders from Natural Earth.")
    parser.add_argument("--from-folder", help="folder with the Natural Earth *.geojson files")
    args = parser.parse_args(argv)
    wanted = sorted({info["boundary"] for info in config.REGIONS.values() if info.get("boundary")})
    features, sources = [], {}
    for boundary in wanted:
        kind, code = boundary.split(":", 1)
        if kind not in sources:
            sources[kind] = load(kind, args.from_folder)
        found = [f for f in sources[kind]["features"]
                 if any(f["properties"].get(key) == code for key in KEYS[kind])]
        if len(found) != 1:
            print(f"{boundary}: expected exactly one Natural Earth feature, found {len(found)}")
            return 1
        properties = found[0]["properties"]
        features.append({"type": "Feature", "id": boundary,
                         "properties": {"name": properties.get("NAME") or properties.get("name")},
                         "geometry": rounded(found[0]["geometry"])})
        print(f"{boundary}: {features[-1]['properties']['name']}")
    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(json.dumps({
        "type": "FeatureCollection",
        "source": "Natural Earth 1:10m Cultural Vectors (naturalearthdata.com), public domain",
        "files": FILES, "features": features}, separators=(",", ":")), encoding="utf-8")
    print(f"written: {OUTPUT} ({OUTPUT.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
