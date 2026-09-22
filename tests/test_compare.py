from hpa.compare import (
    COMPARABLE,
    CONFLICTING,
    INPATIENT_ONLY,
    MODIFIERS_ONLY,
    NEGOTIATED_ONLY,
    NOT_FOUND,
    UNKNOWN_CLASS,
    Line,
    summarise,
)


def line(**kw):
    base = dict(code_type="CPT", code="73721", other_codes=(), description="MRI", setting="outpatient",
                billing_class=None, modifiers=None, gross=None, discounted_cash=None, minimum=None, maximum=None, source_ref="row 1")
    base.update(kw)
    return Line(**base)


def test_nothing_found():
    assert summarise([]).verdict == NOT_FOUND


def test_one_clean_facility_line_is_comparable():
    s = summarise([line(billing_class="facility", gross=3200.0, discounted_cash=1600.0, minimum=900.0, maximum=2500.0)])
    assert s.verdict == COMPARABLE and s.headline.discounted_cash == 1600.0


def test_missing_billing_class_is_unknown_not_a_match():
    s = summarise([line(gross=5471.59, discounted_cash=2735.80)])
    assert s.verdict == UNKNOWN_CLASS and s.headline.discounted_cash == 2735.80


def test_hca_shape_modifier_lines_plus_payer_only_lines():
    payer_only = [line(other_codes=(f"RC {rc}",), minimum=215.06, maximum=215.06, source_ref=f"item {i}") for i, rc in enumerate((730, 343, 400))]
    mods = [line(other_codes=("CDM 434377",), modifiers="50", gross=32963.0, discounted_cash=32963.0),
            line(other_codes=("CDM 761039",), modifiers="RT", gross=19633.57, discounted_cash=19633.57)]
    s = summarise(payer_only + mods)
    assert s.verdict == MODIFIERS_ONLY and s.headline is None
    assert "50, RT" in s.detail


def test_only_payer_rates_is_negotiated_only():
    s = summarise([line(minimum=344.93, maximum=4690.0), line(minimum=4255.0, maximum=4255.0)])
    assert s.verdict == NEGOTIATED_ONLY and "2 lines" in s.detail


def test_two_unmodified_lines_with_different_cash_is_conflicting():
    s = summarise([line(billing_class="facility", discounted_cash=1000.0), line(billing_class="facility", discounted_cash=1200.0)])
    assert s.verdict == CONFLICTING and s.headline is None


def test_outpatient_line_preferred_over_inpatient():
    s = summarise([line(setting="inpatient", billing_class="facility", gross=4738.0, discounted_cash=3174.46),
                   line(setting="outpatient", billing_class="facility", gross=2000.0, discounted_cash=1340.0)])
    assert s.verdict == COMPARABLE and s.headline.setting == "outpatient"


def test_inpatient_only_is_its_own_verdict():
    s = summarise([line(setting="inpatient", billing_class="facility", gross=4738.0, discounted_cash=3174.46)])
    assert s.verdict == INPATIENT_ONLY and s.headline.discounted_cash == 3174.46


def test_professional_line_does_not_become_the_headline():
    s = summarise([line(billing_class="facility", gross=3200.0, discounted_cash=1600.0),
                   line(billing_class="professional", modifiers="26", gross=450.0, discounted_cash=225.0)])
    assert s.verdict == COMPARABLE and s.headline.billing_class == "facility"
    assert "1 other line" in s.detail


def test_review_supplies_billing_class_without_overriding_the_file():
    from hpa.compare import apply_review
    review = {"hospitals": [{"hospital": "Harris Health", "billing_class": "facility", "ref": "row 33175"},
                            {"hospital": "Harris Health", "billing_class": "professional", "ref": "row 1"}]}
    lines = [line(source_ref="row 33175", gross=3821.0, discounted_cash=231.94),
             line(source_ref="row 1", billing_class="facility", gross=1.0),  # the file said facility; review must not override
             line(source_ref="row 2", gross=5.0)]
    out = apply_review(lines, review, "Harris Health")
    assert out[0].billing_class == "facility" and out[0].class_from_review and out[0].context == "outpatient, facility (per review)"
    assert out[1].billing_class == "facility" and not out[1].class_from_review
    assert out[2].billing_class is None
    assert apply_review(lines, False, "Harris Health") == lines
    assert apply_review(lines, review, "Someone Else") == lines


# --- a verdict on every pair, not only on every hospital (SPEC step 6) -------------------

from hpa import compare  # noqa: E402 - the pair helpers, alongside the names imported above

def priced(name, setting="outpatient", billing_class="facility", modifiers=None):
    return {"name": name, "headline": {"setting": setting, "billing_class": billing_class, "modifiers": modifiers}}


def test_matching_context_is_comparable():
    p = compare.pair(priced("Methodist"), priced("Baylor"))
    assert p.verdict == compare.COMPARABLE and p.detail == "outpatient, facility, no modifiers"


def test_a_missing_context_is_unknown_never_a_match():
    p = compare.pair(priced("Methodist"), priced("Harris", billing_class=None))
    assert p.verdict == compare.UNKNOWN_PAIR and "Harris's row has no billing class" in p.detail
    # Two missing values are not a match either.
    both = compare.pair(priced("A", billing_class=None), priced("B", billing_class=None))
    assert both.verdict == compare.UNKNOWN_PAIR


def test_different_context_says_why_it_cannot_be_compared():
    p = compare.pair(priced("Methodist"), priced("HCA", setting="inpatient", billing_class="professional"))
    assert p.verdict == compare.NOT_COMPARABLE
    assert "outpatient vs inpatient" in p.detail and "facility vs professional charge" in p.detail


def test_a_charge_that_applies_to_both_settings_sits_beside_either():
    p = compare.pair(priced("Methodist", setting="both"), priced("Baylor", setting="outpatient"))
    assert p.verdict == compare.COMPARABLE


def test_a_hospital_with_no_price_is_unknown_not_excluded():
    p = compare.pair(priced("Methodist"), {"name": "Orthopedic", "headline": None})
    assert p.verdict == compare.UNKNOWN_PAIR and "no priced line" in p.detail


def test_every_pair_appears_once():
    names = [priced(n) for n in ("A", "B", "C", "D")]
    got = [(p.a, p.b) for p in compare.pairs(names)]
    assert got == [("A", "B"), ("A", "C"), ("A", "D"), ("B", "C"), ("B", "D"), ("C", "D")]


# --- what the review pointed out: verdicts must not promise more than was checked ---------

def test_a_priced_professional_line_alone_is_not_called_negotiated_only():
    from hpa.compare import PROFESSIONAL_ONLY
    s = summarise([line(billing_class="professional", gross=450.0, discounted_cash=225.0)])
    assert s.verdict == PROFESSIONAL_ONLY and s.headline is None
    assert "professional" in s.detail and "negotiated" not in s.detail


def test_a_line_with_no_setting_is_unknown_on_the_card_as_it_is_in_the_pair():
    from hpa.compare import UNKNOWN_SETTING
    s = summarise([line(setting=None, billing_class="facility", gross=100.0, discounted_cash=50.0)])
    assert s.verdict == UNKNOWN_SETTING and s.headline.discounted_cash == 50.0


def test_two_codes_of_one_entry_are_not_the_same_service():
    a = {"name": "A", "headline": {"code_type": "CPT", "code": "84153", "setting": "outpatient", "billing_class": "facility", "modifiers": None}}
    b = {"name": "B", "headline": {"code_type": "CPT", "code": "84154", "setting": "outpatient", "billing_class": "facility", "modifiers": None}}
    p = compare.pair(a, b)
    assert p.verdict == compare.NOT_COMPARABLE and "84153 vs CPT 84154" in p.detail
    b["headline"]["code"] = "84153"
    assert compare.pair(a, b).verdict == compare.COMPARABLE
    # The same code under the two labels files use for it is the same code.
    b["headline"]["code_type"] = "HCPCS"
    assert compare.pair(a, b).verdict == compare.COMPARABLE
    b["headline"].update(code_type="MS-DRG", code="84153")
    assert compare.pair(a, b).verdict == compare.NOT_COMPARABLE


def test_a_review_is_bound_to_the_line_it_looked_at():
    from hpa.compare import apply_review
    review = {"hospitals": [
        {"hospital": "Harris Health", "billing_class": "facility", "ref": "row 1", "description": "MRI  Lower Extremity Joint", "headline_is_this_service": "yes"},
        {"hospital": "Harris Health", "billing_class": "facility", "ref": "row 2", "description": "CT HEAD", "headline_is_this_service": "no"},
    ]}
    lines = [line(source_ref="row 1", description="mri lower extremity joint", gross=1.0),  # same line, spacing and case aside
             line(source_ref="row 2", description="CT HEAD", gross=2.0)]
    out = apply_review(lines, review, "Harris Health")
    assert out[0].billing_class == "facility" and out[0].class_from_review
    assert out[1].billing_class is None  # the reviewer did not confirm this one
    # The file was reordered: row 1 is now something else, and the review does not follow the ref.
    moved = [line(source_ref="row 1", description="CT HEAD", gross=1.0)]
    assert apply_review(moved, review, "Harris Health")[0].billing_class is None


def test_a_drg_service_is_priced_as_a_stay_so_inpatient_is_the_line_that_counts():
    from hpa.compare import OUTPATIENT_ONLY, expected_setting
    assert expected_setting((("MS-DRG", "470"),)) == "inpatient"
    assert expected_setting((("CPT", "73721"),)) == "outpatient"
    stay = line(setting="inpatient", billing_class="facility", gross=60000.0, discounted_cash=30000.0)
    clinic = line(setting="outpatient", billing_class="facility", gross=500.0, discounted_cash=250.0)
    s = summarise([stay, clinic], setting="inpatient")
    assert s.verdict == COMPARABLE and s.headline is stay
    s = summarise([clinic], setting="inpatient")
    assert s.verdict == OUTPATIENT_ONLY and "priced as inpatient" in s.detail
    s = summarise([stay], setting="outpatient")
    assert s.verdict == INPATIENT_ONLY and "priced as outpatient" in s.detail


def test_agreeing_cash_with_differing_gross_says_so():
    s = summarise([line(billing_class="facility", gross=2460.0, discounted_cash=1230.0, source_ref="row 1"),
                   line(billing_class="facility", gross=2500.0, discounted_cash=1230.0, source_ref="row 2")])
    assert s.verdict == COMPARABLE
    assert "cash agrees; gross charges differ ($2,460.00, $2,500.00)" in s.detail


def test_unpriced_hospitals_are_named_once_and_kept_out_of_the_pairs():
    hs = [priced("A"), {"name": "B", "headline": None}, priced("C"), {"name": "D", "headline": None}]
    ps, unpriced = compare.priced_pairs(hs)
    assert unpriced == ["B", "D"]
    assert [(p.a, p.b) for p in ps] == [("A", "C")] and ps[0].verdict == compare.COMPARABLE
