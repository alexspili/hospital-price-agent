import pytest

from hpa import cli
from hpa.cli import main


def test_rejects_nonpositive_limit(capsys):
    with pytest.raises(SystemExit) as e:
        main(["hospitals", "77030", "--limit", "0"])
    assert e.value.code == 2
    assert "at least 1" in capsys.readouterr().err


def test_hospitals_without_setup(tmp_path, capsys):
    assert main(["--db", str(tmp_path / "none.duckdb"), "hospitals", "77030"]) == 1
    assert "hpa setup" in capsys.readouterr().err


def test_catalog_verdicts(capsys):
    assert main(["catalog", "knee mri"]) == 0
    assert capsys.readouterr().out.startswith("selected: MRI scan of leg joint (CPT 73721)")
    assert main(["catalog", "knee mri with contrast"]) == 1
    assert capsys.readouterr().out.startswith("unsupported variant:")


def test_a_running_server_owns_the_database(tmp_path, monkeypatch, capsys):
    """While `hpa serve` holds the file, commands that need it say so (SPEC "Process
    model"), instead of failing with a DuckDB lock error."""
    monkeypatch.setattr(cli.client, "running_server", lambda: "http://127.0.0.1:8000")
    db = tmp_path / "hpa.duckdb"
    db.touch()
    assert cli.main(["--db", str(db), "locate", "77030"]) == 1
    err = capsys.readouterr().err
    assert "http://127.0.0.1:8000 owns the database" in err and "stop it" in err


def test_prices_asks_the_server_when_one_is_running(monkeypatch, capsys):
    monkeypatch.setattr(cli.client, "running_server", lambda: "http://127.0.0.1:8000")
    asked = {}

    def fake_get_prices(url, service, zips, ccn, limit, show_all=False, no_llm=False):
        asked.update(url=url, service=service, zips=zips, limit=limit)
        return {
            "status": "ok", "resolver": None, "note": None,
            "service": {"id": "cpt-73721", "name": "MRI scan of leg joint", "codes": "CPT 73721", "reviewed": True},
            "hospitals": [{
                "ccn": "450289", "name": "Harris Health", "verdict": "comparable", "detail": "",
                "url": "https://example.test/f.csv", "file_date": "2026-09-01", "line_count": 1, "lines": [],
                "headline": {"cash": 2735.8, "gross": 5471.59, "min": 431.06, "max": 574.74,
                             "context": "outpatient, facility", "ref": "row 1570", "description": "MRI JOINT"},
            }],
        }

    monkeypatch.setattr(cli.client, "get_prices", fake_get_prices)
    assert cli.main(["prices", "knee mri", "77030"]) == 0
    out = capsys.readouterr().out
    assert asked == {"url": "http://127.0.0.1:8000", "service": "knee mri", "zips": ["77030"], "limit": 5}
    assert "MRI scan of leg joint (CPT 73721)  [reviewed]" in out
    assert "cash $2,735.80  gross $5,471.59  negotiated $431.06–$574.74  [outpatient, facility]  row 1570" in out
