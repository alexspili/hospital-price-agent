"""How the CLI finds a running `hpa serve`, and asks it for answers.

DuckDB gives one process the file at a time, and while a writer holds it no other process
can open it at all (SPEC "Process model"). So the server drops a marker next to the
database saying where it listens; commands that only read ask the server instead of the
file, and commands that write say so plainly rather than dying on a lock.
"""

import json
import os
from contextlib import contextmanager
from pathlib import Path

import httpx

from hpa.store import DATA_DIR

MARKER = DATA_DIR / "hpa.server.json"


@contextmanager
def marker(url: str, db: str | Path, path: Path = MARKER):
    """Announce a running server for as long as the block lasts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pid": os.getpid(), "url": url, "db": str(db)}))
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def read_marker(path: Path = MARKER) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def running_server(path: Path = MARKER, timeout: float = 1.0) -> str | None:
    """The base URL of a server that is actually up, or None. A marker left behind by a
    killed process is stale, not a server, and is cleaned up here."""
    m = read_marker(path)
    if not m or not m.get("url"):
        return None
    try:
        os.kill(int(m["pid"]), 0)  # signal 0: does this pid exist?
    except PermissionError:
        pass  # it exists and belongs to someone else, so it is not a marker to delete
    except (OSError, ValueError, TypeError):
        path.unlink(missing_ok=True)
        return None
    try:
        r = httpx.get(m["url"] + "/api/health", timeout=timeout)
    except httpx.HTTPError:
        return None
    return m["url"] if r.status_code == 200 else None


def get_prices(url: str, service: str, zips: list[str], ccn: str | None, limit: int,
               show_all: bool = False) -> dict:
    """The server resolves deterministically (its endpoint is public), so an unclear
    name comes back as candidates rather than a Claude answer."""
    params: list[tuple[str, str]] = [("service", service), ("limit", str(limit))]
    params += [("zip", z) for z in zips or []]
    if ccn:
        params.append(("ccn", ccn))
    if show_all:
        params.append(("all", "1"))
    r = httpx.get(url + "/api/prices", params=params, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(r.json().get("detail", r.text))
    return r.json()
