"""Download the public reference datasets into data/raw/."""

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


def fetch_cms_hospitals(client: httpx.Client) -> Path:
    meta = client.get(CMS_HOSPITAL_DATASET).raise_for_status().json()
    csv_url = next(
        d["downloadURL"] for d in meta["distribution"] if d.get("mediaType") == "text/csv"
    )
    HGI_CSV.write_bytes(client.get(csv_url).raise_for_status().content)
    return HGI_CSV


def fetch_zcta_gazetteer(client: httpx.Client) -> Path:
    archive = zipfile.ZipFile(io.BytesIO(client.get(ZCTA_GAZETTEER_ZIP).raise_for_status().content))
    name = next(n for n in archive.namelist() if n.endswith(".txt"))
    dest = RAW_DIR / name
    dest.write_bytes(archive.read(name))
    return dest


def geocode_hospitals(client: httpx.Client, hgi_csv: Path) -> tuple[Path, int]:
    """Geocode every hospital address (about a minute for the whole country)."""
    rows = geocode.hospital_address_rows(str(hgi_csv))
    matched = geocode.write_coords_csv(geocode.geocode_batch(client, rows), str(COORDS_CSV))
    return COORDS_CSV, matched


def client() -> httpx.Client:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    return httpx.Client(follow_redirects=True, timeout=300)
