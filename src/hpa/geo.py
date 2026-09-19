"""ZIP geography from the Census ZCTA gazetteer: centroids and an equivalent radius."""

from math import asin, cos, radians, sin, sqrt

EARTH_RADIUS_KM = 6371.0088
KM_PER_MILE = 1.609344


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points, in kilometres."""
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))


# Same formula, for use inside DuckDB queries.
HAVERSINE_SQL = (
    "2 * 6371.0088 * asin(sqrt(sin(radians({lat2} - {lat1}) / 2) ^ 2"
    " + cos(radians({lat1})) * cos(radians({lat2})) * sin(radians({lon2} - {lon1}) / 2) ^ 2))"
)


def load_zcta(con, gazetteer_txt: str) -> int:
    """Load ZCTA centroids from the tab-separated Census gazetteer file.

    `radius_km` is the radius of a circle with the ZCTA's land area: a rough size for the
    ZIP, used to bound distances for hospitals we can only place at the centroid and to
    sanity-check geocoded points. The gazetteer pads its last column with spaces, so
    everything is read as text and trimmed before casting.
    """
    con.execute(
        """
        CREATE OR REPLACE TABLE zcta AS
        SELECT trim(GEOID) AS zip,
               CAST(trim(INTPTLAT) AS DOUBLE) AS lat,
               CAST(trim(INTPTLONG) AS DOUBLE) AS lon,
               sqrt(CAST(trim(ALAND) AS DOUBLE) / pi()) / 1000 AS radius_km
        FROM read_csv(?, delim = '\t', header = true, all_varchar = true)
        """,
        [gazetteer_txt],
    )
    return con.execute("SELECT count(*) FROM zcta").fetchone()[0]


def zip_centroid(con, zip_code: str) -> tuple[float, float] | None:
    row = con.execute("SELECT lat, lon FROM zcta WHERE zip = ?", [zip_code]).fetchone()
    return (row[0], row[1]) if row else None
