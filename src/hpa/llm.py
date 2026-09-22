"""The fuzzy steps that go to Claude, and nothing else.

Two calls, both cached in DuckDB by (model, prompt version, input):
- `find_hospital_website`: a web search for a hospital's official site, when the
  deterministic domain guesses have no cms-hpt.txt.
- `pick_entry`: choose among near-duplicate index entries using the hospital's address.
"""

import hashlib
import json
from urllib.parse import urlsplit
import os
from dataclasses import dataclass

from dotenv import load_dotenv

from hpa.discovery import HptEntry
from hpa.hospitals import Hospital

MODEL = "claude-opus-5"
# What one service-name confirmation costs at list price, so a CLI user is told before
# a call is made (a whole-catalog fallback is the dearest of the three calls).
CONFIRM_COST_USD = 0.043
# Per call, so changing one prompt does not throw away the answers already bought for the
# other two (SPEC "Caching": cache keys include versions).
PROMPT_VERSIONS = {"website": "2", "pick": "1", "confirm": "2"}
PROMPT_VERSION = "1"  # kept for the llm_cache rows written before the split
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# USD per million tokens, first-party Claude API rates. Cache reads are a tenth of input
# and cache writes a quarter more; a cached *answer* costs nothing at all, because it
# never leaves DuckDB (see `_cached`).
PRICES = {"claude-opus-5": (5.00, 25.00)}
CACHE_READ_SHARE, CACHE_WRITE_SHARE = 0.1, 1.25

WEBSITE_SCHEMA = {
    "type": "object",
    "properties": {
        "domain": {"type": ["string", "null"], "description": "bare domain of the official site, e.g. houstonmethodist.org, or null"},
        "page_url": {"type": ["string", "null"], "description": "the URL of the hospital's own page on that site, if the search found one; a system may keep its hospitals on a subdomain such as healthcare.ascension.org"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "why": {"type": "string"},
        "sources": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["domain", "page_url", "confidence", "why", "sources"],
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


class SpendCapReached(RuntimeError):
    """Today's model budget is gone. The deterministic pipeline carries on without Claude."""


def _price_for(model: str) -> tuple[float, float]:
    """The list price for a model id. A dated snapshot of a known model ("claude-opus-5-2026…")
    costs what the model costs; an id nobody priced is charged at the dearest known rate.
    That is an estimate, not a ceiling: it keeps a fallback from recording as free, and
    PRICES is where a new model gets its real rate."""
    if model in PRICES:
        return PRICES[model]
    for known, price in PRICES.items():
        if model.startswith(known):
            return price
    return max(PRICES.values())


def cost_usd(model: str, usage) -> float:
    """What one call cost, from the usage the API reports."""
    in_rate, out_rate = _price_for(model)
    read = getattr(usage, "cache_read_input_tokens", 0) or 0
    write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    return (
        (usage.input_tokens or 0) * in_rate
        + read * in_rate * CACHE_READ_SHARE
        + write * in_rate * CACHE_WRITE_SHARE
        + (usage.output_tokens or 0) * out_rate
    ) / 1_000_000


def spend_today(con) -> float:
    """What has been spent on the model since midnight, from the recorded usage."""
    if con is None:
        return 0.0
    row = con.execute("SELECT coalesce(sum(usd), 0) FROM llm_spend WHERE called_at >= current_date").fetchone()
    return float(row[0])


@dataclass
class Claude:
    """Thin wrapper so tests can pass a fake `client` and an in-memory cache."""

    client: object
    con: object | None = None  # DuckDB connection with an llm_cache table, or None
    daily_cap_usd: float | None = None  # hosted demo: stop calling once today's budget is gone
    fn: str = ""  # which of the three calls is running, for the spend ledger

    def _cached(self, fn: str, payload: dict, run):
        self.fn = fn
        version = PROMPT_VERSIONS.get(fn, PROMPT_VERSION)
        key = hashlib.sha256(json.dumps([MODEL, version, fn, payload], sort_keys=True).encode()).hexdigest()
        if self.con is not None:
            row = self.con.execute("SELECT output FROM llm_cache WHERE key = ?", [key]).fetchone()
            if row:
                return json.loads(row[0]), True
        out = run()
        if self.con is not None:
            self.con.execute(
                "INSERT INTO llm_cache VALUES (?, ?, ?, ?, ?, now())",
                [key, MODEL, version, json.dumps(payload, sort_keys=True), json.dumps(out)],
            )
        return out, False

    def _json_call(self, prompt: str, schema: dict, tools: list | None = None) -> dict:
        if self.daily_cap_usd is not None:
            spent = spend_today(self.con)
            if spent >= self.daily_cap_usd:
                raise SpendCapReached(f"daily model budget spent (${spent:.2f} of ${self.daily_cap_usd:.2f})")
        resp = self.client.beta.messages.create(
            model=MODEL,
            max_tokens=4000,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            tools=tools or [],
            messages=[{"role": "user", "content": prompt}],
        )
        self._record(resp)
        if resp.stop_reason == "refusal":
            raise RuntimeError("model declined the request")
        text = next(b.text for b in resp.content if b.type == "text")
        return json.loads(text)

    def _record(self, resp) -> None:
        """Every call that reached the API goes in the ledger, refusal or not: a refusal
        that was not billed still costs nothing, and the zero is the honest entry."""
        usage = getattr(resp, "usage", None)
        if self.con is None or usage is None:
            return
        model = getattr(resp, "model", MODEL)
        self.con.execute(
            "INSERT INTO llm_spend VALUES (now(), ?, ?, ?, ?, ?, ?, ?)",
            [model, self.fn, usage.input_tokens or 0, usage.output_tokens or 0,
             getattr(usage, "cache_read_input_tokens", 0) or 0,
             getattr(usage, "cache_creation_input_tokens", 0) or 0,
             cost_usd(model, usage)],
        )

    def find_hospital_website(self, h: Hospital) -> tuple[str | None, str]:
        payload = {"ccn": h.ccn, "name": h.name, "address": h.address, "city": h.city, "state": h.state, "zip": h.zip}
        prompt = (
            "Find the official website of this hospital (the hospital's or its health system's own "
            "domain, not a directory, review site or news article). Use web search. Answer with the "
            "bare domain, and with the URL of the hospital's own page on it when the search found "
            "one: a health system often keeps its hospitals on a subdomain of its domain, and the "
            "page's host matters.\n\n" + json.dumps(payload, indent=1)
        )
        tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}]
        out, cached = self._cached("website", payload, lambda: self._json_call(prompt, WEBSITE_SCHEMA, tools))
        why = f"{out['confidence']} confidence, {out['why']}" + (" [cached]" if cached else "")
        domain = (out.get("domain") or "").lower().removeprefix("https://").removeprefix("http://").strip("/ ").split("/")[0]
        # The page's host wins when it is a subdomain of the domain: that is where the
        # hospital lives, and hosts_to_try in discovery falls back to the apex itself.
        page_host = urlsplit(out.get("page_url") or "").netloc.lower()
        if domain and page_host and page_host != domain and page_host.endswith("." + domain.removeprefix("www.")):
            return page_host, why
        return (domain or None), why

    def confirm_service(self, query: str, resolution, catalogue: list | None = None) -> tuple[object | None, str]:
        """The resolver could not settle the query. Ask Claude to pick among its candidates
        (never outside them) or to phrase the clarifying question. Returns (service, why or
        question).

        `catalogue` is passed when the resolver found nothing that shares a word with the
        query — lay phrasing like "stomach camera". The whole list then becomes the
        candidates, so the rule is unchanged: Claude chooses an entry that exists, or asks.
        """
        cands = list(resolution.candidates) or list(catalogue or [])
        if not cands:
            return None, resolution.reason
        narrowed = bool(resolution.candidates)
        payload = {
            "query": query,
            "resolver": {"verdict": resolution.verdict, "reason": resolution.reason, "narrowed": narrowed},
            "candidates": [{"id": c.id, "name": c.name, "codes": c.code_list, "qualifiers": c.qualifiers, "aliases": list(c.aliases)} for c in cands],
        }
        opening = (
            "A deterministic matcher narrowed it to these entries of CMS's list of 70 shoppable "
            "services but could not settle it."
            if narrowed else
            "A deterministic matcher found no entry sharing a word with it, so the whole list of "
            "CMS's 70 shoppable services follows. The user may have used everyday words for a "
            "procedure, or may have asked for something the list does not cover at all."
        )
        prompt = (
            "A user typed a procedure name. " + opening + " If exactly one entry is what "
            "the user plainly means, return its id. If the user asked for a variant the list does not "
            "have, or the words fit several entries, or you are not sure, return null and a "
            "one-sentence question to ask the user. Never pick an entry that is not in the "
            "candidates, and never guess.\n\n" + json.dumps(payload, indent=1)
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
