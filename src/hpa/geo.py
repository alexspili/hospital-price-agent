"""ZIP geography. Distances are ZIP centroid to ZIP centroid (Census ZCTA gazetteer)."""

from math import asin, cos, radians, sin, sqrt

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points, in kilometres."""
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))


def load_zcta(con, gazetteer_txt: str) -> int:
    """Load ZCTA centroids from the tab-separated Census gazetteer file.

    The gazetteer pads its last column with trailing spaces, so everything is read as
    text and trimmed before casting.
    """
    con.execute(
        """
        CREATE OR REPLACE TABLE zcta AS
        SELECT trim(GEOID) AS zip,
               CAST(trim(INTPTLAT) AS DOUBLE) AS lat,
               CAST(trim(INTPTLONG) AS DOUBLE) AS lon
        FROM read_csv(?, delim = '\t', header = true, all_varchar = true)
        """,
        [gazetteer_txt],
    )
    return con.execute("SELECT count(*) FROM zcta").fetchone()[0]


def zip_centroid(con, zip_code: str) -> tuple[float, float] | None:
    row = con.execute("SELECT lat, lon FROM zcta WHERE zip = ?", [zip_code]).fetchone()
    return (row[0], row[1]) if row else None
