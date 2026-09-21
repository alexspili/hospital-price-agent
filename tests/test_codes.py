from hpa import codes


def test_a_revenue_code_is_named_by_its_series_with_or_without_the_leading_zero():
    assert codes.revenue_code("360") == "Revenue code 0360: operating room services (general)"
    assert codes.revenue_code("0360") == codes.revenue_code("360")
    assert codes.revenue_code("369") == "Revenue code 0369: operating room services (other)"
    assert codes.revenue_code("0361") == "Revenue code 0361: operating room services: minor surgery"
    assert codes.revenue_code("278") == "Revenue code 0278: medical and surgical supplies and devices"
    assert codes.revenue_code("750") == "Revenue code 0750: gastro-intestinal services, general"
    assert codes.revenue_code("0636") == "Revenue code 0636: pharmacy: drugs requiring detailed coding"
    assert codes.revenue_code("9999") == "Revenue code 9999"  # not a known series: no invented name
    assert codes.revenue_code("36") is None


def test_every_code_type_a_file_uses_is_explained_and_nothing_else_is_invented():
    for t in ("CPT", "HCPCS", "MS-DRG", "APR-DRG", "TRIS-DRG", "DRG", "RC", "CDM", "NDC", "APC", "HIPPS", "ICD", "LOCAL"):
        assert codes.explain(f"{t} 360"), t
    assert codes.explain("RC 360").startswith("Revenue code 0360")
    assert codes.explain("CPT 45378").startswith("CPT:")
    assert codes.explain("MADEUP 12") is None
    assert codes.explain_all(["CPT 45378", "RC 360", "MADEUP 1"]).keys() == {"CPT 45378", "RC 360"}
