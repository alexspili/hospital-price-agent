from pathlib import Path

import httpx
import pytest

from hpa.discovery import (
    HptEntry,
    domain_candidates,
    fetch_hpt,
    locate_price_file,
    match_entry,
    parse_hpt,
    probe_mrf,
)
from hpa.hospitals import Hospital

HPT = Path(__file__).parent / "fixtures" / "hpt"


def hospital(name, ccn="000000", address="1 MAIN ST", city="HOUSTON", zip="77030"):
    return Hospital(ccn, name, address, city, "TX", zip, "Acute Care Hospitals", "Proprietary", 0.0, 0.0, "address", "Exact", None)


# --- parsing ---------------------------------------------------------------------------

@pytest.mark.parametrize("fixture, count", [("hca", 36), ("methodist", 20), ("memorialhermann", 19),
                                            ("commonspirit", 72), ("harrishealth", 2), ("texaschildrens", 4),
                                            ("ascension", 13)])
def test_parse_counts_match_the_real_files(fixture, count):
    entries = parse_hpt((HPT / f"{fixture}.txt").read_text())
    assert len(entries) == count
    assert all(e.mrf_url for e in entries)


def test_parse_skips_banner_text_and_keeps_fields():
    entries = parse_hpt((HPT / "methodist.txt").read_text())
    assert entries[0].location_name == "Houston Methodist Hospital"
    assert entries[0].mrf_url.endswith("74110155_the-methodist-hospital_standardcharges.ashx")
    assert entries[0].source_page_url.startswith("https://www.houstonmethodist.org/")
    assert entries[0].contact_email == "lschillaci@houstonmethodist.org"


def test_parse_tolerates_missing_space_after_key_and_crlf():
    text = "location-name:Arizona General Hospital Mesa\r\nmrf-url: https://x/a.json  \r\n"
    assert parse_hpt(text) == [HptEntry("Arizona General Hospital Mesa", None, "https://x/a.json")]


def test_parse_keeps_sas_token_urls_intact():
    hca = parse_hpt((HPT / "hca.txt").read_text())
    kingwood = next(e for e in hca if "KINGWOOD" in e.location_name)
    assert "?" in kingwood.mrf_url and kingwood.mrf_url.endswith(kingwood.mrf_url.split("&")[-1])


# --- matching --------------------------------------------------------------------------

def test_hca_kingwood_matches_among_freestanding_ers():
    m = match_entry(hospital("HCA HOUSTON HEALTHCARE KINGWOOD"), parse_hpt((HPT / "hca.txt").read_text()))
    assert m.verdict == "matched"
    assert m.entry.location_name == "HCA HOUSTON KINGWOOD"


def test_st_lukes_woodlands_not_confused_with_lakeside():
    entries = parse_hpt((HPT / "commonspirit.txt").read_text())
    m = match_entry(hospital("ST LUKE'S THE WOODLANDS HOSPITAL"), entries)
    assert m.verdict == "matched"
    assert m.entry.location_name == "St. Luke's Health - The Woodlands Hospital"
    m = match_entry(hospital("CHI ST LUKES LAKESIDE HOSPITAL"), entries)
    assert m.verdict == "matched"
    assert m.entry.location_name == "St. Luke's Health - Lakeside Hospital"


def test_base_name_beats_its_qualified_variant_but_keeps_it_as_candidate():
    # "Baylor St Luke's Medical Center" vs "... (McNair)": the CMS name has no qualifier,
    # so the base entry wins (97 vs 79); the variant stays visible in the candidates.
    entries = parse_hpt((HPT / "commonspirit.txt").read_text())
    m = match_entry(hospital("Baylor St Lukes Medical Center"), entries)
    assert m.verdict == "matched"
    assert m.entry.location_name == "Baylor St Luke's Medical Center"
    assert "Baylor St. Luke's Medical Center (McNair)" in {e.location_name for e, _ in m.candidates}


def test_system_level_cms_name_is_ambiguous_for_tie_break():
    # CMS lists Harris Health's CCN under the system name; the index has two hospitals.
    m = match_entry(hospital("HARRIS HEALTH", address="1504 TAUB LOOP"), parse_hpt((HPT / "harrishealth.txt").read_text()))
    assert m.verdict == "ambiguous"
    assert len(m.candidates) == 2


def test_texas_childrens_main_campus_beats_its_satellites():
    m = match_entry(hospital("TEXAS CHILDRENS HOSPITAL"), parse_hpt((HPT / "texaschildrens.txt").read_text()))
    assert m.verdict == "matched"
    assert m.entry.location_name == "Texas Children's Hospital"


def test_campus_missing_from_its_systems_index_is_none_not_a_near_miss():
    # Memorial Hermann's index has no Kingwood surgical hospital. Sugar Land shares only the
    # system name, so it must not be offered as a candidate.
    entries = parse_hpt((HPT / "memorialhermann.txt").read_text())
    m = match_entry(hospital("MEMORIAL HERMANN SURGICAL HOSPITAL KINGWOOD"), entries)
    assert m.verdict == "none"
    # ...while a campus that is listed still matches cleanly.
    m = match_entry(hospital("MEMORIAL HERMANN NORTHEAST HOSPITAL"), entries)
    assert m.verdict == "matched" and m.entry.location_name == "Memorial Hermann Northeast Hospital"


def test_unrelated_index_matches_nothing():
    m = match_entry(hospital("KINGWOOD PINES HOSPITAL"), parse_hpt((HPT / "harrishealth.txt").read_text()))
    assert m.verdict == "none"


# --- domains ---------------------------------------------------------------------------

def test_domain_candidates_seed_first_then_guesses():
    c = domain_candidates(hospital("HCA HOUSTON HEALTHCARE KINGWOOD"))
    assert c[0] == "hcahoustonhealthcare.com"
    # A system whose index lives on a subdomain the name would never suggest.
    assert domain_candidates(hospital("ASCENSION SETON NORTHWEST"))[0] == "healthcare.ascension.org"
    assert domain_candidates(hospital("DELL SETON  MED CENTER AT THE UNIVERSITY OF TX"))[0] == "healthcare.ascension.org"
    assert domain_candidates(hospital("BAYLOR SCOTT & WHITE MEDICAL CENTER - FRISCO"))[0] == "bswhealth.com"
    assert domain_candidates(hospital("BAYLOR ST LUKES MEDICAL CENTER"))[0] == "commonspirit.org"  # not Baylor Scott & White
    assert "hcahoustonhealthcarekingwood.com" in c
    c = domain_candidates(hospital("KINGWOOD PINES HOSPITAL"))
    assert c[:2] == ["kingwoodpines.com", "kingwoodpines.org"]


# --- http ------------------------------------------------------------------------------

def transport(routes):
    """routes: {host_path: (status, content_type, body) | Exception}"""
    def handler(request):
        key = request.url.host + request.url.path
        r = routes.get(key, (404, "text/html", "<html>nope</html>"))
        if isinstance(r, Exception):
            raise r
        status, ct, body = r
        return httpx.Response(status, headers={"content-type": ct}, text=body)
    return httpx.MockTransport(handler)


HPT_OK = "location-name: X Hospital\nmrf-url: https://files.x.org/x.json\n"


def test_fetch_falls_back_to_www():
    client = httpx.Client(transport=transport({"www.x.org/cms-hpt.txt": (200, "text/plain", HPT_OK)}))
    r = fetch_hpt(client, "x.org")
    assert r.status == "ok" and r.url == "https://www.x.org/cms-hpt.txt"


def test_fetch_html_with_200_is_not_an_index():
    client = httpx.Client(transport=transport({"x.org/cms-hpt.txt": (200, "text/html", "<html>Not found</html>")}))
    r = fetch_hpt(client, "x.org")
    assert r.status in ("html", "404") and r.text is None
    assert "not an index file" in r.reason


def test_fetch_timeout_is_a_reason_not_an_exception():
    client = httpx.Client(transport=transport({"x.org/cms-hpt.txt": httpx.ReadTimeout("slow")}))
    r = fetch_hpt(client, "x.org")
    assert r.status != "ok" and "timeout" in r.reason


def test_probe_head_then_range_get():
    calls = []

    def handler(request):
        calls.append(request.method)
        if request.method == "HEAD":
            return httpx.Response(405)
        assert request.headers["range"] == "bytes=0-63"
        return httpx.Response(206, headers={"content-type": "application/json", "content-range": "bytes 0-63/2100000000",
                                            "last-modified": "Mon, 01 Sep 2026 00:00:00 GMT"}, content=b"{")

    p = probe_mrf(httpx.Client(transport=httpx.MockTransport(handler)), "https://files.x.org/x.json")
    assert calls == ["HEAD", "GET"]
    assert p.ok and p.shape == "json" and p.size_bytes == 2_100_000_000
    assert p.last_modified.startswith("Mon, 01 Sep 2026")


def test_probe_html_is_failure():
    client = httpx.Client(transport=transport({"files.x.org/x.json": (200, "text/html", "<html>login</html>")}))
    p = probe_mrf(client, "https://files.x.org/x.json")
    assert not p.ok and "HTML" in p.reason


# --- orchestration ---------------------------------------------------------------------

def test_locate_end_to_end_with_tie_break():
    routes = {
        "www.harrishealth.org/cms-hpt.txt": (200, "text/plain", (HPT / "harrishealth.txt").read_text()),
        "www.harrishealth.org/SiteCollectionDocuments/financials/charge description master/2026/741536936_Harris-Health-Ben-Taub-Hospital_StandardCharges.zip":
            (200, "application/zip", ""),
    }
    client = httpx.Client(transport=transport(routes))
    lines = []
    picked = []

    def tie_breaker(h, cands):
        picked.append([c.location_name for c in cands])
        return next(c for c in cands if "Ben Taub" in c.location_name), "address is Taub Loop"

    d = locate_price_file(client, hospital("HARRIS HEALTH", address="1504 TAUB LOOP"), lines.append, tie_breaker=tie_breaker)
    assert d.ok and d.method == "cms-hpt+tie-break"
    assert d.entry.location_name == "Harris Health Ben Taub Hospital"
    assert d.probe.shape == "zip"
    assert picked == [["Harris Health Ben Taub Hospital", "Harris Health Lyndon B Johnson Hospital"]]
    assert lines[0].startswith("Harris Health: cms-hpt.txt found at https://www.harrishealth.org/cms-hpt.txt")
    assert any("tie-break picked" in line for line in lines)


def test_locate_uses_web_search_when_guesses_fail():
    routes = {"realsite.org/cms-hpt.txt": (200, "text/plain", "location-name: Kingwood Pines Hospital\nmrf-url: https://realsite.org/f.csv\n"),
              "realsite.org/f.csv": (200, "text/csv", "")}
    client = httpx.Client(transport=transport(routes))
    d = locate_price_file(client, hospital("KINGWOOD PINES HOSPITAL"), web_search=lambda h: ("realsite.org", "high confidence"))
    assert d.ok and d.method == "web-search+cms-hpt" and d.probe.shape == "csv"


def test_locate_reports_failure_with_every_reason():
    client = httpx.Client(transport=transport({}))
    d = locate_price_file(client, hospital("KINGWOOD PINES HOSPITAL"))
    assert not d.ok and d.method == "failed"
    assert "kingwoodpines.com: 404" in d.reason and "www.kingwoodpines.org: 404" in d.reason
    assert d.steps[-1] == "no machine-readable index located — skipped"


# --- d/b/a names, probe sniffing, site pages -------------------------------------------

def test_legal_dba_name_matches_on_the_trade_name():
    entries = parse_hpt((HPT / "elitekingwood.txt").read_text())
    assert entries[0].location_name.startswith("23330 Emergency Center, LLC d/b/a")
    m = match_entry(hospital("ELITE HOSPITAL KINGWOOD"), entries)
    assert m.verdict == "matched" and m.score == 100


def test_probe_sniffs_json_behind_an_ashx_download():
    def handler(request):
        headers = {"content-type": "application/octet-stream", "content-length": "72060229",
                   "content-disposition": 'attachment; filename="74110155_x_standardcharges.json"'}
        if request.method == "HEAD":
            return httpx.Response(200, headers=headers)
        return httpx.Response(206, headers={**headers, "content-range": "bytes 0-63/72060229"}, content=b"\xef\xbb\xbf{\"hospital_name\": \"x\"}")

    p = probe_mrf(httpx.Client(transport=httpx.MockTransport(handler)), "https://x.org/-/media/file.ashx")
    assert p.ok and p.shape == "json" and p.size_bytes == 72060229


def test_probe_gets_size_from_range_when_head_has_none():
    def handler(request):
        if request.method == "HEAD":
            return httpx.Response(200, headers={"content-type": "application/json"})
        return httpx.Response(206, headers={"content-type": "application/json", "content-range": "bytes 0-63/256037144"}, content=b"{" * 64)

    p = probe_mrf(httpx.Client(transport=httpx.MockTransport(handler)), "https://x.org/f.json")
    assert p.ok and p.size_bytes == 256037144


TOWNSEN_HOME = '<html><a href="/about">About</a><a href="/pricing-transparency">Pricing Transparency</a></html>'
TOWNSEN_PAGE = ('<html><a href="/images/Files/2025-08-19-Townsen-Memorial-Hospital-Shoppable-Services.csv">shoppable</a>'
                '<a href="/images/Files/364867804_TownsenMemorialHospital_StandardCharges.csv">MRF</a></html>')


def test_site_page_layer_finds_the_standard_charges_link():
    routes = {
        "www.townsenmemorial.com/cms-hpt.txt": (404, "text/html", "no"),
        "townsenmemorial.com/cms-hpt.txt": (404, "text/html", "no"),
        "townsenmemorial.com/": (200, "text/html", TOWNSEN_HOME),
        "townsenmemorial.com/pricing-transparency": (200, "text/html", TOWNSEN_PAGE),
        "townsenmemorial.com/images/Files/364867804_TownsenMemorialHospital_StandardCharges.csv": (200, "text/csv", "a,b\n"),
    }
    lines = []
    d = locate_price_file(httpx.Client(transport=transport(routes)), hospital("TOWNSEN MEMORIAL HOSPITAL"), lines.append)
    assert d.ok and d.method == "site-page" and d.probe.shape == "csv"
    assert d.entry.mrf_url.endswith("364867804_TownsenMemorialHospital_StandardCharges.csv")
    assert d.index_url == "https://townsenmemorial.com/pricing-transparency"
    assert any("standard-charges link" in line for line in lines)


# --- what the Austin search found missing (2026-09-22) ------------------------------------

def test_ascension_campuses_match_their_entries():
    entries = parse_hpt((HPT / "ascension.txt").read_text())
    m = match_entry(hospital("ASCENSION SETON NORTHWEST"), entries)
    assert m.verdict == "matched" and m.entry.location_name.startswith("Ascension Seton Northwest")
    m = match_entry(hospital("ASCENSION SETON MEDICAL CENTER AUSTIN"), entries)
    assert m.verdict == "matched" and "Medical Center Austin" in m.entry.location_name
    # CMS abbreviates; the index spells out. Read as the same name.
    m = match_entry(hospital("DELL SETON  MED CENTER AT THE UNIVERSITY OF TX"), entries)
    assert m.verdict == "matched" and m.entry.location_name.startswith("Dell Seton Medical Center")
    # Sister campuses one word apart are each their own exact match, never a tie.
    m = match_entry(hospital("ASCENSION SETON SOUTHWEST"), entries)
    assert m.verdict == "matched" and m.entry.location_name.startswith("Ascension Seton Southwest")


def test_a_pricing_link_to_a_sibling_host_is_followed_to_the_index():
    """The corporate site has no index but links to healthcare.<domain>/price-transparency,
    which is where the index is. No seed, no web search."""
    hpt = "location-name: Newco Hospital North\nmrf-url: https://healthcare.newco.org/files/1_newco_standardcharges.csv\n"
    routes = {
        "newcohospitalnorth.com/cms-hpt.txt": httpx.ConnectError("no such host"),
        "www.newcohospitalnorth.com/cms-hpt.txt": httpx.ConnectError("no such host"),
        "newcohospitalnorth.org/cms-hpt.txt": httpx.ConnectError("no such host"),
        "www.newcohospitalnorth.org/cms-hpt.txt": httpx.ConnectError("no such host"),
        "newco.org/cms-hpt.txt": (404, "text/html", "<html>nope</html>"),
        "www.newco.org/cms-hpt.txt": (404, "text/html", "<html>nope</html>"),
        "newco.org/": (200, "text/html", '<html><a href="https://healthcare.newco.org/price-transparency">Price transparency</a></html>'),
        "healthcare.newco.org/cms-hpt.txt": (200, "text/plain", hpt),
        "healthcare.newco.org/files/1_newco_standardcharges.csv": (200, "text/csv", "description,code|1\nx,1\n"),
    }
    client = httpx.Client(transport=transport(routes))
    # newco.org is reached through the web search here, standing in for a corporate domain
    # a name guess would not produce; the point is what happens after it answers 404.
    d = locate_price_file(client, hospital("NEWCO HOSPITAL NORTH"), web_search=lambda h: ("newco.org", "high"))
    assert d.ok, d.reason
    assert d.method == "web-search+site-link+cms-hpt"
    assert d.entry.location_name == "Newco Hospital North"
    assert any("pricing link points at healthcare.newco.org" in s for s in d.steps)


# --- an NPI in the filename settles a tie, with guardrails ---------------------------------

from hpa.discovery import npi_in, npi_tie_break, npi_valid, same_place  # noqa: E402


def test_npi_check_digit():
    assert npi_valid("1234567893")  # the standard example
    assert npi_valid("1124137054")  # Ascension Seton Northwest
    assert not npi_valid("1234567890") and not npi_valid("123456789") and not npi_valid("abcdefghij")


def test_npi_in_a_filename_is_the_number_after_the_ein():
    assert npi_in("https://x.org/tx-csv/741109643-1124137054_ascension-seton_standardcharges.csv") == "1124137054"
    assert npi_in("https://x.org/741536936_Harris-Health-Ben-Taub-Hospital_StandardCharges.zip") is None  # EIN only
    assert npi_in("https://x.org/1234567890_x_standardcharges.csv") is None  # ten digits, wrong check digit
    assert npi_in(None) is None


def registry(answers: dict):
    """A fake NPI registry: {npi: (address_1, city, zip)}; anything else is not found."""
    def handler(request):
        if request.url.host != "npiregistry.cms.hhs.gov":
            return httpx.Response(404)
        npi = request.url.params.get("number")
        if npi not in answers:
            return httpx.Response(200, json={"result_count": 0, "results": []})
        a, city, z = answers[npi]
        return httpx.Response(200, json={"result_count": 1, "results": [{
            "basic": {"organization_name": "ASCENSION SETON"},
            "addresses": [{"address_purpose": "MAILING", "address_1": "1345 PHILOMENA ST.", "city": "AUSTIN", "state": "TX", "postal_code": "787233185"},
                          {"address_purpose": "LOCATION", "address_1": a, "city": city, "state": "TX", "postal_code": z}]}]})
    return httpx.Client(transport=httpx.MockTransport(handler))


NW = HptEntry("Ascension Seton Northwest (Ascension Seton)", None, "https://x.org/741109643-1124137054_ascension-seton_standardcharges.csv")
SW = HptEntry("Ascension Seton Southwest (Ascension Seton)", None, "https://x.org/741109643-1750499273_ascension-seton_standardcharges.csv")
REG = {"1124137054": ("11113 RESEARCH", "AUSTIN", "787595236"), "1750499273": ("7900 FM 1826", "AUSTIN", "787375000")}


def test_npi_settles_a_tie_when_exactly_one_registered_address_is_the_hospitals():
    h = hospital("ASCENSION SETON", address="11113 RESEARCH BOULEVARD", city="AUSTIN", zip="78759")
    entry, why = npi_tie_break(registry(REG), h, [NW, SW])
    assert entry is NW and "11113 RESEARCH" in why


def test_npi_settles_nothing_when_it_cannot():
    h = hospital("ASCENSION SETON", address="11113 RESEARCH BOULEVARD", city="AUSTIN", zip="78759")
    # The registry knows no such number, or is down: no answer either way, never a guess.
    assert npi_tie_break(registry({}), h, [NW, SW]) == (None, "no candidate's NPI is registered at the hospital's address")
    down = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    assert npi_tie_break(down, h, [NW, SW])[1] == "the NPI registry did not answer"
    # Two campuses sharing one file share one NPI: the same address for both settles nothing.
    shared = HptEntry("Dell Children's North Campus (Ascension Seton)", None, NW.mrf_url)
    assert npi_tie_break(registry(REG), h, [NW, shared])[0] is None
    # No NPI in any filename: nothing is looked up.
    ein_only = HptEntry("Harris Health Ben Taub Hospital", None, "https://x.org/741536936_Harris-Health-Ben-Taub-Hospital_StandardCharges.zip")
    assert npi_tie_break(registry(REG), h, [ein_only]) == (None, "no NPI in the filenames")
    # A different street number at the same city is not the same place.
    elsewhere = hospital("ASCENSION SETON", address="1201 W 38TH ST", city="AUSTIN", zip="78705")
    assert npi_tie_break(registry(REG), elsewhere, [NW, SW])[0] is None
    assert same_place(elsewhere, {"address": "1201 W 38TH STREET", "city": "Austin", "zip": "78705"})


def test_a_tie_on_the_index_goes_to_the_npi_before_the_model(monkeypatch):
    """A system-level CMS name that fits two campuses, with no model tie-breaker at all."""
    index = "\n".join(f"location-name: {e.location_name}\nmrf-url: {e.mrf_url}\n" for e in (NW, SW))
    routes = {"healthcare.ascension.org/cms-hpt.txt": (200, "text/plain", index),
              "x.org/741109643-1124137054_ascension-seton_standardcharges.csv": (200, "text/csv", "description,code|1\nx,1\n")}
    base = transport(routes)
    reg = registry(REG)

    def handler(request):
        return reg._transport.handler(request) if request.url.host == "npiregistry.cms.hhs.gov" else base.handler(request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    h = hospital("ASCENSION SETON", address="11113 RESEARCH BOULEVARD", city="AUSTIN", zip="78759")
    d = locate_price_file(client, h)
    assert d.ok and d.method == "cms-hpt+npi" and d.entry is not None
    assert d.entry.location_name.startswith("Ascension Seton Northwest")
    assert any(s.startswith("NPI settled it") for s in d.steps)
