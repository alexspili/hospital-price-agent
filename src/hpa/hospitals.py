"""Hospitals from CMS's Hospital General Information dataset, and `find_hospitals`."""

from dataclasses import dataclass

from hpa.geo import haversine_km, zip_centroid

# Federal (VA, DoD) hospitals are exempt from the price transparency rule, and
# psychiatric, long-term and rural emergency hospitals rarely offer the procedures
# people search for. `types=None` includes everything.
DEFAULT_TYPES = ("Acute Care Hospitals", "Critical Access Hospitals", "Childrens")

# How a hospital's coordinate was obtained, best first. Unresolved hospitals are kept in
# the table (so they can be reported) but never returned as "nearest".
LOCATION_SOURCES = ("address", "zip", "unresolved")


class UnknownZip(ValueError):
    pass


@dataclass(frozen=True)
class Hospital:
    ccn: str
    name: str
    address: str
    city: str
    state: str
    zip: str
    hospital_type: str
    ownership: str
    distance_km: float
    # "address": geocoded street address. "zip": ZIP centroid, so every hospital in that
    # ZIP sits at the same point and the distance can be a mile or two off.
    location_source: str


def load_hospitals(con, hgi_csv: str, coords_csv: str | None = None) -> int:
    """Load the CMS CSV and give every hospital the best coordinate available.

    Priority: geocoded street address (`coords_csv`, from hpa.geocode) > ZIP centroid
    (requires the zcta table) > unresolved. Nothing is guessed from nearby ZIP numbers;
    ZIP numbering says nothing about geography.
    """
    if coords_csv is None:
        coords_sql = "SELECT NULL::VARCHAR AS ccn, NULL::DOUBLE AS lat, NULL::DOUBLE AS lon WHERE false"
        params = [hgi_csv]
    else:
        coords_sql = (
            "SELECT ccn, lat, lon FROM read_csv(?, header = true, "
            "columns = {'ccn': 'VARCHAR', 'lat': 'DOUBLE', 'lon': 'DOUBLE', 'match': 'VARCHAR'})"
        )
        params = [hgi_csv, coords_csv]

    con.execute(
        f"""
        CREATE OR REPLACE TABLE hospitals AS
        WITH raw AS (
            SELECT "Facility ID" AS ccn,
                   "Facility Name" AS name,
                   "Address" AS address,
                   "City/Town" AS city,
                   "State" AS state,
                   lpad("ZIP Code", 5, '0') AS zip,
                   "Hospital Type" AS hospital_type,
                   "Hospital Ownership" AS ownership
            FROM read_csv(?, header = true, all_varchar = true)
        ),
        coords AS ({coords_sql})
        SELECT r.*,
               coalesce(c.lat, z.lat) AS lat,
               coalesce(c.lon, z.lon) AS lon,
               CASE WHEN c.ccn IS NOT NULL THEN 'address'
                    WHEN z.zip IS NOT NULL THEN 'zip'
                    ELSE 'unresolved' END AS location_source
        FROM raw r
        LEFT JOIN coords c ON c.ccn = r.ccn
        LEFT JOIN zcta z ON z.zip = r.zip
        """,
        params,
    )
    return con.execute("SELECT count(*) FROM hospitals").fetchone()[0]


def location_counts(con) -> dict[str, int]:
    rows = con.execute(
        "SELECT location_source, count(*) FROM hospitals GROUP BY 1"
    ).fetchall()
    return {source: dict(rows).get(source, 0) for source in LOCATION_SOURCES}


def find_hospitals(
    con,
    zip_code: str,
    limit: int = 5,
    types: tuple[str, ...] | None = DEFAULT_TYPES,
) -> list[Hospital]:
    """The `limit` hospitals nearest a ZIP centroid, nearest first."""
    if limit < 1:
        raise ValueError(f"limit must be at least 1, got {limit}")
    origin = zip_centroid(con, zip_code)
    if origin is None:
        raise UnknownZip(f"{zip_code} is not a residential ZIP code in the census ZCTA list")

    sql = """
        SELECT ccn, name, address, city, state, zip, hospital_type, ownership,
               lat, lon, location_source
        FROM hospitals
        WHERE location_source <> 'unresolved'
    """
    params: list = []
    if types is not None:
        sql += " AND list_contains(?, hospital_type)"
        params.append(list(types))

    found = []
    for *fields, lat, lon, source in con.execute(sql, params).fetchall():
        distance = haversine_km(origin[0], origin[1], lat, lon)
        found.append(Hospital(*fields, distance_km=round(distance, 1), location_source=source))
    return sorted(found, key=lambda h: (h.distance_km, h.name))[:limit]
