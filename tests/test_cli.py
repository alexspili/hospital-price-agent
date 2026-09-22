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


def test_prices_without_setup_says_so(tmp_path, capsys):
    """A missing file is not a lock: the answer is what builds one."""
    assert main(["--db", str(tmp_path / "none.duckdb"), "prices", "knee mri", "77030"]) == 1
    err = capsys.readouterr().err
    assert "hpa setup" in err and "another process" not in err


def test_a_zip_is_required(capsys):
    for command in (["prices", "knee mri"], ["locate"], ["scan"]):
        with pytest.raises(SystemExit) as e:
            main(command)
        assert e.value.code == 2
    assert "ZIP" in capsys.readouterr().err


def test_a_hospital_never_looked_for_says_so(capsys):
    """"No price file located" alone reads as a finding; the detail says it was never looked for."""
    cli.print_hospital({"name": "Cedars-Sinai Medical Center", "verdict": "no price file located",
                        "detail": "run `hpa locate` first", "url": None, "file_date": None,
                        "line_count": 0, "headline": None, "lines": []}, show_all=False)
    assert capsys.readouterr().out.strip() == "Cedars-Sinai Medical Center: no price file located — run `hpa locate` first"


def test_a_missing_negotiated_range_is_one_dash_and_hidden_lines_are_counted(capsys):
    line = {"code_type": "CPT", "code": "73721", "other_codes": [], "cash": 1230.0, "gross": 2460.0, "min": None, "max": None,
            "context": "both, facility", "ref": "item 13569/charge 1", "description": "HC MRI LOWER EXT JOINT W/O CONTRA", "note": None}
    cli.print_hospital({"name": "Houston Methodist Hospital", "verdict": "comparable", "detail": "",
                        "url": "https://example.test/f.json", "file_date": "2026-04-01",
                        "line_count": 3, "headline": line, "lines": [line, line, line]}, show_all=False)
    out = capsys.readouterr().out
    assert "negotiated —  [both, facility]" in out and "—–—" not in out
    assert "(file dated 2026-04-01; https://example.test/f.json)" in out  # no ellipsis on a short URL
    assert "… 2 more lines (--all)" in out


def test_the_trace_ends_with_who_has_no_price_then_the_pairs_that_have_two(capsys):
    from hpa import pipeline
    hs = [{"name": "A", "headline": {"setting": "outpatient", "billing_class": "facility", "modifiers": None}},
          {"name": "B", "headline": None},
          {"name": "C", "headline": {"setting": "outpatient", "billing_class": "facility", "modifiers": None}}]
    lines = pipeline.pair_lines(hs)
    assert lines[0] == "no priced line for this service at B; no pair with them can be compared"
    assert lines[1].startswith("compare: A vs C: comparable")
    assert len(lines) == 2
    assert pipeline.pair_lines(hs[:2])[1] == "only one hospital has a price for this service; nothing to put side by side"
    assert pipeline.short_reason("no cms-hpt.txt or linked file located: a.com: ConnectError; b.org: 404").startswith("no index file or standard-charges link")
    assert pipeline.short_reason("file URL failed: HTTP 403") == "file URL failed: HTTP 403"
