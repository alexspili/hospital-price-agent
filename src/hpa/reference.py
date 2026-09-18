"""Download the public reference datasets into data/raw/."""

import io
import zipfile
from pathlib import Path

import httpx

from hpa.store import DATA_DIR

RAW_DIR = DATA_DIR / "raw"

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
    dest = RAW_DIR / "Hospital_General_Information.csv"
    dest.write_bytes(client.get(csv_url).raise_for_status().content)
    return dest


def fetch_zcta_gazetteer(client: httpx.Client) -> Path:
    archive = zipfile.ZipFile(io.BytesIO(client.get(ZCTA_GAZETTEER_ZIP).raise_for_status().content))
    name = next(n for n in archive.namelist() if n.endswith(".txt"))
    dest = RAW_DIR / name
    dest.write_bytes(archive.read(name))
    return dest


def fetch_all() -> tuple[Path, Path]:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with httpx.Client(follow_redirects=True, timeout=120) as client:
        return fetch_cms_hospitals(client), fetch_zcta_gazetteer(client)
