"""Find a hospital's price transparency file on the live web.

Deterministic layers, in order: candidate domains (a small seed of Houston health systems
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

# Seed: health systems whose index files were checked by hand for this project. The name
# pattern is matched against the CMS facility name. Everything else is guessed from the
# name and, failing that, looked up with a web search.
SYSTEM_DOMAINS: list[tuple[str, list[str]]] = [
    (r"\bHCA HOUSTON\b", ["hcahoustonhealthcare.com"]),
    (r"\bHOUSTON METHODIST\b", ["houstonmethodist.org"]),
    (r"\bMEMORIAL HERMANN\b", ["memorialhermann.org"]),
    (r"\bST\.? ?LUKE|\bBAYLOR ST\b|\bCHI ST\b", ["commonspirit.org", "stlukeshealth.org"]),
    (r"\bTEXAS CHILDREN", ["texaschildrens.org"]),
    (r"\bHARRIS HEALTH\b", ["harrishealth.org"]),
]

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
            if urlsplit(link).netloc.removeprefix("www.") != urlsplit(final).netloc.removeprefix("www."):
                continue
            if STANDARD_CHARGES_FILE.search(link):
                files.setdefault(link, final)
            elif TRANSPARENCY_PAGE.search(href) and link not in seen and len(to_visit) < 6:
                to_visit.append(link)
    return SiteResult(domain, tuple(pages), tuple(files.items()))


# --- matching --------------------------------------------------------------------------

def _match_tokens(name: str) -> str:
    return " ".join(t for t in _clean_name(name).split() if t not in NOISE)


DBA = re.compile(r"(?<!\w)(?:d/b/a|dba)/?(?!\w)", re.I)


def _entry_aliases(name: str) -> list[str]:
    """An index entry may carry a legal name: "23330 Emergency Center, LLC d/b/a Elite
    Hospital Kingwood". Match on the trade name too."""
    parts = [p.strip(" ,/") for p in DBA.split(name)]
    return [name] + [p for p in parts[1:] if p]


def _entry_score(target: str, entry: HptEntry) -> float:
    return max(float(fuzz.token_sort_ratio(target, _match_tokens(a))) for a in _entry_aliases(entry.location_name))


def match_entry(hospital: Hospital, entries: list[HptEntry], accept: float = 90, margin: float = 10) -> Match:
    """Name match, ignoring words that carry no identity. `matched` only when the best
    entry clearly beats the runner-up; near-duplicates (Baylor St. Luke's vs Baylor St.
    Luke's (McNair)) come back `ambiguous` for a tie-breaker, never silently picked."""
    target = _match_tokens(hospital.name)
    # Tokens that most entries share are the system's name ("MEMORIAL HERMANN") and say
    # nothing about which campus. A candidate must share a token that isn't one of those,
    # or it's a different campus of the same system, not a near miss.
    entry_tokens = [set(_match_tokens(a).split()) for e in entries for a in _entry_aliases(e.location_name)]
    common = {t for t in set().union(*entry_tokens) if sum(t in toks for toks in entry_tokens) * 2 >= len(entries)} if entries else set()
    distinctive = set(target.split()) - common
    scored = []
    for e in entries:
        # "23330 Emergency Center, LLC d/b/a Elite Hospital Kingwood" is a hospital; judge
        # the ER pattern on the trade name, not only the legal one.
        aliases = _entry_aliases(e.location_name)
        if all(FREESTANDING_ER.search(a) for a in aliases):
            continue
        score = _entry_score(target, e)
        if distinctive and not any(distinctive & set(_match_tokens(a).split()) for a in aliases):
            score = min(score, 30.0)
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
        size = _int(head.headers.get("content-length"))
        shape = _shape(str(head.url), head.headers.get("content-type"), head.headers.get("content-disposition"))
        if head.status_code < 400 and size is not None and shape != "unknown":
            return _probe_from(url, head, size, shape, b"")
        with client.stream("GET", url, headers={**headers, "Range": "bytes=0-63"},
                           follow_redirects=True, timeout=PROBE_TIMEOUT) as r:
            first = b"".join(_take(r.iter_bytes(), 64)) if r.status_code < 400 else b""
            size = _total_from_range(r.headers.get("content-range")) or size or (
                _int(r.headers.get("content-length")) if r.status_code == 200 else None)
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
    # 1b. no index, but a site that answers: look for a linked standard-charges file
    site_entry: HptEntry | None = None
    if index is None:
        for domain in alive:
            site = find_file_on_site(client, domain)
            if site.files:
                step(f"no cms-hpt.txt at {domain}, but {len(site.files)} standard-charges link(s) on {site.files[0][1]}")
                site_entry = _entry_from_site(hospital, site, tie_breaker, step)
                if site_entry:
                    d.domain, d.index_url, d.method = domain, site.files[0][1], "site-page"
                    break
    if index is None and site_entry is None and web_search is not None:
        step("cms-hpt.txt missing on guessed domains, searching the web for the site")
        domain, why = web_search(hospital)
        if domain:
            step(f"web search says {domain} ({why})")
            r = fetch_hpt(client, domain)
            if r.status == "ok":
                index = r
                d.method = "web-search+cms-hpt"
                step(f"cms-hpt.txt found at {r.url}")
            else:
                tried.append(r.reason)
                site = find_file_on_site(client, domain)
                if site.files:
                    site_entry = _entry_from_site(hospital, site, tie_breaker, step)
                    if site_entry:
                        d.domain, d.index_url, d.method = domain, site.files[0][1], "web-search+site-page"
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
        if tie_breaker is not None:
            entry, why = tie_breaker(hospital, [e for e, _ in m.candidates])
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
