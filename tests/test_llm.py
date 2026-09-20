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


def test_confirm_service_picks_only_among_candidates():
    from hpa import catalog
    res = catalog.resolve("mri")  # ambiguous: brain, leg joint, lumbar
    fake = FakeClient({"id": "cpt-73721", "question": None, "why": "user context says knee"})
    svc, why = Claude(fake).confirm_service("mri", res)
    assert svc.id == "cpt-73721" and why == "user context says knee"
    fake = FakeClient({"id": "cpt-99999", "question": "Which MRI: brain, knee or lower back?", "why": "several fit"})
    svc, why = Claude(fake).confirm_service("mri", res)
    assert svc is None and why.startswith("Which MRI")


# --- lay phrasing: the whole list becomes the candidate set ------------------------------

def test_with_no_candidates_the_whole_catalog_is_offered():
    from hpa import catalog

    services = catalog.load()
    # "stomach" or "knee" would narrow it; these words appear nowhere in the catalog.
    r = catalog.resolve("camera down my throat", services)
    assert not r.candidates

    fake = FakeClient({"id": "cpt-43235", "question": None, "why": "an upper GI endoscopy goes down the throat"})
    chosen, why = Claude(fake).confirm_service("camera down my throat", r, catalogue=services)
    prompt = fake.calls[0]["messages"][0]["content"]
    assert "the whole list of CMS's 70 shoppable services follows" in prompt
    assert prompt.count('"id"') >= 70  # every entry travelled as a candidate
    assert chosen is not None and chosen.id == "cpt-43235"


def test_it_may_still_only_pick_an_entry_that_exists():
    from hpa import catalog

    services = catalog.load()
    r = catalog.resolve("camera down my throat", services)
    fake = FakeClient({"id": "cpt-99999", "question": None, "why": "invented"})
    chosen, why = Claude(fake).confirm_service("camera down my throat", r, catalogue=services)
    assert chosen is None  # an id outside the candidates is not a choice


def test_an_unmatched_query_asks_nothing_when_no_catalogue_is_offered():
    from hpa import catalog

    fake = FakeClient({"id": None, "question": "which service?", "why": ""})
    chosen, why = Claude(fake).confirm_service("xyzzy", catalog.resolve("xyzzy"))
    assert chosen is None and fake.calls == []  # the model was never asked
