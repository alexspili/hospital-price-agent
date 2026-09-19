"""The fuzzy steps that go to Claude, and nothing else.

Two calls, both cached in DuckDB by (model, prompt version, input):
- `find_hospital_website`: a web search for a hospital's official site, when the
  deterministic domain guesses have no cms-hpt.txt.
- `pick_entry`: choose among near-duplicate index entries using the hospital's address.
"""

import hashlib
import json
import os
from dataclasses import dataclass

from dotenv import load_dotenv

from hpa.discovery import HptEntry
from hpa.hospitals import Hospital

MODEL = "claude-opus-5"
PROMPT_VERSION = "1"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

WEBSITE_SCHEMA = {
    "type": "object",
    "properties": {
        "domain": {"type": ["string", "null"], "description": "bare domain of the official site, e.g. houstonmethodist.org, or null"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "why": {"type": "string"},
        "sources": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["domain", "confidence", "why", "sources"],
    "additionalProperties": False,
}

CONFIRM_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": ["string", "null"], "description": "the catalog id that the user's words mean, or null"},
        "question": {"type": ["string", "null"], "description": "a short question to ask the user when no single entry fits"},
        "why": {"type": "string"},
    },
    "required": ["id", "question", "why"],
    "additionalProperties": False,
}

PICK_SCHEMA = {
    "type": "object",
    "properties": {
        "index": {"type": ["integer", "null"], "description": "0-based index of the matching entry, or null if none clearly matches"},
        "why": {"type": "string"},
    },
    "required": ["index", "why"],
    "additionalProperties": False,
}


def have_api_key() -> bool:
    load_dotenv()
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def make_client():
    import anthropic

    load_dotenv()
    return anthropic.Anthropic()


@dataclass
class Claude:
    """Thin wrapper so tests can pass a fake `client` and an in-memory cache."""

    client: object
    con: object | None = None  # DuckDB connection with an llm_cache table, or None

    def _cached(self, fn: str, payload: dict, run):
        key = hashlib.sha256(json.dumps([MODEL, PROMPT_VERSION, fn, payload], sort_keys=True).encode()).hexdigest()
        if self.con is not None:
            row = self.con.execute("SELECT output FROM llm_cache WHERE key = ?", [key]).fetchone()
            if row:
                return json.loads(row[0]), True
        out = run()
        if self.con is not None:
            self.con.execute(
                "INSERT INTO llm_cache VALUES (?, ?, ?, ?, ?, now())",
                [key, MODEL, PROMPT_VERSION, json.dumps(payload, sort_keys=True), json.dumps(out)],
            )
        return out, False

    def _json_call(self, prompt: str, schema: dict, tools: list | None = None) -> dict:
        resp = self.client.beta.messages.create(
            model=MODEL,
            max_tokens=4000,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            tools=tools or [],
            messages=[{"role": "user", "content": prompt}],
        )
        if resp.stop_reason == "refusal":
            raise RuntimeError("model declined the request")
        text = next(b.text for b in resp.content if b.type == "text")
        return json.loads(text)

    def find_hospital_website(self, h: Hospital) -> tuple[str | None, str]:
        payload = {"ccn": h.ccn, "name": h.name, "address": h.address, "city": h.city, "state": h.state, "zip": h.zip}
        prompt = (
            "Find the official website of this hospital (the hospital's or its health system's own "
            "domain, not a directory, review site or news article). Use web search. Answer with the "
            "bare domain only.\n\n" + json.dumps(payload, indent=1)
        )
        tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}]
        out, cached = self._cached("website", payload, lambda: self._json_call(prompt, WEBSITE_SCHEMA, tools))
        why = f"{out['confidence']} confidence, {out['why']}" + (" [cached]" if cached else "")
        domain = (out.get("domain") or "").lower().removeprefix("https://").removeprefix("http://").strip("/ ")
        return (domain or None), why

    def confirm_service(self, query: str, resolution) -> tuple[object | None, str]:
        """The resolver could not settle the query. Ask Claude to pick among its candidates
        (never outside them) or to phrase the clarifying question. Returns (service, why or
        question)."""
        cands = list(resolution.candidates)
        if not cands:
            return None, resolution.reason
        payload = {
            "query": query,
            "resolver": {"verdict": resolution.verdict, "reason": resolution.reason},
            "candidates": [{"id": c.id, "name": c.name, "codes": c.code_list, "qualifiers": c.qualifiers, "aliases": list(c.aliases)} for c in cands],
        }
        prompt = (
            "A user typed a procedure name. A deterministic matcher narrowed it to these entries of "
            "CMS's list of 70 shoppable services but could not settle it. If exactly one entry is what "
            "the user plainly means, return its id. If the user asked for a variant the list does not "
            "have, or the words fit several entries, return null and a one-sentence question to ask "
            "the user. Never pick an entry that is not in the candidates.\n\n" + json.dumps(payload, indent=1)
        )
        out, cached = self._cached("confirm", payload, lambda: self._json_call(prompt, CONFIRM_SCHEMA))
        suffix = " [cached]" if cached else ""
        chosen = next((c for c in cands if c.id == out.get("id")), None)
        if chosen is None:
            return None, (out.get("question") or out["why"]) + suffix
        return chosen, out["why"] + suffix

    def pick_entry(self, h: Hospital, candidates: list[HptEntry]) -> tuple[HptEntry | None, str]:
        payload = {
            "hospital": {"name": h.name, "address": h.address, "city": h.city, "zip": h.zip},
            "entries": [{"location_name": e.location_name, "mrf_url": e.mrf_url} for e in candidates],
        }
        prompt = (
            "A hospital from the CMS dataset must be matched to one entry of a health system's price "
            "transparency index (cms-hpt.txt). The entries below are the closest by name. Pick the one "
            "that is this specific facility, using the address and any location hints in names or URLs. "
            "If none clearly is, answer null. Do not guess.\n\n" + json.dumps(payload, indent=1)
        )
        out, cached = self._cached("pick", payload, lambda: self._json_call(prompt, PICK_SCHEMA))
        why = out["why"] + (" [cached]" if cached else "")
        i = out.get("index")
        if i is None or not 0 <= i < len(candidates):
            return None, why
        return candidates[i], why
