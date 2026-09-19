import json
from types import SimpleNamespace

from hpa import store
from hpa.discovery import HptEntry
from hpa.hospitals import Hospital
from hpa.llm import Claude


def hospital():
    return Hospital("450289", "HARRIS HEALTH", "1504 TAUB LOOP", "HOUSTON", "TX", "77030",
                    "Acute Care Hospitals", "Government", 0.0, 0.0, "address", "Exact", None)


class FakeClient:
    """Answers every call with the given JSON and records what it was asked."""

    def __init__(self, answer):
        self.calls = []
        create = lambda **kw: (self.calls.append(kw), SimpleNamespace(
            stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(answer))]))[1]
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=create))


def test_pick_entry_returns_the_chosen_candidate_and_caches():
    con = store.connect(":memory:")
    fake = FakeClient({"index": 0, "why": "Taub Loop is Ben Taub"})
    claude = Claude(fake, con)
    cands = [HptEntry("Harris Health Ben Taub Hospital", None, "https://x/a.zip"),
             HptEntry("Harris Health Lyndon B Johnson Hospital", None, "https://x/b.zip")]
    entry, why = claude.pick_entry(hospital(), cands)
    assert entry is cands[0] and why == "Taub Loop is Ben Taub"
    assert len(fake.calls) == 1
    assert fake.calls[0]["model"] == "claude-opus-5"
    assert fake.calls[0]["output_config"]["format"]["type"] == "json_schema"

    entry2, why2 = claude.pick_entry(hospital(), cands)  # second call is served from the cache
    assert entry2 is cands[0] and why2.endswith("[cached]")
    assert len(fake.calls) == 1


def test_pick_entry_null_means_no_choice():
    claude = Claude(FakeClient({"index": None, "why": "neither matches"}))
    entry, why = claude.pick_entry(hospital(), [HptEntry("A", None, None)])
    assert entry is None and why == "neither matches"


def test_find_website_uses_web_search_and_normalises_domain():
    fake = FakeClient({"domain": "https://www.harrishealth.org/", "confidence": "high", "why": "official site", "sources": ["https://www.harrishealth.org"]})
    domain, why = Claude(fake).find_hospital_website(hospital())
    assert domain == "www.harrishealth.org"
    assert why.startswith("high confidence")
    tools = fake.calls[0]["tools"]
    assert tools[0]["type"] == "web_search_20260209" and tools[0]["name"] == "web_search"
