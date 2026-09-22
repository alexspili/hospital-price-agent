"""Find a hospital's price transparency file on the live web.

Deterministic layers, in order: candidate domains (a seed of Texas health systems
plus guesses from the hospital's name) → `cms-hpt.txt` on each → match the hospital to one
of the index's entries → probe the file URL without downloading it. Two hooks take a
fuzzy step to Claude when the deterministic layers can't decide: `web_search` for the
domain, `tie_breaker` for the entry.
"""

import re
import time
from urllib.parse import urljoin, urlsplit
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx
from rapidfuzz import fuzz

from hpa.hospitals import Hospital

USER_AGENT = "Mozilla/5.0 (compatible; hospital-price-agent/0.1; +https://github.com/alexspili/hospital-price-agent)"
INDEX_TIMEOUT = 15.0
PROBE_TIMEOUT = 20.0

# Seed: health systems whose index files were checked by hand for this project (each host
# answered /cms-hpt.txt with entries on 2026-09-22). The name pattern is matched against
# the CMS facility name. Everything else is guessed from the name and, failing that,
# looked up with a web search. A system's index often lives on a subdomain the name
# would never suggest (healthcare.ascension.org), which is what the seed is for.
SYSTEM_DOMAINS: list[tuple[str, list[str]]] = [
    (r"\bHCA HOUSTON\b", ["hcahoustonhealthcare.com"]),
    (r"\bHOUSTON METHODIST\b", ["houstonmethodist.org"]),
    (r"\bMEMORIAL HERMANN\b", ["memorialhermann.org"]),
    (r"\bST\.? ?LUKE|\bBAYLOR ST\b|\bCHI ST\b", ["commonspirit.org", "stlukeshealth.org"]),
    (r"\bTEXAS CHILDREN", ["texaschildrens.org"]),
    (r"\bHARRIS HEALTH\b", ["harrishealth.org"]),
    (r"\bASCENSION\b|\bSETON\b|\bDELL CHILDREN", ["healthcare.ascension.org"]),
    (r"\bBAYLOR SCOTT\b|\bSCOTT (AND|&) WHITE\b|\bBAYLOR (UNIVERSITY|MEDICAL|REGIONAL|EMERGENCY|HEART)\b", ["bswhealth.com"]),
    (r"\bMETHODIST (DALLAS|CHARLTON|RICHARDSON|MANSFIELD|MIDLOTHIAN|SOUTHLAKE)\b", ["methodisthealthsystem.org"]),
    (r"\bST\.? ?DAVID", ["stdavids.com"]),
    (r"\bMEDICAL CITY\b", ["medicalcityhealthcare.com"]),
    (r"\bCHRISTUS\b", ["christushealth.org"]),
    (r"\bUNIVERSITY HEALTH SYSTEM\b", ["universityhealth.com"]),
    (r"\bPARKLAND\b", ["parklandhealth.org"]),
    (r"\bCOOK CHILDREN", ["cookchildrens.org"]),
    (r"\bCHILDRENS MEDICAL (CENTER|CTR)\b", ["childrens.com"]),
    (r"UNIVERSITY OF TEXAS MEDICAL BRANCH", ["utmb.edu"]),
    (r"\bJPS\b", ["jpshealthnet.org"]),
    (r"UNIVERSITY MEDICAL CENTER OF EL PASO", ["umcelpaso.org"]),
    (r"SOUTHWESTERN UNIVERSITY HOSPITAL", ["utsouthwestern.edu"]),
]


def registrable(host: str) -> str:
    """'healthcare.ascension.org' -> 'ascension.org': the part of a hostname that names the
    organisation, so a sibling host of the same site can be recognised."""
    host = host.lower().removeprefix("www.")
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) > 2 else host


def hosts_to_try(host: str) -> list[str]:
    """A host and, when it is a subdomain, its apex too: an index may sit at either."""
    apex = registrable(host)
    return [host] if apex == host.removeprefix("www.") else [host, apex]

HPT_KEYS = {"location-name", "source-page-url", "mrf-url", "contact-name", "contact-email"}
HPT_LINE = re.compile(r"^\s*(location-name|source-page-url|mrf-url|contact-name|contact-email)\s*:\s*(.*?)\s*$", re.I)

# Words that carry no identity when matching a CMS facility name to an index entry.
NOISE = {"HOSPITAL", "HOSPITALS", "HEALTHCARE", "HEALTH", "MEDICAL", "CENTER", "CENTRE", "THE", "OF",
         "LLC", "LP", "INC", "SYSTEM", "CHI", "AND", "AT"}
FREESTANDING_ER = re.compile(r"\bER 24/7\b|\bEMERGENCY CENTER\b|\bFREESTANDING\b", re.I)


@dataclass(frozen=True)
class HptEntry:
    location_name: str
    source_page_url: str | None
    mrf_url: str | None
    contact_name: str | None = None
    contact_email: str | None = None


@dataclass(frozen=True)
class HptResult:
    domain: str
    url: str | None  # the URL that answered, when one did
    status: str  # ok | 404 | blocked | html | timeout | error
    text: str | None
    reason: str


@dataclass(frozen=True)
class Match:
    verdict: str  # matched | ambiguous | none
    entry: HptEntry | None
    score: float
    candidates: tuple[tuple[HptEntry, float], ...]


@dataclass(frozen=True)
class Probe:
    url: str
    ok: bool
    status_code: int | None
    final_url: str | None
    content_type: str | None
    size_bytes: int | None
    last_modified: str | None
    etag: str | None
    shape: str  # json | csv | zip | unknown
    reason: str


@dataclass
class Discovery:
    ccn: str
    name: str
    method: str  # cms-hpt | cms-hpt+tie-break | web-search+cms-hpt | failed
    domain: str | None = None
    index_url: str | None = None
    entry: HptEntry | None = None
    probe: Probe | None = None
    reason: str = ""
    steps: list[str] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.probe is not None and self.probe.ok


# --- domains ---------------------------------------------------------------------------

def _clean_name(name: str) -> str:
    name = name.upper().replace("&", " AND ").replace("'", "").replace("\u2019", "")  # Children's -> CHILDRENS
    name = re.sub(r"[^A-Z0-9 ]+", " ", name)
    return " ".join(name.split())


def domain_candidates(hospital: Hospital) -> list[str]:
    """Seeded system domains first, then guesses from the name. Order matters."""
    name = _clean_name(hospital.name)
    out: list[str] = []
    for pattern, domains in SYSTEM_DOMAINS:
        if re.search(pattern, name):
            out.extend(domains)
    tokens = [t for t in name.split() if t not in {"THE", "LLC", "LP", "INC"}]
    without_hospital = [t for t in tokens if t not in {"HOSPITAL", "HOSPITALS"}]
    for words in (without_hospital, tokens):
        if not words:
            continue
        stem = "".join(words).lower()
        for tld in ("com", "org"):
            guess = f"{stem}.{tld}"
            if guess not in out:
                out.append(guess)
    return out


# --- cms-hpt.txt -----------------------------------------------------------------------

def _looks_like_hpt(text: str) -> bool:
    return bool(re.search(r"^\s*(location-name|mrf-url)\s*:", text, re.I | re.M))


def fetch_hpt(client: httpx.Client, domain: str) -> HptResult:
    """Try https://{domain}/cms-hpt.txt, then the www. form. Never raises."""
    hosts = [domain] if domain.startswith("www.") else [domain, f"www.{domain}"]
    reasons = []
    for host in hosts:
        url = f"https://{host}/cms-hpt.txt"
        try:
            resp = client.get(url, headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=INDEX_TIMEOUT)
        except httpx.TimeoutException:
            reasons.append(f"{host}: timeout")
            status = "timeout"
            continue
        except httpx.HTTPError as e:
            reasons.append(f"{host}: {type(e).__name__}")
            status = "error"
            continue
        if resp.status_code == 200 and _looks_like_hpt(resp.text):
            return HptResult(domain, str(resp.url), "ok", resp.text, "")
        if resp.status_code == 200:
            reasons.append(f"{host}: 200 but not an index file ({resp.headers.get('content-type', '?')})")
            status = "html"
        elif resp.status_code in (401, 403):
            reasons.append(f"{host}: {resp.status_code} blocked")
            status = "blocked"
        elif resp.status_code == 404:
            reasons.append(f"{host}: 404")
            status = "404"
        else:
            reasons.append(f"{host}: HTTP {resp.status_code}")
            status = "error"
    return HptResult(domain, None, status, None, "; ".join(reasons))


def parse_hpt(text: str) -> list[HptEntry]:
    """Entries from an index file. Tolerates banner text, CRLF, `key:value` without a space
    and stray whitespace. A new `location-name` starts a new entry."""
    entries: list[HptEntry] = []
    current: dict[str, str] = {}

    def flush() -> None:
        if current.get("location-name"):
            entries.append(HptEntry(
                location_name=current["location-name"],
                source_page_url=current.get("source-page-url") or None,
                mrf_url=current.get("mrf-url") or None,
                contact_name=current.get("contact-name") or None,
                contact_email=current.get("contact-email") or None,
            ))

    for line in text.splitlines():
        m = HPT_LINE.match(line)
        if not m:
            continue
        key, value = m.group(1).lower(), m.group(2).strip()
        if key == "location-name":
            flush()
            current = {}
        current[key] = value
    flush()
    return entries


# --- a file linked from the site, when there is no index -------------------------------

HREF = re.compile(r'''href\s*=\s*["']([^"']+)["']''', re.I)
TRANSPARENCY_PAGE = re.compile(r"transparen|standard.?charge|machine.?readable|chargemaster|price.?estimat", re.I)
# CMS's required filename: <EIN>_<hospital-name>_standardcharges.<json|csv|zip>
STANDARD_CHARGES_FILE = re.compile(r"standard.?charges[^/]*\.(json|csv|zip)(\?|$)|\b\d{2}-?\d{7}_[^/]*\.(json|csv|zip)(\?|$)", re.I)
COMMON_PATHS = ("/price-transparency", "/pricing-transparency", "/standard-charges", "/price-transparency/")


@dataclass(frozen=True)
class SiteResult:
    domain: str
    pages: tuple[str, ...]  # pages that answered
    files: tuple[tuple[str, str], ...]  # (file url, page it was linked from)
    # Hosts of the same organisation that a pricing link pointed at (ascension.org's home
    # page links to healthcare.ascension.org/price-transparency): the index may be there.
    related_hosts: tuple[str, ...] = ()


def _get_html(client: httpx.Client, url: str) -> tuple[str | None, str | None]:
    try:
        r = client.get(url, headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=INDEX_TIMEOUT)
    except httpx.HTTPError:
        return None, None
    if r.status_code != 200 or "html" not in r.headers.get("content-type", "html"):
        return None, None
    return r.text, str(r.url)


def find_file_on_site(client: httpx.Client, domain: str) -> SiteResult:
    """Home page → links that mention price transparency (and a few common paths) →
    links to standard-charges files. Same host only; at most four pages fetched."""
    host = domain if domain.startswith("www.") else domain
    base = f"https://{host}/"
    pages: list[str] = []
    files: dict[str, str] = {}
    related: list[str] = []
    to_visit: list[str] = [base] + [urljoin(base, p) for p in COMMON_PATHS]
    seen: set[str] = set()
    while to_visit and len(pages) < 4:
        url = to_visit.pop(0)
        if url in seen:
            continue
        seen.add(url)
        html, final = _get_html(client, url)
        if html is None:
            continue
        pages.append(final)
        for href in HREF.findall(html):
            link = urljoin(final, href.strip())
            link_host, page_host = urlsplit(link).netloc.lower(), urlsplit(final).netloc.lower()
            if link_host.removeprefix("www.") != page_host.removeprefix("www."):
                if (link_host and TRANSPARENCY_PAGE.search(href) and registrable(link_host) == registrable(page_host)
                        and link_host not in related):
                    related.append(link_host)
                continue
            if STANDARD_CHARGES_FILE.search(link):
                files.setdefault(link, final)
            elif TRANSPARENCY_PAGE.search(href) and link not in seen and len(to_visit) < 6:
                to_visit.append(link)
    return SiteResult(domain, tuple(pages), tuple(files.items()), tuple(related))


# --- an identifier in the filename ------------------------------------------------------

# Some systems name a file with the campus's NPI after the parent's EIN
# (741109643-1124137054_ascension-seton_standardcharges.csv). The NPI registry is public
# and answers with the registered practice address, which is a fact the CMS dataset can be
# checked against. Used only to settle a tie between candidates the name match produced,
# and only when exactly one candidate's registered address is the hospital's.
NPI_REGISTRY = "https://npiregistry.cms.hhs.gov/api/"
NPI_IN_NAME = re.compile(r"(?<!\d)(\d{10})(?!\d)")


def npi_valid(npi: str) -> bool:
    """The NPI check digit: Luhn over the number with the card-issuer prefix 80840."""
    if not re.fullmatch(r"\d{10}", npi):
        return False
    total = 0
    for i, ch in enumerate(reversed("80840" + npi)):
        n = int(ch)
        if i % 2 == 1:
            n = n * 2 - 9 if n * 2 > 9 else n * 2
        total += n
    return total % 10 == 0


def npi_in(url: str | None) -> str | None:
    """A valid NPI in the file's name, or None. After an EIN, the NPI comes second."""
    name = urlsplit(url or "").path.rsplit("/", 1)[-1]
    found = [n for n in NPI_IN_NAME.findall(name) if npi_valid(n)]
    return found[-1] if found else None


def npi_location(client: httpx.Client, npi: str) -> dict | None:
    """The registered practice location for an NPI; {} when the registry has no such
    number, None when it does not answer. Either way it settles nothing."""
    try:
        r = client.get(NPI_REGISTRY, params={"version": "2.1", "number": npi},
                       headers={"User-Agent": USER_AGENT}, timeout=PROBE_TIMEOUT)
        if r.status_code != 200:
            return None
        results = r.json().get("results") or []
        if not results:
            return {}  # the registry answered: nobody has this NPI
        loc = next((a for a in results[0].get("addresses", []) if a.get("address_purpose") == "LOCATION"), None)
        if not loc:
            return {}
        return {"name": (results[0].get("basic") or {}).get("organization_name"), "address": loc.get("address_1"),
                "city": loc.get("city"), "state": loc.get("state"), "zip": (loc.get("postal_code") or "")[:5]}
    except (httpx.HTTPError, ValueError):
        return None


def _street_number(address: str | None) -> str | None:
    m = re.match(r"\s*(\d+)", address or "")
    return m.group(1) if m else None


def same_place(hospital: Hospital, loc: dict) -> bool:
    """The same street number, in the same city or ZIP: enough to tell sister campuses
    apart, and not something a stale registry entry would produce by accident."""
    number = _street_number(hospital.address)
    if not number or number != _street_number(loc.get("address")):
        return False
    return _clean_name(loc.get("city") or "") == _clean_name(hospital.city) or loc.get("zip") == (hospital.zip or "")[:5]


def npi_tie_break(client: httpx.Client, hospital: Hospital, candidates: list[HptEntry]) -> tuple[HptEntry | None, str]:
    """Deterministic and free. Exactly one candidate whose filename NPI is registered at
    the hospital's address wins; anything else is no answer, and the model tie-break
    remains. Two candidates sharing one NPI share one file and cannot be told apart here."""
    npis = {e: npi_in(e.mrf_url) for e in candidates}
    if not any(npis.values()):
        return None, "no NPI in the filenames"
    looked: dict[str, dict | None] = {}
    matches: list[tuple[HptEntry, str, dict]] = []
    for e, npi in npis.items():
        if not npi:
            continue
        if npi not in looked:
            looked[npi] = npi_location(client, npi)
        loc = looked[npi]
        if loc and same_place(hospital, loc):
            matches.append((e, npi, loc))
    if len(matches) == 1:
        e, npi, loc = matches[0]
        return e, f"NPI {npi} in its filename is registered at {loc['address']}, {loc['city']}, the hospital's own address"
    if not matches:
        if all(v is None for v in looked.values()):
            return None, "the NPI registry did not answer"
        return None, "no candidate's NPI is registered at the hospital's address"
    return None, f"{len(matches)} candidates' NPIs are registered at the hospital's address"


# --- matching --------------------------------------------------------------------------

# CMS abbreviates where an index spells out: "DELL SETON MED CENTER AT THE UNIVERSITY OF TX".
ABBREVIATIONS = {"MED": "MEDICAL", "CTR": "CENTER", "HOSP": "HOSPITAL", "UNIV": "UNIVERSITY", "TX": "TEXAS",
                 "REG": "REGIONAL", "MEM": "MEMORIAL"}


def _match_tokens(name: str) -> str:
    return " ".join(t for t in (ABBREVIATIONS.get(w, w) for w in _clean_name(name).split()) if t not in NOISE)


DBA = re.compile(r"(?<!\w)(?:d/b/a|dba)/?(?!\w)", re.I)


SYSTEM_SUFFIX = re.compile(r"\s*\(([^)]*)\)\s*$")


def shared_suffixes(entries: list[HptEntry]) -> set[str]:
    """Parentheticals that several entries of one index end with: the system's name
    ("(Ascension Seton)" on eleven campuses), not a campus qualifier ("(McNair)" on one)."""
    seen: dict[str, int] = {}
    for e in entries:
        m = SYSTEM_SUFFIX.search(e.location_name)
        if m:
            key = _clean_name(m.group(1))
            seen[key] = seen.get(key, 0) + 1
    return {k for k, n in seen.items() if n >= 2}


def _entry_aliases(name: str, shared: set[str] = frozenset()) -> list[str]:
    """An index entry may carry a legal name: "23330 Emergency Center, LLC d/b/a Elite
    Hospital Kingwood". Match on the trade name too. A trailing parenthetical that the
    index puts on several entries is the system, not part of the campus name, so the
    name without it is an alias as well; one that appears once ("(McNair)") stays."""
    parts = [p.strip(" ,/") for p in DBA.split(name)]
    out = [name] + [p for p in parts[1:] if p]
    for a in list(out):
        m = SYSTEM_SUFFIX.search(a)
        if m and _clean_name(m.group(1)) in shared:
            bare = a[:m.start()].strip()
            if bare and bare not in out:
                out.append(bare)
    return out


def _entry_score(target: str, entry: HptEntry, shared: set[str] = frozenset()) -> float:
    return max(float(fuzz.token_sort_ratio(target, _match_tokens(a))) for a in _entry_aliases(entry.location_name, shared))


def match_entry(hospital: Hospital, entries: list[HptEntry], accept: float = 90, margin: float = 10) -> Match:
    """Name match, ignoring words that carry no identity. `matched` only when the best
    entry clearly beats the runner-up; near-duplicates (Baylor St. Luke's vs Baylor St.
    Luke's (McNair)) come back `ambiguous` for a tie-breaker, never silently picked."""
    target = _match_tokens(hospital.name)
    shared = shared_suffixes(entries)
    # Tokens that most entries share are the system's name ("MEMORIAL HERMANN") and say
    # nothing about which campus. A candidate must share a token that isn't one of those,
    # or it's a different campus of the same system, not a near miss.
    entry_tokens = [set(_match_tokens(a).split()) for e in entries for a in _entry_aliases(e.location_name, shared)]
    common = {t for t in set().union(*entry_tokens) if sum(t in toks for toks in entry_tokens) * 2 >= len(entries)} if entries else set()
    distinctive = set(target.split()) - common
    # The CMS name, word for word, is one entry's name: that is a match, not a fuzzy
    # score to weigh against a sister campus that differs by one word (Northwest, Southwest).
    target_set = set(target.split())
    exact = [e for e in entries
             if target_set and any(set(_match_tokens(a).split()) == target_set for a in _entry_aliases(e.location_name, shared))]
    scored = []
    for e in entries:
        # "23330 Emergency Center, LLC d/b/a Elite Hospital Kingwood" is a hospital; judge
        # the ER pattern on the trade name, not only the legal one.
        aliases = _entry_aliases(e.location_name, shared)
        if all(FREESTANDING_ER.search(a) for a in aliases):
            continue
        score = _entry_score(target, e, shared)
        if distinctive and not any(distinctive & set(_match_tokens(a).split()) for a in aliases):
            score = min(score, 30.0)
        if len(exact) == 1 and e is exact[0]:
            score = 100.0
        scored.append((e, score))
    scored.sort(key=lambda x: -x[1])
    # Candidates: plausible on their own (>= 40) and not far behind the best, so a
    # system-level CMS name ("HARRIS HEALTH") keeps both of the system's hospitals.
    top = scored[0][1] if scored else 0.0
    candidates = tuple((e, s) for e, s in scored[:5] if s >= 40 and s >= top - 25)
    if not candidates:
        return Match("none", None, scored[0][1] if scored else 0.0, ())
    best, best_score = candidates[0]
    runner_up = candidates[1][1] if len(candidates) > 1 else 0.0
    if len(exact) == 1 and best is exact[0]:
        return Match("matched", best, best_score, candidates)
    if best_score >= accept and best_score - runner_up >= margin:
        return Match("matched", best, best_score, candidates)
    return Match("ambiguous", None, best_score, candidates)


# --- probing the file ------------------------------------------------------------------

def _shape(url: str, content_type: str | None, disposition: str | None = None, first: bytes = b"") -> str:
    """json / csv / zip from, in order: the URL path, the download filename, the content
    type, and the first bytes (a `.ashx` handler that serves JSON is common)."""
    names = [url.split("?", 1)[0].lower()]
    m = re.search(r'filename\*?="?([^";]+)', disposition or "", re.I)
    if m:
        names.append(m.group(1).lower())
    for name in names:
        for ext, shape in ((".json", "json"), (".csv", "csv"), (".zip", "zip")):
            if name.endswith(ext):
                return shape
    ct = (content_type or "").lower()
    for key, shape in (("json", "json"), ("csv", "csv"), ("zip", "zip")):
        if key in ct:
            return shape
    head = first.lstrip(b"\xef\xbb\xbf \t\r\n")
    if head.startswith(b"{") or head.startswith(b"["):
        return "json"
    if head.startswith(b"PK"):
        return "zip"
    if head and all(32 <= b < 127 or b in (9, 10, 13) for b in head) and b"," in head:
        return "csv"
    return "unknown"


def probe_mrf(client: httpx.Client, url: str) -> Probe:
    """HEAD first; then a 64-byte range GET when HEAD is refused, gives no size, or the
    shape isn't clear from the name and content type. At most 64 bytes are ever read."""
    headers = {"User-Agent": USER_AGENT}
    try:
        head = client.head(url, headers=headers, follow_redirects=True, timeout=PROBE_TIMEOUT)
        # A HEAD that says 0 bytes is a server that does not size the file (Ascension), not
        # an empty file: treat it as unknown and let the GET decide.
        size = _int(head.headers.get("content-length")) or None
        shape = _shape(str(head.url), head.headers.get("content-type"), head.headers.get("content-disposition"))
        if head.status_code < 400 and size is not None and shape != "unknown":
            return _probe_from(url, head, size, shape, b"")
        with client.stream("GET", url, headers={**headers, "Range": "bytes=0-63"},
                           follow_redirects=True, timeout=PROBE_TIMEOUT) as r:
            first = b"".join(_take(r.iter_bytes(), 64)) if r.status_code < 400 else b""
            size = _total_from_range(r.headers.get("content-range")) or size or (
                _int(r.headers.get("content-length")) or None if r.status_code == 200 else None)
            shape = _shape(str(r.url), r.headers.get("content-type"), r.headers.get("content-disposition"), first)
            return _probe_from(url, r, size, shape, first)
    except httpx.TimeoutException:
        return Probe(url, False, None, None, None, None, None, None, _shape(url, None), "timeout")
    except httpx.HTTPError as e:
        return Probe(url, False, None, None, None, None, None, None, _shape(url, None), type(e).__name__)


def _take(chunks, n: int):
    got = 0
    for c in chunks:
        yield c[: n - got]
        got += len(c)
        if got >= n:
            return


def _probe_from(url: str, resp: httpx.Response, size: int | None, shape: str, first: bytes) -> Probe:
    ct = resp.headers.get("content-type")
    ok = resp.status_code < 400
    reason = "" if ok else f"HTTP {resp.status_code}"
    if ok and ("text/html" in (ct or "") or first.lstrip().lower().startswith(b"<!doctype") or first.lstrip().lower().startswith(b"<html")):
        ok, reason = False, "HTML page, not a data file (login wall or moved?)"
    return Probe(url, ok, resp.status_code, str(resp.url), ct, size,
                 resp.headers.get("last-modified"), resp.headers.get("etag"), shape, reason)


def _int(v: str | None) -> int | None:
    try:
        return int(v) if v is not None else None
    except ValueError:
        return None


def _total_from_range(v: str | None) -> int | None:
    m = re.search(r"/(\d+)$", v or "")
    return int(m.group(1)) if m else None


# --- orchestration ---------------------------------------------------------------------

Trace = Callable[[str], None]
TieBreaker = Callable[[Hospital, list[HptEntry]], tuple[HptEntry | None, str]]
WebSearch = Callable[[Hospital], tuple[str | None, str]]


def _entry_from_site(hospital: Hospital, site: SiteResult, tie_breaker: TieBreaker | None, step) -> HptEntry | None:
    """One linked file is the answer; several need a tie-break (a system site listing
    every campus). Shoppable-services files are not the machine-readable file."""
    entries = [HptEntry(url.rsplit("/", 1)[-1].split("?")[0], page, url) for url, page in site.files
               if not re.search(r"shoppable", url, re.I)]
    if not entries:
        step("linked files are shoppable-services lists, not the standard charges file")
        return None
    if len(entries) == 1:
        step(f"standard charges file linked: {entries[0].mrf_url}")
        return entries[0]
    m = match_entry(hospital, entries)
    if m.verdict == "matched":
        step(f"{len(entries)} files linked, matched {m.entry.location_name}")
        return m.entry
    names = "; ".join(e.location_name for e in entries[:5])
    step(f"{len(entries)} files linked, ambiguous: {names}")
    if tie_breaker is None:
        return None
    entry, why = tie_breaker(hospital, entries[:5])
    step(f"tie-break picked {entry.location_name} ({why})" if entry else f"tie-break declined: {why}")
    return entry


def short_name(hospital: Hospital) -> str:
    def word(w: str) -> str:
        return w if w in {"HCA", "CHI", "LLC", "LP"} else "-".join(p.capitalize() for p in w.split("-"))
    return " ".join(word(w) for w in hospital.name.split())


def locate_price_file(
    client: httpx.Client,
    hospital: Hospital,
    trace: Trace = lambda line: None,
    tie_breaker: TieBreaker | None = None,
    web_search: WebSearch | None = None,
) -> Discovery:
    started = time.monotonic()
    who = short_name(hospital)
    d = Discovery(hospital.ccn, hospital.name, "failed")

    def step(line: str) -> None:
        d.steps.append(line)
        trace(f"{who}: {line}")

    # 1. an index file on a candidate domain
    index: HptResult | None = None
    tried = []
    alive: list[str] = []  # domains that answered, just not with an index
    for domain in domain_candidates(hospital):
        r = fetch_hpt(client, domain)
        if r.status == "ok":
            index = r
            step(f"cms-hpt.txt found at {r.url}")
            break
        tried.append(r.reason)
        if r.status in ("404", "html", "blocked"):
            alive.append(domain)
    # 1b. no index, but a site that answers: look for a linked standard-charges file, and
    # for a pricing link to a sibling host of the same organisation, where the index may be
    site_entry: HptEntry | None = None
    related: list[str] = []

    def note_related(site: SiteResult, host: str) -> None:
        for h in site.related_hosts:
            if h != host and h not in related and h not in alive:
                related.append(h)

    def try_host(host: str, how: str) -> bool:
        """An index on `host`, or a standard-charges link on its pages. `how` names the
        way the host was found, for the method recorded with the result."""
        nonlocal index, site_entry
        r = fetch_hpt(client, host)
        if r.status == "ok":
            index = r
            d.method = f"{how}cms-hpt"
            step(f"cms-hpt.txt found at {r.url}")
            return True
        tried.append(r.reason)
        site = find_file_on_site(client, host)
        note_related(site, host)
        if site.files:
            step(f"no cms-hpt.txt at {host}, but {len(site.files)} standard-charges link(s) on {site.files[0][1]}")
            site_entry = _entry_from_site(hospital, site, tie_breaker, step)
            if site_entry:
                d.domain, d.index_url, d.method = host, site.files[0][1], f"{how}site-page"
                return True
        return False

    def try_related(how: str) -> bool:
        while related:
            host = related.pop(0)
            step(f"a pricing link points at {host}, trying there")
            if try_host(host, how):
                return True
        return False

    if index is None:
        for domain in alive:
            site = find_file_on_site(client, domain)
            note_related(site, domain)
            if site.files:
                step(f"no cms-hpt.txt at {domain}, but {len(site.files)} standard-charges link(s) on {site.files[0][1]}")
                site_entry = _entry_from_site(hospital, site, tie_breaker, step)
                if site_entry:
                    d.domain, d.index_url, d.method = domain, site.files[0][1], "site-page"
                    break
    if index is None and site_entry is None:
        try_related("site-link+")
    if index is None and site_entry is None and web_search is not None:
        step("cms-hpt.txt missing on guessed domains, searching the web for the site")
        found, why = web_search(hospital)
        if found:
            step(f"web search says {found} ({why})")
            # The hospital's page may sit on a subdomain and the index on it or on the apex,
            # or a pricing link on either may point at where it is.
            if not any(try_host(domain, "web-search+") for domain in hosts_to_try(found)):
                try_related("web-search+site-link+")
        else:
            step(f"web search found no site ({why})")
    if index is None and site_entry is None:
        d.reason = "no cms-hpt.txt or linked file located: " + "; ".join(tried)
        step("no machine-readable index located — skipped")
        d.seconds = time.monotonic() - started
        return d
    if index is not None:
        d.domain, d.index_url = index.domain, index.url
        if d.method == "failed":
            d.method = "cms-hpt"

    # 2. which entry is this hospital?
    entries = parse_hpt(index.text or "") if index is not None else []
    m = match_entry(hospital, entries) if index is not None else Match("matched", site_entry, 100.0, ())
    entry = m.entry
    if site_entry is not None:
        pass
    elif m.verdict == "ambiguous":
        names = "; ".join(f"{e.location_name} ({s:.0f})" for e, s in m.candidates)
        step(f"{len(entries)} entries, ambiguous match: {names}")
        cands = [e for e, _ in m.candidates]
        # An identifier in the filename settles it for free when it can; the model only
        # gets the question when it cannot.
        entry, why = npi_tie_break(client, hospital, cands)
        if entry:
            d.method += "+npi"
            step(f"NPI settled it: {entry.location_name} ({why})")
        else:
            if why != "no NPI in the filenames":
                step(f"NPI could not settle it ({why})")
            if tie_breaker is not None:
                entry, why = tie_breaker(hospital, cands)
                if entry:
                    d.method += "+tie-break"
                    step(f"tie-break picked {entry.location_name} ({why})")
                else:
                    step(f"tie-break declined: {why}")
    elif m.verdict == "matched":
        step(f"{len(entries)} entries, matched {entry.location_name} ({m.score:.0f})")
    else:
        step(f"{len(entries)} entries, none resemble {hospital.name}")
    if entry is None:
        d.reason = f"index found but no entry for this hospital ({m.verdict})"
        d.seconds = time.monotonic() - started
        return d
    d.entry = entry
    if not entry.mrf_url:
        d.reason = "entry has no mrf-url"
        step("entry has no mrf-url — skipped")
        d.seconds = time.monotonic() - started
        return d

    # 3. is the file really there?
    p = probe_mrf(client, entry.mrf_url)
    d.probe = p
    if p.ok:
        size = (f"{p.size_bytes / 1e6:,.0f} MB" if p.size_bytes >= 1_000_000 else f"{p.size_bytes / 1e3:,.0f} KB") if p.size_bytes else "size unknown"
        step(f"price file {p.shape}, {size}" + (f", modified {p.last_modified}" if p.last_modified else ""))
    else:
        d.reason = f"file URL failed: {p.reason}"
        step(f"file URL failed: {p.reason}")
    d.seconds = time.monotonic() - started
    return d
