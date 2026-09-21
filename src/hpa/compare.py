"""Turn the charge lines a hospital lists for a service into one headline and a verdict.

A file rarely has one clean line per CPT code. HCA Kingwood lists CPT 73721 fifty times:
three chargemaster lines (bilateral, right, left) with gross and cash prices, and 47
per-revenue-center lines carrying only negotiated rates. The verdict says which situation
the reader is looking at; the headline is chosen only when the choice is defensible, and
every line stays available.
"""

from dataclasses import dataclass, field

# Charge lines carrying payer rates only (min/max) but no gross or cash price.
COMPARABLE = "comparable"
# Verdicts on a pair of hospitals, as distinct from a verdict on one hospital's lines.
NOT_COMPARABLE = "not comparable"
UNKNOWN_PAIR = "unknown"
UNKNOWN_CLASS = "unknown: no billing class stated"
UNKNOWN_SETTING = "unknown: no setting stated"
MODIFIERS_ONLY = "modifier-specific lines only"
NEGOTIATED_ONLY = "negotiated rates only, no cash or gross price"
PROFESSIONAL_ONLY = "professional charge only, no facility line"
CONFLICTING = "conflicting"
INPATIENT_ONLY = "inpatient line only"
OUTPATIENT_ONLY = "outpatient line only"
NOT_FOUND = "not found"


def expected_setting(codes) -> str:
    """Which setting a service's price is. Sixty-five of the 70 are outpatient services;
    the five MS-DRG entries (joint replacement, spinal fusion, cardiac valve, uterine
    procedures) are hospital stays, priced as inpatient."""
    return "inpatient" if any(t == "MS-DRG" for t, _ in codes) else "outpatient"


@dataclass(frozen=True)
class Line:
    code_type: str
    code: str
    other_codes: tuple[str, ...]  # e.g. ("RC 730",) or ("CDM 434377",)
    description: str
    setting: str | None
    billing_class: str | None
    modifiers: str | None
    gross: float | None
    discounted_cash: float | None
    minimum: float | None
    maximum: float | None
    source_ref: str
    off_template_note: str | None = None
    class_from_review: bool = False  # billing class supplied by a human review, not the file

    @property
    def has_price(self) -> bool:
        return self.discounted_cash is not None or self.gross is not None

    @property
    def context(self) -> str:
        bc = f"{self.billing_class} (per review)" if self.billing_class and self.class_from_review else self.billing_class
        parts = [self.setting, bc, f"mod {self.modifiers}" if self.modifiers else None]
        return ", ".join(p for p in parts if p) or "no context stated"


@dataclass
class Summary:
    verdict: str
    headline: Line | None
    lines: list[Line] = field(default_factory=list)
    detail: str = ""

    @property
    def plain_lines(self) -> list[Line]:
        return [l for l in self.lines if l.modifiers is None and l.billing_class in (None, "facility", "both")]


@dataclass(frozen=True)
class Pair:
    """Whether two hospitals' headline prices can honestly be put side by side."""

    a: str
    b: str
    verdict: str  # comparable | not comparable | unknown
    detail: str

    def __str__(self) -> str:
        return f"compare: {self.a} vs {self.b}: {self.verdict}" + (f" ({self.detail})" if self.detail else "")


# "both" means the charge applies to inpatient and outpatient alike, so it sits happily
# beside either. Anything else must match exactly.
def _same_setting(a: str | None, b: str | None) -> bool:
    return a == b or "both" in (a, b)


def pair(a: dict, b: dict) -> Pair:
    """Compare two hospital results (as `pipeline.hospital_prices` returns them).

    Two missing values are never treated as a match (SPEC): a context either side does not
    state makes the verdict `unknown`, never `comparable`.
    """
    names = (a["name"], b["name"])
    for one in (a, b):
        if not one.get("headline"):
            return Pair(*names, UNKNOWN_PAIR, f"{one['name']} has no priced line for this service")
    la, lb = a["headline"], b["headline"]

    unstated = [f"{one['name']}'s row has no {field.replace('_', ' ')}"
                for one, line in ((a, la), (b, lb))
                for field in ("setting", "billing_class") if line.get(field) is None]
    if unstated:
        return Pair(*names, UNKNOWN_PAIR, "; ".join(unstated))

    differences = []
    # One catalog entry can carry two codes (PSA: 84153 and 84154). Two hospitals' lines
    # are the same service only when they carry the same code. CPT codes are HCPCS
    # level I, and files label the same code either way, so the label is not a difference.
    ca, cb = (la.get("code_type"), la.get("code")), (lb.get("code_type"), lb.get("code"))
    if all(ca) and all(cb) and not _same_code(ca, cb):
        differences.append(f"different codes ({ca[0]} {ca[1]} vs {cb[0]} {cb[1]})")
    if not _same_setting(la.get("setting"), lb.get("setting")):
        differences.append(f"{la['setting']} vs {lb['setting']}")
    if la.get("billing_class") != lb.get("billing_class"):
        differences.append(f"{la['billing_class']} vs {lb['billing_class']} charge")
    if (la.get("modifiers") or None) != (lb.get("modifiers") or None):
        differences.append(f"modifiers {la.get('modifiers') or 'none'} vs {lb.get('modifiers') or 'none'}")
    if differences:
        return Pair(*names, NOT_COMPARABLE, "; ".join(differences))

    shared = [la.get("setting"), la.get("billing_class"), f"mod {la['modifiers']}" if la.get("modifiers") else "no modifiers"]
    return Pair(*names, COMPARABLE, ", ".join(p for p in shared if p))


def _same_code(a: tuple[str, str], b: tuple[str, str]) -> bool:
    family = {"CPT": "HCPCS", "HCPCS": "HCPCS"}
    return a[1] == b[1] and family.get(a[0], a[0]) == family.get(b[0], b[0])


def pairs(hospitals: list[dict]) -> list[Pair]:
    """Every pair, in the order the hospitals were given (nearest first)."""
    return [pair(a, b) for i, a in enumerate(hospitals) for b in hospitals[i + 1:]]


def apply_review(lines: list[Line], review: dict | bool, hospital: str) -> list[Line]:
    """Fill in a billing class a reviewer confirmed for this hospital's line, marking it as
    coming from the review. The file's own value always wins.

    A review is bound to the evidence it looked at: the source ref *and* the line's
    description, when the review recorded one. A hospital that reorders its file moves
    the ref to some other line, and the review must not travel with it. An answer that
    did not confirm the headline ("no", "unsure") is not evidence and is not applied.
    """
    if not review or not isinstance(review, dict):
        return lines
    answers: dict[str, tuple[str, str]] = {}
    for h in review.get("hospitals", []):
        if h.get("hospital") != hospital or not h.get("billing_class") or not h.get("ref"):
            continue
        if (h.get("headline_is_this_service") or "yes") != "yes":
            continue
        answers[h["ref"]] = (h["billing_class"], _norm(h.get("description")))
    if not answers:
        return lines
    from dataclasses import replace

    def confirmed(l: Line) -> str | None:
        a = answers.get(l.source_ref)
        if a is None or l.billing_class is not None:
            return None
        return a[0] if not a[1] or a[1] == _norm(l.description) else None

    return [replace(l, billing_class=bc, class_from_review=True) if (bc := confirmed(l)) else l for l in lines]


def _norm(text: str | None) -> str:
    return " ".join((text or "").split()).lower()


def summarise(lines: list[Line], setting: str = "outpatient") -> Summary:
    """`setting` is the one the service is priced in (see `expected_setting`): a line in
    the other setting is a different price and is reported as such, never mixed in."""
    if not lines:
        return Summary(NOT_FOUND, None, [])
    s = Summary("", None, list(lines))
    plain = [l for l in s.plain_lines if l.has_price]
    with_mods = [l for l in lines if l.modifiers is not None and l.has_price]
    if not plain and not with_mods:
        n = len(lines)
        professional = [l for l in lines if l.has_price and l.billing_class == "professional"]
        if professional:
            # A doctor's fee, not the hospital's: priced, but not the thing being compared.
            s.verdict = PROFESSIONAL_ONLY
            s.detail = f"{len(professional)} priced line{'s' if len(professional) != 1 else ''} carr{'y' if len(professional) != 1 else 'ies'} the professional charge only"
            return s
        s.verdict, s.detail = NEGOTIATED_ONLY, f"{n} line{'s' if n != 1 else ''}, each with negotiated min/max only"
        return s
    if not plain:
        mods = sorted({l.modifiers for l in with_mods})
        s.verdict, s.detail = MODIFIERS_ONLY, f"priced lines carry modifiers {', '.join(mods)}; no unmodified line to compare"
        return s
    fitting = [l for l in plain if l.setting in (setting, "both", None)]
    pool = fitting or plain
    cash = {l.discounted_cash for l in pool if l.discounted_cash is not None}
    gross = {l.gross for l in pool if l.gross is not None}
    if len(cash) > 1 or (not cash and len(gross) > 1):
        s.verdict = CONFLICTING
        vals = sorted(cash) if len(cash) > 1 else sorted(gross)
        s.detail = f"{len(pool)} unmodified lines disagree ({'cash' if len(cash) > 1 else 'gross'} {', '.join(f'${float(v):,.2f}' for v in vals)})"
        return s
    headline = next((l for l in pool if l.discounted_cash is not None), pool[0])
    s.headline = headline
    if headline.billing_class is None:
        s.verdict = UNKNOWN_CLASS
        s.detail = "the file does not say whether this is a facility or professional charge"
    elif headline.setting is None:
        # The pair verdict would say "unknown" for this row; the card must not say more.
        s.verdict = UNKNOWN_SETTING
        s.detail = "the file does not say whether this is an inpatient or outpatient charge"
    else:
        s.verdict = COMPARABLE
    if not fitting:
        other = "inpatient" if setting == "outpatient" else "outpatient"
        s.verdict = INPATIENT_ONLY if other == "inpatient" else OUTPATIENT_ONLY
        s.detail = f"only an {other} line is priced; this service is priced as {setting}, so no comparison"
    elif len(gross) > 1:
        # The cash prices agree, which is what is compared; the gross charges do not,
        # and the one shown is not the only one.
        s.detail = f"cash agrees; gross charges differ ({', '.join(f'${float(v):,.2f}' for v in sorted(gross))})"
    extra = len(lines) - 1
    if extra:
        s.detail = (s.detail + "; " if s.detail else "") + f"{extra} other line{'s' if extra != 1 else ''} for this code (modifiers, revenue centers or payer-only rates)"
    return s
