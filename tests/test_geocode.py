import csv
import io

import httpx
import pytest

from hpa import geocode
from hpa.geocode import GeocodeError, geocode_batch, parse_batch_response, reconcile, write_coords_csv

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
    ("454158", "1317 S LOOP 336 WEST", "CONROE", "TX", "77304"),
]


def test_parse_yields_every_status_and_coordinates_for_matches():
    records = list(parse_batch_response(RESPONSE))
    assert [(r.id, r.status) for r in records] == [
        ("450289", "Match"), ("450775", "Match"), ("670122", "No_Match"), ("454158", "Tie"),
    ]
    assert records[0].coordinate == ("450289", 29.712577940163, -95.393749604192, "Exact")
    assert records[2].coordinate is None


def test_html_error_page_is_an_error_not_a_nonmatch():
    with pytest.raises(GeocodeError, match="unexpected geocoder response"):
        list(parse_batch_response("<html><body>Service unavailable</body></html>"))


def test_reconcile_returns_coordinates_in_submitted_order():
    coords = reconcile(ROWS, parse_batch_response(RESPONSE))
    assert [c[0] for c in coords] == ["450289", "450775"]


@pytest.mark.parametrize(
    "text, message",
    [
        (RESPONSE.splitlines()[0] + "\n", "3 ids missing"),
        (RESPONSE + RESPONSE.splitlines()[0] + "\n", "twice"),
        (RESPONSE + '"999999","x","No_Match"\n', "1 unexpected"),
    ],
)
def test_reconcile_rejects_missing_duplicate_and_unexpected_ids(text, message):
    with pytest.raises(GeocodeError, match=message):
        reconcile(ROWS, parse_batch_response(text))


def client_returning(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def echo_handler(request):
    """Answer like the geocoder: one No_Match row per uploaded address."""
    body = request.content.decode(errors="replace")
    csv_part = body.split("\r\n\r\n", 2)[-1]  # crude multipart: last part is the CSV
    csv_part = csv_part.split("\r\n--", 1)[0]
    ids = [row[0] for row in csv.reader(io.StringIO(csv_part)) if row]
    echo_handler.batches.append(ids)
    return httpx.Response(200, text="".join(f'"{i}","addr","No_Match"\n' for i in ids))


def test_rows_are_split_at_the_batch_boundary_each_id_once(monkeypatch):
    monkeypatch.setattr(geocode, "BATCH_SIZE", 3)
    echo_handler.batches = []
    assert list(geocode_batch(client_returning(echo_handler), ROWS)) == []
    assert echo_handler.batches == [["450289", "450775", "670122"], ["454158"]]


def test_response_for_a_different_batch_is_rejected():
    def handler(request):
        return httpx.Response(200, text=RESPONSE)  # ids from ROWS, but we submit others

    with pytest.raises(GeocodeError, match="does not match the batch"):
        list(geocode_batch(client_returning(handler), [("1", "a", "b", "TX", "77002")]))


def test_http_failure_raises_and_writes_nothing(tmp_path):
    def handler(request):
        return httpx.Response(503, text="Service Unavailable")

    dest = tmp_path / "coords.csv"
    with pytest.raises(httpx.HTTPStatusError):
        write_coords_csv(geocode_batch(client_returning(handler), ROWS), str(dest))
    assert list(tmp_path.iterdir()) == []


def test_write_coords_csv_uses_lf_line_endings(tmp_path):
    dest = tmp_path / "coords.csv"
    coords = reconcile(ROWS, parse_batch_response(RESPONSE))
    assert write_coords_csv(coords, str(dest)) == 2
    assert b"\r" not in dest.read_bytes()
