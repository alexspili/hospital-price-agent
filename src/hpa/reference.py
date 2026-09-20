"""Download the public reference datasets into data/raw/, and record where each came from.

Every download returns a provenance record as well as the file: the URL that answered, the
dataset's own release date where it publishes one, the checksum of what arrived, and its
size. Those rows are what `hpa hospitals --verbose` prints, so a count on screen can
always be traced to a dated file (SPEC "Storage").
"""

import hashlib
import io
import zipfile
from pathlib import Path

import httpx

from hpa import geocode
from hpa.store import DATA_DIR

RAW_DIR = DATA_DIR / "raw"
HGI_CSV = RAW_DIR / "Hospital_General_Information.csv"
COORDS_CSV = RAW_DIR / "hospital_coords.csv"

# CMS versions the CSV's URL on every release, so resolve it through the metastore API.
CMS_HOSPITAL_DATASET = (
    "https://data.cms.gov/provider-data/api/1/metastore/schemas/dataset/items/xubh-q36u"
)
ZCTA_GAZETTEER_ZIP = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
    "2024_Gazetteer/2024_Gaz_zcta_national.zip"
)


def _provenance(name: str, url: str, path: Path, release_date: str | None = None, note: str = "") -> dict:
    data = path.read_bytes()
    return {"name": name, "url": url, "release_date": release_date, "note": note,
            "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}


def fetch_cms_hospitals(client: httpx.Client) -> tuple[Path, dict]:
    meta = client.get(CMS_HOSPITAL_DATASET).raise_for_status().json()
    csv_url = next(
        d["downloadURL"] for d in meta["distribution"] if d.get("mediaType") == "text/csv"
    )
    HGI_CSV.write_bytes(client.get(csv_url).raise_for_status().content)
    # CMS versions the file on every release; `modified` is the release it served us.
    release = meta.get("modified") or meta.get("issued")
    return HGI_CSV, _provenance("CMS Hospital General Information", csv_url, HGI_CSV, release,
                                note=meta.get("title", ""))


def fetch_zcta_gazetteer(client: httpx.Client) -> tuple[Path, dict]:
    archive = zipfile.ZipFile(io.BytesIO(client.get(ZCTA_GAZETTEER_ZIP).raise_for_status().content))
    name = next(n for n in archive.namelist() if n.endswith(".txt"))
    dest = RAW_DIR / name
    dest.write_bytes(archive.read(name))
    return dest, _provenance("Census ZCTA gazetteer", ZCTA_GAZETTEER_ZIP, dest, release_date="2024",
                             note=name)


def geocode_hospitals(client: httpx.Client, hgi_csv: Path) -> tuple[Path, int, dict]:
    """Geocode every hospital address (about a minute for the whole country)."""
    rows = geocode.hospital_address_rows(str(hgi_csv))
    matched = geocode.write_coords_csv(geocode.geocode_batch(client, rows), str(COORDS_CSV))
    record = _provenance("Census Geocoder", geocode.BATCH_URL, COORDS_CSV,
                         note=f"benchmark {geocode.BENCHMARK}; {matched:,} of {len(rows):,} addresses matched")
    record["rows"] = matched
    return COORDS_CSV, matched, record


def client() -> httpx.Client:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    return httpx.Client(follow_redirects=True, timeout=300)
