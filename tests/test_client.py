"""Finding a running server, and not being fooled by one that has gone."""

import json

import httpx
import pytest

from hpa import client


@pytest.fixture
def marker(tmp_path):
    return tmp_path / "hpa.server.json"


def answering(status: int = 200):
    return httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(status, json={"status": "ok"})))


def test_no_marker_means_no_server(marker):
    assert client.running_server(marker) is None


def test_a_marker_from_a_dead_process_is_cleaned_up(marker, monkeypatch):
    # uvicorn re-raises the signal that stopped it, so a killed server never gets to
    # tidy up: the pid decides, not the file.
    marker.write_text(json.dumps({"pid": 2 ** 30, "url": "http://127.0.0.1:8000"}))
    assert client.running_server(marker) is None
    assert not marker.exists()


def test_a_live_pid_that_does_not_answer_is_not_our_server(marker, monkeypatch):
    marker.write_text(json.dumps({"pid": 1, "url": "http://127.0.0.1:8000"}))
    monkeypatch.setattr(client.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("refused")))
    assert client.running_server(marker) is None
    assert marker.exists()  # pid 1 exists, so the marker is not ours to delete


def test_a_healthy_server_is_found(marker, monkeypatch, tmp_path):
    monkeypatch.setattr(client.httpx, "get", lambda *a, **k: httpx.Response(200, json={"status": "ok"}))
    with client.marker("http://127.0.0.1:8000", tmp_path / "hpa.duckdb", path=marker):
        assert client.running_server(marker) == "http://127.0.0.1:8000"
        assert json.loads(marker.read_text())["db"].endswith("hpa.duckdb")
    assert not marker.exists()  # the block gave it back
