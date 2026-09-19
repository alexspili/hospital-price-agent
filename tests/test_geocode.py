import httpx
import pytest

from hpa import geocode
from hpa.geocode import geocode_batch, parse_batch_response, write_coords_csv

# Real rows from the Census batch geocoder, one of each status.
RESPONSE = """\
"450289","1504 TAUB LOOP, HOUSTON, TX, 77030","Match","Exact","1504 TAUB LOOP, HOUSTON, TX, 77030","-95.393749604192,29.712577940163","96065203","R"
"450775","22999 US HIGHWAY 59 N, KINGWOOD, TX, 77325","Match","Non_Exact","22999 US HWY 59 N, KINGWOOD, TX, 77339","-95.252979044113,30.05045433179","638054058","L"
"670122","17201 INTERSTATE 45 SOUTH, THE WOODLANDS, TX, 77385","No_Match"
"454158","1317 S LOOP 336 WEST, CONROE, TX, 77304","Tie"
"""

ROWS = [
    ("450289", "1504 TAUB LOOP", "HOUSTON", "TX", "77030"),
    ("450775", "22999 US HIGHWAY 59 N", "KINGWOOD", "TX", "77325"),
    ("670122", "17201 INTERSTATE 45 SOUTH", "THE WOODLANDS", "TX", "77385"),
]


def test_parse_keeps_matches_only():
    assert list(parse_batch_response(RESPONSE)) == [
        ("450289", 29.712577940163, -95.393749604192, "Exact"),
        ("450775", 30.05045433179, -95.252979044113, "Non_Exact"),
    ]


def client_returning(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_rows_are_split_at_the_batch_boundary(monkeypatch):
    monkeypatch.setattr(geocode, "BATCH_SIZE", 2)
    uploads = []

    def handler(request):
        uploads.append(request.content.count(b"\n"))
        return httpx.Response(200, text=RESPONSE)

    list(geocode_batch(client_returning(handler), ROWS))
    assert len(uploads) == 2  # 3 rows, batches of 2


def test_http_failure_raises_and_writes_nothing(tmp_path):
    def handler(request):
        return httpx.Response(503, text="Service Unavailable")

    dest = tmp_path / "coords.csv"
    with pytest.raises(httpx.HTTPStatusError):
        write_coords_csv(geocode_batch(client_returning(handler), ROWS), str(dest))
    assert not dest.exists()
    assert not (tmp_path / "coords.csv.part").exists()


def test_write_coords_csv_uses_lf_line_endings(tmp_path):
    dest = tmp_path / "coords.csv"
    assert write_coords_csv(parse_batch_response(RESPONSE), str(dest)) == 2
    assert b"\r" not in dest.read_bytes()
