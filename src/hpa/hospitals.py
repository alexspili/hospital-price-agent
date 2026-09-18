"""Hospitals from CMS's Hospital General Information dataset, and `find_hospitals`."""

from dataclasses import dataclass

from hpa.geo import haversine_km, zip_centroid

# Federal (VA, DoD) hospitals are exempt from the price transparency rule, and
# psychiatric, long-term and rural emergency hospitals rarely offer the procedures
# people search for. `types=None` includes everything.
DEFAULT_TYPES = ("Acute Care Hospitals", "Critical Access Hospitals", "Childrens")


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
    # True when the hospital's ZIP has no census centroid (usually a PO-box ZIP) and
    # the nearest ZIP in the same 3-digit prefix was used instead.
    location_approx: bool


def load_hospitals(con, hgi_csv: str) -> int:
    """Load the CMS CSV and give every hospital a coordinate. Requires the zcta table."""
    con.execute(
        """
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
        fallback AS (
            SELECT r.ccn, z.lat, z.lon
            FROM raw r
            JOIN zcta z ON left(z.zip, 3) = left(r.zip, 3)
            WHERE r.zip NOT IN (SELECT zip FROM zcta)
            QUALIFY row_number() OVER (
                PARTITION BY r.ccn ORDER BY abs(CAST(z.zip AS INT) - CAST(r.zip AS INT)), z.zip
            ) = 1
        )
        SELECT r.*,
               coalesce(z.lat, f.lat) AS lat,
               coalesce(z.lon, f.lon) AS lon,
               z.zip IS NULL AS location_approx
        FROM raw r
        LEFT JOIN zcta z ON z.zip = r.zip
        LEFT JOIN fallback f ON f.ccn = r.ccn
        """,
        [hgi_csv],
    )
    return con.execute("SELECT count(*) FROM hospitals").fetchone()[0]


def find_hospitals(
    con,
    zip_code: str,
    radius_km: float = 25,
    types: tuple[str, ...] | None = DEFAULT_TYPES,
) -> list[Hospital]:
    """Hospitals within `radius_km` of a ZIP centroid, nearest first."""
    origin = zip_centroid(con, zip_code)
    if origin is None:
        raise UnknownZip(f"{zip_code} is not a residential ZIP code in the census ZCTA list")

    sql = """
        SELECT ccn, name, address, city, state, zip, hospital_type, ownership,
               lat, lon, location_approx
        FROM hospitals
        WHERE lat IS NOT NULL
    """
    params: list = []
    if types is not None:
        sql += " AND list_contains(?, hospital_type)"
        params.append(list(types))

    found = []
    for *fields, lat, lon, approx in con.execute(sql, params).fetchall():
        distance = haversine_km(origin[0], origin[1], lat, lon)
        if distance <= radius_km:
            found.append(Hospital(*fields, distance_km=round(distance, 1), location_approx=approx))
    return sorted(found, key=lambda h: (h.distance_km, h.name))
