import io
import zipfile
from pathlib import Path

import pytest

from hpa.mrf import OffTemplate, iter_csv, open_mrf, read_json_header

FIX = Path(__file__).parent / "fixtures" / "mrf"


def charges_of(path):
    header, it = open_mrf(str(path))
    return header, list(it)


def test_csv_wide_header_and_charges():
    header, charges = charges_of(FIX / "wide_elite.csv")
    assert header.shape == "csv-wide"
    assert header.hospital_name == "23330 Emergency Center LLC"
    assert header.last_updated_on == "6/1/2026" and header.version == "3.0.0"
    assert len(charges) == 22  # 25 lines minus 3 header rows
    first = charges[0]
    assert first.description.startswith("20% Intralipid")
    assert first.codes == (("HCPCS", "INTRLIP"),)
    assert first.setting == "both"
    assert (first.gross, first.discounted_cash, first.minimum, first.maximum) == (358.8, 179.4, 269.1, 269.1)
    assert first.source_ref == "row 4"
    assert first.off_template_note is None


def test_csv_tall_dedupes_payer_rows_into_one_charge_per_context():
    header, charges = charges_of(FIX / "tall_kingwoodpines.csv")
    assert header.shape == "csv-tall"
    assert header.last_updated_on == "2026-08-31"
    # 37 payer rows in the fixture collapse to one charge per (item, context, summary values).
    assert len(charges) < 37
    inpatient = next(c for c in charges if c.description == "Inpatient - ALL")
    assert inpatient.codes == (("RC", "124"),)
    assert inpatient.gross == 2500.0 and inpatient.minimum == 650.0 and inpatient.maximum == 1244.0
    # Same item id across all rows of the item.
    assert len({c.item_id for c in charges if c.description == "Inpatient - ALL"}) == 1


def test_csv_tall_keeps_conflicting_summary_values():
    text = (
        "hospital_name,last_updated_on,version\r\nX,2026-01-01,3.0.0\r\n"
        "description,code|1,code|1|type,setting,standard_charge|gross,standard_charge|discounted_cash,payer_name,plan_name,standard_charge|min,standard_charge|max\r\n"
        "MRI,73721,CPT,outpatient,1000,500,Aetna,PPO,400,900\r\n"
        "MRI,73721,CPT,outpatient,1000,500,Cigna,HMO,400,900\r\n"
        "MRI,73721,CPT,outpatient,1200,500,Blue,PPO,400,900\r\n"
    )
    _, it = iter_csv(io.StringIO(text))
    charges = list(it)
    assert [c.gross for c in charges] == [1000.0, 1200.0]  # two distinct values, both kept
    assert charges[0].item_id == charges[1].item_id
    assert charges[0].source_ref == "row 4" and charges[1].source_ref == "row 6"


def test_non_numeric_dollar_cell_is_kept_as_note_not_coerced():
    text = (
        "hospital_name,last_updated_on,version\r\nX,2026-01-01,3.0.0\r\n"
        "description,code|1,code|1|type,setting,standard_charge|gross,standard_charge|discounted_cash,standard_charge|min,standard_charge|max\r\n"
        "Visit,99213,CPT,outpatient,N/A,60% of billed charges,,\r\n"
    )
    _, it = iter_csv(io.StringIO(text))
    c = list(it)[0]
    assert c.gross is None and c.discounted_cash is None
    assert c.off_template_note == "gross='N/A'; discounted_cash='60% of billed charges'"


def test_off_template_csv_is_reported_not_parsed():
    with pytest.raises(OffTemplate, match="row 3 is not the CMS header"):
        charges_of(FIX / "offtemplate_townsen.csv")


def test_json_with_bom_header_and_multiple_charges_per_item():
    header, charges = charges_of(FIX / "methodist_items.json")
    assert header.shape == "json"
    assert header.hospital_name == "The Methodist Hospital"
    assert header.last_updated_on == "2026-04-01" and header.version == "3.0.0"
    assert header.location_names == ("The Methodist Hospital",)
    mri = [c for c in charges if ("CPT", "73721") in c.codes]
    assert len(mri) == 2
    facility, professional = mri
    assert facility.billing_class == "facility" and facility.modifiers is None
    assert (facility.gross, facility.discounted_cash, facility.minimum, facility.maximum) == (3200.0, 1600.0, 900.0, 2500.0)
    assert professional.billing_class == "professional" and professional.modifiers == "26"
    assert professional.source_ref == "item 7/charge 2"
    assert facility.item_id == professional.item_id
    # An NDC item with two charge objects (different units in the notes) keeps both.
    fomepizole = [c for c in charges if c.description.startswith("FOMEPIZOLE") and ("NDC", "00517071001") in c.codes]
    assert [c.gross for c in fomepizole] == [15772.0, 7728.5]


def test_json_without_the_array_is_off_template(tmp_path):
    p = tmp_path / "x.json"
    p.write_text('{"hospital_name": "X", "version": "3.0.0"}')
    header, it = open_mrf(str(p))
    with pytest.raises(OffTemplate, match="no standard_charge_information"):
        list(it)


def test_zip_opens_the_largest_csv_member(tmp_path):
    p = tmp_path / "x.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("readme.txt", "hi")
        z.writestr("123_x_standardcharges.csv", (FIX / "wide_elite.csv").read_text())
    header, charges = charges_of(p)
    assert header.shape == "csv-wide" and len(charges) == 22


def test_json_header_from_prefix_only():
    h = read_json_header(b'\xef\xbb\xbf{"hospital_name":"A","last_updated_on":"2026-02-28","version":"3.0.0","location_name": ["A","A ER"],"x":1')
    assert h.hospital_name == "A" and h.location_names == ("A", "A ER") and h.shape == "json"
