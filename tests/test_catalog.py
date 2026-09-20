import pytest

from hpa import catalog
from hpa.catalog import AMBIGUOUS, NEEDS_CLARIFICATION, NOT_IN_CATALOG, SELECTED, UNSUPPORTED_VARIANT


def test_all_seventy_cms_services_present():
    services = catalog.load()
    assert len(services) == 70
    assert len({s.id for s in services}) == 70
    assert all(s.codes for s in services)


def test_reviewed_entries_carry_evidence():
    # `reviewed` is never a bare flag: it names who, when, and which hospital lines were checked.
    reviewed = [s for s in catalog.load() if s.reviewed]
    assert len(reviewed) == 5
    for s in reviewed:
        assert s.reviewed["reviewer"] and s.reviewed["date"] and s.reviewed["alias_confirmed"] is True
        assert all(h["ref"] for h in s.reviewed["hospitals"] if h["billing_class"])


def test_ids_are_built_from_codes():
    ids = {s.id for s in catalog.load()}
    assert {"cpt-73721", "drg-470", "cpt-81000-81001", "cpt-84153-84154"} <= ids


@pytest.mark.parametrize(
    "query, code",
    [
        ("knee mri", "73721"),
        ("45378", "45378"),
        ("screening mammogram", "77067"),
        ("colonoscopy with biopsy", "45380"),
        ("colonoscopy without biopsy", "45378"),  # not the biopsy entry
        ("colonoscopy", "45378"),  # exact alias beats the other three
        ("head CT without contrast", "70450"),
        ("lumbar x-ray", "72110"),
    ],
)
def test_selected(query, code):
    r = catalog.resolve(query)
    assert r.verdict == SELECTED
    assert r.service.codes[0][1] == code


def test_wrong_variant_is_unsupported_not_a_different_organ():
    # The catalog only has the leg-joint MRI without contrast. Asking for contrast must
    # not return the brain MRI just because it mentions contrast.
    r = catalog.resolve("knee mri with contrast")
    assert r.verdict == UNSUPPORTED_VARIANT
    assert r.service is None
    assert r.candidates[0].codes[0][1] == "73721"
    assert "with contrast is not on it" in r.reason


@pytest.mark.parametrize(
    "query, phrase",
    [
        ("knee mri with biopsy", "doesn't say whether MRI scan of leg joint (CPT 73721) is with biopsy"),
        ("colonoscopy with contrast", "doesn't say whether Diagnostic examination of large bowel"),
        ("knee mri with contrast without contrast", "both with and without contrast"),
    ],
)
def test_undeclared_or_contradictory_qualifiers_ask_instead_of_guessing(query, phrase):
    r = catalog.resolve(query)
    assert r.verdict == NEEDS_CLARIFICATION
    assert r.service is None
    assert phrase in r.reason


def test_ambiguous_lists_the_ties():
    r = catalog.resolve("mri")
    assert r.verdict == AMBIGUOUS
    assert r.service is None
    assert {s.codes[0][1] for s in r.candidates} == {"70553", "72148", "73721"}


def test_missing_anatomy_is_not_in_catalog():
    # "chest" matches nothing; the lumbar x-ray must not be selected on "x-ray" alone.
    r = catalog.resolve("chest x-ray")
    assert r.verdict == NOT_IN_CATALOG
    assert r.service is None
    assert "chest" in r.reason
    assert r.candidates[0].codes[0][1] == "72110"


def test_hyphen_and_no_hyphen_spellings_match():
    assert catalog.resolve("lumbar xray").service.codes[0][1] == "72110"


def test_ranges_expand_to_every_code():
    psa = next(s for s in catalog.load() if s.name.startswith("PSA"))
    assert psa.codes == (("CPT", "84153"), ("CPT", "84154"))


def test_no_match_returns_empty():
    r = catalog.resolve("xyzzy")
    assert r.verdict == NOT_IN_CATALOG
    assert catalog.search("xyzzy") == []


# --- misspellings: a string-distance problem, fixed without a model ----------------------

def test_a_misspelling_resolves_and_says_what_it_read():
    r = catalog.resolve("colonscopy")
    assert r.verdict == catalog.SELECTED and r.service.id == "cpt-45378"
    assert r.corrections == (("colonscopy", "colonoscopy"),)


def test_a_misspelling_can_land_on_several_entries_and_still_asks():
    r = catalog.resolve("mamogram")
    assert r.verdict == catalog.AMBIGUOUS
    assert r.corrections == (("mamogram", "mammogram"),)
    assert len(r.candidates) >= 2  # it asks which, rather than picking one


def test_a_word_nobody_uses_stays_unmatched():
    r = catalog.resolve("xyzzy")
    assert r.verdict == catalog.NOT_IN_CATALOG and not r.corrections


def test_short_words_are_never_corrected():
    # "cbc" -> "cmp" or "ekg" -> "eeg" would be a different test entirely; three letters
    # carry too little signal, so they are left alone.
    assert catalog.correct_tokens({"cbd", "eeg"}, catalog.load()) == {}


def test_a_correct_query_is_never_rewritten():
    for query in ("knee mri", "colonoscopy", "cbc", "screening mammogram", "45378"):
        assert catalog.resolve(query).corrections == ()
