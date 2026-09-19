"""Street-address coordinates from the Census Geocoder's free batch endpoint.

ZIP centroids put every hospital in a ZIP at the same point and, for PO-box ZIPs, nowhere
at all. The geocoder resolves ~85% of CMS hospital addresses to a rooftop-level point; the
rest fall back to the ZIP centroid or stay unresolved (see hospitals.load_hospitals).
"""

import csv
import io
from collections.abc import Iterable, Iterator

import httpx

BATCH_URL = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
BENCHMARK = "Public_AR_Current"
BATCH_SIZE = 5000  # the endpoint accepts 10,000 rows, but smaller uploads fail less often

AddressRow = tuple[str, str, str, str, str]  # id, street, city, state, zip
Coordinate = tuple[str, float, float, str]  # id, lat, lon, match type (Exact / Non_Exact)


def parse_batch_response(text: str) -> Iterator[Coordinate]:
    """Yield one coordinate per matched row. Ties and non-matches are left out on purpose:
    a Tie means the geocoder found two equally good candidates, which is not a location."""
    for row in csv.reader(io.StringIO(text)):
        if len(row) >= 6 and row[2] == "Match":
            lon, lat = row[5].split(",")
            yield row[0], float(lat), float(lon), row[3]


def geocode_batch(client: httpx.Client, rows: Iterable[AddressRow]) -> Iterator[Coordinate]:
    rows = list(rows)
    for start in range(0, len(rows), BATCH_SIZE):
        buf = io.StringIO()
        csv.writer(buf).writerows(rows[start : start + BATCH_SIZE])
        resp = client.post(
            BATCH_URL,
            data={"benchmark": BENCHMARK},
            files={"addressFile": ("addresses.csv", buf.getvalue(), "text/csv")},
        )
        resp.raise_for_status()
        yield from parse_batch_response(resp.text)


def hospital_address_rows(hgi_csv: str) -> list[AddressRow]:
    with open(hgi_csv, encoding="utf-8-sig", newline="") as f:
        return [
            (r["Facility ID"], r["Address"], r["City/Town"], r["State"], r["ZIP Code"])
            for r in csv.DictReader(f)
        ]


def write_coords_csv(coords: Iterable[Coordinate], dest: str) -> int:
    with open(dest, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["ccn", "lat", "lon", "match"])
        n = 0
        for c in coords:
            w.writerow(c)
            n += 1
    return n
