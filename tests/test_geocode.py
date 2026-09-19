from hpa.cli import main
from hpa.geocode import parse_batch_response

# Real rows from the Census batch geocoder, one of each status.
RESPONSE = """\
"450289","1504 TAUB LOOP, HOUSTON, TX, 77030","Match","Exact","1504 TAUB LOOP, HOUSTON, TX, 77030","-95.393749604192,29.712577940163","96065203","R"
"450775","22999 US HIGHWAY 59 N, KINGWOOD, TX, 77325","Match","Non_Exact","22999 US HWY 59 N, KINGWOOD, TX, 77339","-95.252979044113,30.05045433179","638054058","L"
"670122","17201 INTERSTATE 45 SOUTH, THE WOODLANDS, TX, 77385","No_Match"
"454158","1317 S LOOP 336 WEST, CONROE, TX, 77304","Tie"
"""


def test_parse_keeps_matches_only():
    assert list(parse_batch_response(RESPONSE)) == [
        ("450289", 29.712577940163, -95.393749604192, "Exact"),
        ("450775", 30.05045433179, -95.252979044113, "Non_Exact"),
    ]


def test_cli_rejects_nonpositive_limit(capsys):
    try:
        main(["hospitals", "77030", "--limit", "0"])
    except SystemExit as e:
        assert e.code == 2
    assert "at least 1" in capsys.readouterr().err
