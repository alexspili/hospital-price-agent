from pathlib import Path

import pytest

from hpa import store
from hpa.geo import load_zcta
from hpa.hospitals import UnknownZip, find_hospitals, load_hospitals

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def con():
    con = store.connect(":memory:")
    load_zcta(con, str(FIXTURES / "zcta.txt"))
    load_hospitals(con, str(FIXTURES / "hospitals.csv"))
    return con


def names(hospitals):
    return [h.name for h in hospitals]


def test_woodlands_hospitals_nearest_first(con):
    found = find_hospitals(con, "77380", radius_km=15)
    assert names(found)[0] == "HOUSTON METHODIST THE WOODLANDS HOSPITAL"  # 77385, 6.7 km
    assert "THE WOODLANDS SPECIALTY HOSPITAL" in names(found)  # 77386, 11.5 km
    assert all(h.distance_km <= 15 for h in found)
    assert [h.distance_km for h in found] == sorted(h.distance_km for h in found)


def test_radius_excludes_far_hospitals(con):
    near_tmc = names(find_hospitals(con, "77030", radius_km=10))
    assert "MEMORIAL HERMANN - TEXAS MEDICAL CENTER" in near_tmc
    assert "ST LUKE'S THE WOODLANDS HOSPITAL" not in near_tmc


def test_federal_hospitals_excluded_by_default(con):
    assert "HOUSTON VA MEDICAL CENTER" not in names(find_hospitals(con, "77030", 5))
    assert "HOUSTON VA MEDICAL CENTER" in names(find_hospitals(con, "77030", 5, types=None))


def test_ccn_keeps_letters_and_leading_zeros(con):
    va = next(h for h in find_hospitals(con, "77030", 5, types=None) if "VA" in h.name)
    assert va.ccn == "45074F"


def test_po_box_zip_falls_back_to_nearest_zip_in_prefix(con):
    # 77387 has no census centroid; the nearest ZIP in the 773 prefix is 77386.
    po_box = next(h for h in find_hospitals(con, "77386", 1) if h.ccn == "999999")
    assert po_box.location_approx
    assert po_box.distance_km == 0


def test_unmatched_hospital_without_any_nearby_zip_is_skipped(con):
    # Parmer County's 790 prefix has no ZIPs in the fixture, so it has no coordinate.
    assert all(h.ccn != "451300" for h in find_hospitals(con, "77030", 5000))


def test_unknown_zip_raises(con):
    with pytest.raises(UnknownZip):
        find_hospitals(con, "00000")
