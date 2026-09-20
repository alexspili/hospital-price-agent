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
MODIFIERS_ONLY = "modifier-specific lines only"
NEGOTIATED_ONLY = "negotiated rates only, no cash or gross price"
CONFLICTING = "conflicting"
INPATIENT_ONLY = "inpatient line only"
NOT_FOUND = "not found"


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


def pairs(hospitals: list[dict]) -> list[Pair]:
    """Every pair, in the order the hospitals were given (nearest first)."""
    return [pair(a, b) for i, a in enumerate(hospitals) for b in hospitals[i + 1:]]


def apply_review(lines: list[Line], review: dict | bool, hospital: str) -> list[Line]:
    """Fill in a billing class a reviewer confirmed for this hospital's line (matched by
    source ref), marking it as coming from the review. The file's own value always wins."""
    if not review or not isinstance(review, dict):
        return lines
    answers = {h["ref"]: h["billing_class"] for h in review.get("hospitals", [])
               if h.get("hospital") == hospital and h.get("billing_class") and h.get("ref")}
    if not answers:
        return lines
    from dataclasses import replace
    return [replace(l, billing_class=answers[l.source_ref], class_from_review=True)
            if l.billing_class is None and l.source_ref in answers else l for l in lines]


def summarise(lines: list[Line]) -> Summary:
    if not lines:
        return Summary(NOT_FOUND, None, [])
    s = Summary("", None, list(lines))
    plain = [l for l in s.plain_lines if l.has_price]
    with_mods = [l for l in lines if l.modifiers is not None and l.has_price]
    if not plain and not with_mods:
        n = len(lines)
        s.verdict, s.detail = NEGOTIATED_ONLY, f"{n} line{'s' if n != 1 else ''}, each with negotiated min/max only"
        return s
    if not plain:
        mods = sorted({l.modifiers for l in with_mods})
        s.verdict, s.detail = MODIFIERS_ONLY, f"priced lines carry modifiers {', '.join(mods)}; no unmodified line to compare"
        return s
    # The 70 shoppable services are outpatient services; an inpatient-only line is a
    # different price (a hospital stay) and is reported as such, never mixed in.
    outpatient = [l for l in plain if l.setting in ("outpatient", "both", None)]
    pool = outpatient or plain
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
    else:
        s.verdict = COMPARABLE
    if not outpatient:
        s.verdict = INPATIENT_ONLY
        s.detail = "only an inpatient line is priced; outpatient comparison not possible"
    extra = len(lines) - 1
    if extra:
        s.detail = (s.detail + "; " if s.detail else "") + f"{extra} other line{'s' if extra != 1 else ''} for this code (modifiers, revenue centers or payer-only rates)"
    return s
