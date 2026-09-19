"""Hospitals from CMS's Hospital General Information dataset, and `find_hospitals`."""

from dataclasses import dataclass

from hpa.geo import HAVERSINE_SQL, haversine_km, zip_centroid

# Only federal hospitals are exempt from the price transparency rule (45 CFR 180).
# Psychiatric, long-term, children's and rural emergency hospitals must publish files and
# are included; which of them offer a given service is the catalog's concern.
FEDERAL_TYPES = ("Acute Care - Veterans Administration", "Acute Care - Department of Defense")

# How a hospital's coordinate was obtained, best first. Unresolved hospitals are kept in
# the table (so they can be reported) but never returned as "nearest".
LOCATION_SOURCES = ("address", "zip", "unresolved")

# A geocoded point is accepted only if it lies within this distance of its own ZIP's
# centroid: three times the ZIP's equivalent radius, plus 2 km for small or oddly shaped
# ZIPs. The Census geocoder's Non_Exact matches occasionally land on the wrong side of a
# city; one Houston hospital came back 42 km from its ZIP.
GEOCODE_TOLERANCE_SQL = "3 * z.radius_km + 2"


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
    # For "address" locations, the distance from the query ZIP's centroid to the geocoded
    # point. For "zip" locations, an upper bound: distance between the two ZIP centroids
    # plus the hospital ZIP's radius, so a hospital we can't place precisely never
    # outranks one we can.
    distance_km: float
    location_source: str  # "address" (geocoded street address) or "zip" (ZIP centroid)
    geocode_match: str | None  # Census "Exact" / "Non_Exact", when geocoded
    location_note: str | None  # why a geocode was rejected, if it was

    @property
    def distance_is_bound(self) -> bool:
        return self.location_source == "zip"


def load_hospitals(con, hgi_csv: str, coords_csv: str | None = None) -> int:
    """Load the CMS CSV and give every hospital the best coordinate available.

    Priority: geocoded street address (`coords_csv`, from hpa.geocode), if it passes the
    sanity check against its own ZIP > ZIP centroid (requires the zcta table) >
    unresolved. Nothing is guessed from nearby ZIP numbers; ZIP numbering says nothing
    about geography.
    """
    if coords_csv is None:
        coords_sql = (
            "SELECT NULL::VARCHAR AS ccn, NULL::DOUBLE AS lat, NULL::DOUBLE AS lon,"
            " NULL::VARCHAR AS match WHERE false"
        )
        params = [hgi_csv]
    else:
        coords_sql = (
            "SELECT ccn, lat, lon, match FROM read_csv(?, header = true, "
            "columns = {'ccn': 'VARCHAR', 'lat': 'DOUBLE', 'lon': 'DOUBLE', 'match': 'VARCHAR'})"
        )
        params = [hgi_csv, coords_csv]

    off_km = HAVERSINE_SQL.format(lat1="c.lat", lon1="c.lon", lat2="z.lat", lon2="z.lon")
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
        coords AS ({coords_sql}),
        checked AS (
            SELECT r.*, c.lat AS g_lat, c.lon AS g_lon, c.match,
                   z.lat AS z_lat, z.lon AS z_lon, z.radius_km,
                   CASE WHEN c.ccn IS NOT NULL AND z.zip IS NOT NULL THEN {off_km} END AS off_km,
                   c.ccn IS NOT NULL
                       AND (z.zip IS NULL OR {off_km} <= {GEOCODE_TOLERANCE_SQL}) AS geocode_ok
            FROM raw r
            LEFT JOIN coords c ON c.ccn = r.ccn
            LEFT JOIN zcta z ON z.zip = r.zip
        )
        SELECT ccn, name, address, city, state, zip, hospital_type, ownership,
               CASE WHEN geocode_ok THEN g_lat ELSE z_lat END AS lat,
               CASE WHEN geocode_ok THEN g_lon ELSE z_lon END AS lon,
               CASE WHEN geocode_ok THEN 'address'
                    WHEN z_lat IS NOT NULL THEN 'zip'
                    ELSE 'unresolved' END AS location_source,
               CASE WHEN geocode_ok THEN match END AS geocode_match,
               coalesce(radius_km, 0) AS zip_radius_km,
               CASE WHEN match IS NOT NULL AND NOT geocode_ok THEN
                    format('{{}} geocode rejected: {{:.0f}} km from the {{}} centroid', match, off_km, zip)
               END AS location_note
        FROM checked
        """,
        params,
    )
    return con.execute("SELECT count(*) FROM hospitals").fetchone()[0]


def location_counts(con) -> dict[str, int]:
    rows = con.execute("SELECT location_source, count(*) FROM hospitals GROUP BY 1").fetchall()
    return {source: dict(rows).get(source, 0) for source in LOCATION_SOURCES}


def find_hospitals(
    con,
    zip_code: str,
    limit: int = 5,
    include_federal: bool = False,
) -> list[Hospital]:
    """The `limit` hospitals nearest a ZIP centroid, nearest first."""
    if limit < 1:
        raise ValueError(f"limit must be at least 1, got {limit}")
    origin = zip_centroid(con, zip_code)
    if origin is None:
        raise UnknownZip(f"{zip_code} is not a residential ZIP code in the census ZCTA list")

    sql = """
        SELECT ccn, name, address, city, state, zip, hospital_type, ownership,
               lat, lon, location_source, geocode_match, zip_radius_km, location_note
        FROM hospitals
        WHERE location_source <> 'unresolved'
    """
    params: list = []
    if not include_federal:
        sql += " AND NOT list_contains(?, hospital_type)"
        params.append(list(FEDERAL_TYPES))

    found = []
    for *fields, lat, lon, source, match, radius, note in con.execute(sql, params).fetchall():
        distance = haversine_km(origin[0], origin[1], lat, lon)
        if source == "zip":
            distance += radius
        found.append(Hospital(*fields, round(distance, 1), source, match, note))
    # Ties go to the better-located hospital, then to the name.
    return sorted(found, key=lambda h: (h.distance_km, h.location_source, h.name))[:limit]
