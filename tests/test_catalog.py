from hpa import catalog


def test_all_seventy_cms_services_present():
    services = catalog.load()
    assert len(services) == 70
    assert len({s.id for s in services}) == 70
    assert all(s.codes for s in services)


def test_nothing_is_verified_yet():
    # Flip entries to verified only after checking them against real hospital files.
    assert sum(s.verified for s in catalog.load()) == 0


def test_search_by_alias():
    assert catalog.search("knee mri")[0].codes == (("CPT", "73721"),)


def test_search_by_code():
    assert catalog.search("45378")[0].name.startswith("Diagnostic examination of large bowel")


def test_search_ranks_better_matches_first():
    results = catalog.search("colonoscopy with biopsy")
    assert results[0].codes == (("CPT", "45380"),)
    assert len(results) >= 3  # the other colonoscopy entries follow


def test_ranges_expand_to_every_code():
    psa = next(s for s in catalog.load() if s.name.startswith("PSA"))
    assert psa.codes == (("CPT", "84153"), ("CPT", "84154"))


def test_no_match_returns_empty():
    assert catalog.search("xyzzy") == []
