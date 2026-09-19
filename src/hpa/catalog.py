"""The procedure catalog: CMS's 70 specified shoppable services, with plain-English aliases.

Searches map to catalog entries rather than to arbitrary codes, so every code the system
scans for is one a person can check. Each entry is `verified` only after someone has
confirmed, against real hospital files, that rows matched on its codes are comparable.
"""

import json
import re
from dataclasses import dataclass
from importlib import resources


@dataclass(frozen=True)
class Service:
    id: str
    category: str
    name: str
    codes: tuple[tuple[str, str], ...]  # (code type, code)
    aliases: tuple[str, ...]
    verified: bool
    notes: str

    @property
    def code_list(self) -> str:
        return ", ".join(f"{t} {c}" for t, c in self.codes)


def load() -> list[Service]:
    raw = json.loads(resources.files("hpa.data").joinpath("shoppable_services.json").read_text())
    return [
        Service(
            id=s["id"],
            category=s["category"],
            name=s["name"],
            codes=tuple((c["type"], c["code"]) for c in s["codes"]),
            aliases=tuple(s["aliases"]),
            verified=s["verified"],
            notes=s["notes"],
        )
        for s in raw["services"]
    ]


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def search(query: str, services: list[Service] | None = None) -> list[Service]:
    """Keyword match over names, aliases and codes; best matches first.

    Deliberately simple. It answers "does the catalog have this?" for the CLI and the
    offline demo; the Claude-backed mapping in milestone 4 handles vaguer phrasing.
    """
    services = services if services is not None else load()
    q = _tokens(query)
    if not q:
        return []
    scored = []
    for s in services:
        if any(code == query.strip() for _, code in s.codes):
            scored.append((100, s))
            continue
        hay = _tokens(s.name) | _tokens(" ".join(s.aliases))
        hits = len(q & hay)
        if hits:
            scored.append((hits / len(q), s))
    scored.sort(key=lambda x: (-x[0], x[1].name))
    return [s for _, s in scored]
