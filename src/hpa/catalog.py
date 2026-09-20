"""The procedure catalog: CMS's 70 specified shoppable services, with plain-English aliases.

Searches map to catalog entries rather than to arbitrary codes, so every code the system
scans for is one a person can check. `resolve` is a deterministic candidate search that
says how sure it is; confirming a selection with the user (or Claude) is a later step.
"""

import json
import re
from dataclasses import dataclass, replace
from importlib import resources


@dataclass(frozen=True)
class Service:
    id: str
    category: str
    name: str
    codes: tuple[tuple[str, str], ...]  # (code type, code)
    aliases: tuple[str, ...]
    qualifiers: dict[str, str]  # e.g. {"contrast": "without"}; variants the CMS name leaves implicit
    reviewed: dict | bool  # False, or the review evidence (reviewer, date, per-hospital answers)
    notes: str

    @property
    def code_list(self) -> str:
        return ", ".join(f"{t} {c}" for t, c in self.codes)


SELECTED = "selected"  # one entry clearly fits
AMBIGUOUS = "ambiguous"  # several entries fit equally; ask which
UNSUPPORTED_VARIANT = "unsupported variant"  # the service exists, but not in the variant asked for
NOT_IN_CATALOG = "not in catalog"  # nothing covers the whole query
NEEDS_CLARIFICATION = "needs clarification"  # a qualifier the catalog can't answer, or contradictory ones


@dataclass(frozen=True)
class Resolution:
    verdict: str
    service: Service | None
    candidates: tuple[Service, ...] = ()
    reason: str = ""
    # Spellings the resolver read as something else, e.g. (("colonscopy", "colonoscopy"),).
    # Always shown to the reader: a corrected query is an answer to a question nobody
    # asked, unless it says so.
    corrections: tuple[tuple[str, str], ...] = ()


def load() -> list[Service]:
    raw = json.loads(resources.files("hpa.data").joinpath("shoppable_services.json").read_text())
    return [
        Service(
            id=s["id"],
            category=s["category"],
            name=s["name"],
            codes=tuple((c["type"], c["code"]) for c in s["codes"]),
            aliases=tuple(s["aliases"]),
            qualifiers=dict(s["qualifiers"]),
            reviewed=s["reviewed"] or False,
            notes=s["notes"],
        )
        for s in raw["services"]
    ]


# Words that carry no meaning for matching. "test" and "study" are kept: they appear in
# service names ("Sleep study", "Blood test, clotting time").
STOPWORDS = {"a", "an", "the", "of", "for", "and", "or", "my", "scan", "exam", "procedure"}

# (pattern, qualifier key, qualifier value). Order matters: "with and without" first.
QUALIFIER_PATTERNS = [
    (r"\b(with and without|with/without|w/ and w/o)\s+contrast\b", "contrast", "with and without"),
    (r"\b(without|w/o|no|non[- ]?)\s*contrast\b", "contrast", "without"),
    (r"\b(with|w/)\s+contrast\b", "contrast", "with"),
    (r"\b(without|w/o|no)\s+biops(y|ies)\b", "biopsy", "without"),
    (r"\b(with|w/)\s+biops(y|ies)\b", "biopsy", "with"),
]


def _tokens(text: str) -> set[str]:
    text = re.sub(r"(?<=\w)-(?=\w)", "", text.lower())  # x-ray -> xray
    return set(re.findall(r"[a-z0-9]+", text)) - STOPWORDS


def parse_query(query: str) -> tuple[set[str], dict[str, set[str]], str]:
    """Split a query into content tokens, requested qualifiers (every value asked for,
    so contradictions are visible), and the stripped phrase."""
    text = query.lower()
    wanted: dict[str, set[str]] = {}
    for pattern, key, value in QUALIFIER_PATTERNS:
        if re.search(pattern, text):
            wanted.setdefault(key, set()).add(value)
            text = re.sub(pattern, " ", text)
    phrase = " ".join(text.split())
    return _tokens(phrase), wanted, phrase


def _haystack(s: Service) -> set[str]:
    return _tokens(s.name) | _tokens(" ".join(s.aliases))


# A misspelling is a string-distance problem, not a question of meaning, so it is fixed
# here rather than by a model. Only close, long-enough words qualify: "mri" must never
# become "mra", and a word nobody in the catalog uses stays unmatched.
TYPO_SCORE = 87
TYPO_MIN_LENGTH = 5


def vocabulary(services: list[Service]) -> set[str]:
    words: set[str] = set()
    for s in services:
        words |= _haystack(s)
    return words


def correct_tokens(tokens: set[str], services: list[Service]) -> dict[str, str]:
    """{typed word: the catalog's word}, for words the catalog does not contain."""
    from rapidfuzz import fuzz, process

    known = vocabulary(services)
    fixes: dict[str, str] = {}
    for token in tokens - known:
        if len(token) < TYPO_MIN_LENGTH:
            continue
        match = process.extractOne(token, known, scorer=fuzz.ratio, score_cutoff=TYPO_SCORE)
        if match:
            fixes[token] = match[0]
    return fixes


def resolve(query: str, services: list[Service] | None = None) -> Resolution:
    """Deterministic: an entry, or a stated reason why not. Never invents a code."""
    services = services if services is not None else load()
    r = _resolve(query, services)
    if r.verdict != NOT_IN_CATALOG or r.candidates:
        return r
    # Nothing matched at all. Before giving up, try reading the unknown words as the
    # catalog's own, and resolve again with what that says.
    tokens, _, _ = parse_query(query)
    fixes = correct_tokens(tokens, services)
    if not fixes:
        return r
    reread = query.lower()
    for typed, known in fixes.items():
        reread = re.sub(rf"\b{re.escape(typed)}\b", known, reread)
    corrected = _resolve(reread, services)
    if corrected.verdict == NOT_IN_CATALOG and not corrected.candidates:
        return r  # the correction did not help; report the original miss
    return replace(corrected, corrections=tuple(fixes.items()))


def _resolve(query: str, services: list[Service]) -> Resolution:
    query = query.strip()
    for s in services:
        if any(code == query for _, code in s.codes):
            return Resolution(SELECTED, s, (s,), f"code {query} matched exactly")

    tokens, asked, phrase = parse_query(query)
    if not tokens:
        return Resolution(NOT_IN_CATALOG, None, (), "no searchable words in the query")
    contradictory = {k: v for k, v in asked.items() if len(v) > 1}
    if contradictory:
        k, v = next(iter(contradictory.items()))
        return Resolution(
            NEEDS_CLARIFICATION, None, (),
            f"the query asks for both {' and '.join(sorted(v))} {k}; which one?",
        )
    wanted = {k: next(iter(v)) for k, v in asked.items()}

    full: list[tuple[float, Service]] = []  # every content word matched, no qualifier conflict
    conflicts: list[Service] = []  # every word matched, but a different variant
    unknown: list[tuple[Service, str]] = []  # every word matched, but a qualifier the entry doesn't declare
    partial: list[tuple[float, Service]] = []
    for s in services:
        coverage = len(tokens & _haystack(s)) / len(tokens)
        if coverage == 0:
            continue
        score = coverage
        if phrase == s.name.lower() or phrase in (a.lower() for a in s.aliases):
            score += 0.5  # the whole query is one of this entry's names
        conflict = False
        undeclared = None
        for key, value in wanted.items():
            have = s.qualifiers.get(key)
            if have is None:
                undeclared = key  # never assume; the catalog must say
            elif have == value:
                score += 0.25
            else:
                conflict = True
        if coverage < 1:
            partial.append((score, s))
        elif conflict:
            conflicts.append(s)
        elif undeclared:
            unknown.append((s, undeclared))
        else:
            full.append((score, s))

    if full:
        full.sort(key=lambda x: (-x[0], x[1].name))
        ranked = tuple(s for _, s in full)
        if len(full) == 1 or full[0][0] > full[1][0]:
            return Resolution(SELECTED, ranked[0], ranked, "")
        tied = [s.name for _, s in full if _ == full[0][0]]
        return Resolution(AMBIGUOUS, None, ranked, f"{len(tied)} entries fit equally: " + "; ".join(tied))

    if unknown:
        s, key = unknown[0]
        return Resolution(
            NEEDS_CLARIFICATION, None, tuple(u for u, _ in unknown),
            f"the catalog doesn't say whether {s.name} ({s.code_list}) is {wanted[key]} {key}; "
            "ask before scanning",
        )

    if conflicts:
        s = conflicts[0]
        asked = ", ".join(f"{v} {k}" for k, v in wanted.items())
        has = ", ".join(f"{v} {k}" for k, v in s.qualifiers.items())
        return Resolution(
            UNSUPPORTED_VARIANT, None, tuple(conflicts),
            f"the CMS list has {s.name} ({s.code_list}) only {has}; {asked} is not on it",
        )

    partial.sort(key=lambda x: (-x[0], x[1].name))
    closest = tuple(s for _, s in partial[:5])
    missing = sorted(tokens - (_haystack(closest[0]) if closest else set()))
    reason = f"nothing in the catalog matches {' '.join(missing) or query!r}"
    if closest:
        reason += f"; closest is {closest[0].name}"
    return Resolution(NOT_IN_CATALOG, None, closest, reason)


def search(query: str, services: list[Service] | None = None) -> list[Service]:
    """Candidates only, best first. Use `resolve` when the verdict matters."""
    return list(resolve(query, services).candidates)
