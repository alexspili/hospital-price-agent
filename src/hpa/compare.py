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

    @property
    def has_price(self) -> bool:
        return self.discounted_cash is not None or self.gross is not None

    @property
    def context(self) -> str:
        parts = [self.setting, self.billing_class, f"mod {self.modifiers}" if self.modifiers else None]
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
        s.detail = f"{len(pool)} unmodified lines disagree (cash {sorted(cash)})" if len(cash) > 1 else f"{len(pool)} unmodified lines disagree (gross {sorted(gross)})"
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
