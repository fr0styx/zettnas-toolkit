# Place names

`places.tsv.gz` is the offline list photo places are named from (AI-24): name, region, country,
latitude and longitude of the towns with more than 15,000 people.

Data from [GeoNames](https://www.geonames.org/), licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); converted, not otherwise changed.
Made from `cities15000.txt`, `admin1CodesASCII.txt` and `countryInfo.txt` of
https://download.geonames.org/export/dump/ with `python scripts/build_places.py` (downloaded 2026-10-28).
