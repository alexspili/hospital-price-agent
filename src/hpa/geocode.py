"""Street-address coordinates from the Census Geocoder's free batch endpoint.

ZIP centroids put every hospital in a ZIP at the same point and, for PO-box ZIPs, nowhere
at all. The geocoder matches ~85% of CMS hospital addresses to a point interpolated along
the street's address range (not a rooftop; typically tens of metres off, occasionally the
wrong side of a city, which hospitals.load_hospitals checks for). The rest fall back to
the ZIP centroid or stay unresolved.
"""

import csv
import io
import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

import httpx

BATCH_URL = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
BENCHMARK = "Public_AR_Current"
BATCH_SIZE = 5000  # the endpoint accepts 10,000 rows, but smaller uploads fail less often
STATUSES = {"Match", "No_Match", "Tie"}

AddressRow = tuple[str, str, str, str, str]  # id, street, city, state, zip
Coordinate = tuple[str, float, float, str]  # id, lat, lon, match type (Exact / Non_Exact)


class GeocodeError(RuntimeError):
    """The geocoder answered with something other than one record per submitted address."""


@dataclass(frozen=True)
class Record:
    id: str
    status: str  # Match / No_Match / Tie
    coordinate: Coordinate | None  # set only for Match


def parse_batch_response(text: str) -> Iterator[Record]:
    """One record per response row. A row that isn't in the geocoder's format (an HTML
    error page served with HTTP 200, say) is an error, not a non-match."""
    for row in csv.reader(io.StringIO(text)):
        if not row:
            continue
        if len(row) < 3 or row[2] not in STATUSES:
            raise GeocodeError(f"unexpected geocoder response row: {row[:3]!r}")
        if row[2] != "Match":
            yield Record(row[0], row[2], None)
            continue
        if len(row) < 6 or "," not in row[5]:
            raise GeocodeError(f"Match row without coordinates: {row!r}")
        lon, lat = row[5].split(",")
        yield Record(row[0], "Match", (row[0], float(lat), float(lon), row[3]))


def reconcile(submitted: Iterable[AddressRow], records: Iterable[Record]) -> list[Coordinate]:
    """Every submitted id must come back exactly once, and nothing else may."""
    expected = [r[0] for r in submitted]
    seen: dict[str, Record] = {}
    for rec in records:
        if rec.id in seen:
            raise GeocodeError(f"geocoder returned id {rec.id} twice")
        seen[rec.id] = rec
    missing = [i for i in expected if i not in seen]
    extra = sorted(set(seen) - set(expected))
    if missing or extra:
        raise GeocodeError(
            f"geocoder response does not match the batch: {len(missing)} ids missing"
            f" (first: {missing[:3]}), {len(extra)} unexpected (first: {extra[:3]})"
        )
    return [rec.coordinate for i in expected if (rec := seen[i]).coordinate is not None]


def geocode_batch(client: httpx.Client, rows: Iterable[AddressRow]) -> Iterator[Coordinate]:
    rows = list(rows)
    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start : start + BATCH_SIZE]
        buf = io.StringIO()
        csv.writer(buf).writerows(batch)
        resp = client.post(
            BATCH_URL,
            data={"benchmark": BENCHMARK},
            files={"addressFile": ("addresses.csv", buf.getvalue(), "text/csv")},
        )
        resp.raise_for_status()
        yield from reconcile(batch, parse_batch_response(resp.text))


def hospital_address_rows(hgi_csv: str) -> list[AddressRow]:
    with open(hgi_csv, encoding="utf-8-sig", newline="") as f:
        return [
            (r["Facility ID"], r["Address"], r["City/Town"], r["State"], r["ZIP Code"])
            for r in csv.DictReader(f)
        ]


def write_coords_csv(coords: Iterable[Coordinate], dest: str) -> int:
    """Write via a uniquely named temp file, so a batch that fails midway leaves no
    half-written CSV and two runs can't share one."""
    tmp = f"{dest}.{os.getpid()}.part"
    try:
        with open(tmp, "w", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["ccn", "lat", "lon", "match"])
            n = 0
            for c in coords:
                w.writerow(c)
                n += 1
        os.replace(tmp, dest)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return n
