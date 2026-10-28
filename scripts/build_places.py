"""Makes backend/geodata/places.tsv.gz, the offline place list photo dates and places use (AI-24).

    python scripts/build_places.py cities15000.txt admin1CodesASCII.txt countryInfo.txt

The three files come from https://download.geonames.org/export/dump/ (GeoNames, CC BY 4.0:
credit GeoNames where the place names are shown). cities15000 lists the ~33,000 towns with more
than 15,000 people; cities5000 or cities1000 give more towns and a bigger file.

Each output line: name, region, country, latitude, longitude, population (tab-separated, gzip).
"""

from __future__ import annotations

import gzip
import os
import sys

OUT = os.path.join(os.path.dirname(__file__), "..", "backend", "geodata", "places.tsv.gz")


def _table(path: str, key_cols: int, value_col: int) -> dict[str, str]:
    out = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.rstrip("\n").split("\t")
            out[".".join(parts[:key_cols])] = parts[value_col]
    return out


def build(cities: str, admin1: str, countries: str, out: str = OUT) -> int:
    regions = _table(admin1, 1, 1)  # "IT.07" -> "Lazio"
    names = _table(countries, 1, 4)  # "IT" -> "Italy"
    rows = 0
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(cities, encoding="utf-8") as src, gzip.open(out, "wt", encoding="utf-8", compresslevel=9) as dst:
        for line in src:
            p = line.rstrip("\n").split("\t")
            if len(p) < 11:
                continue
            name, lat, lon, cc, a1, pop = p[1], p[4], p[5], p[8], p[10], p[14] if len(p) > 14 else ""
            region = regions.get(f"{cc}.{a1}", "")
            dst.write(
                f"{name}\t{region}\t{names.get(cc, cc)}\t{float(lat):.4f}\t{float(lon):.4f}\t{pop if pop.isdigit() else ''}\n"
            )
            rows += 1
    return rows


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    print(f"{build(*sys.argv[1:4])} places written to {os.path.normpath(OUT)}")
