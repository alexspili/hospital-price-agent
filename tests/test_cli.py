import pytest

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
