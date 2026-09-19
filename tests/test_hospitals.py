from pathlib import Path

import pytest

from hpa import store
from hpa.geo import load_zcta
from hpa.hospitals import UnknownZip, find_hospitals, load_hospitals, location_counts

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def con():
    con = store.connect(":memory:")
    load_zcta(con, str(FIXTURES / "zcta.txt"))
    load_hospitals(con, str(FIXTURES / "hospitals.csv"), str(FIXTURES / "coords.csv"))
    return con


def names(hospitals):
    return [h.name for h in hospitals]


def by_ccn(hospitals, ccn):
    return next(h for h in hospitals if h.ccn == ccn)


def test_nearest_first_and_limited(con):
    found = find_hospitals(con, "77380")
    assert len(found) == 5
    assert "WOODLANDS" in names(found)[0]
    assert "HOUSTON METHODIST THE WOODLANDS HOSPITAL" in names(found)
    assert [h.distance_km for h in found] == sorted(h.distance_km for h in found)


def test_limit_keeps_only_the_nearest(con):
    assert len(find_hospitals(con, "77030", limit=2)) == 2


def test_geocoded_hospitals_in_one_zip_get_distinct_distances(con):
    # Both are in 77030; with ZIP centroids they would tie at 0.0.
    found = find_hospitals(con, "77030", limit=3)
    harris, hermann = by_ccn(found, "450289"), by_ccn(found, "450068")
    assert harris.location_source == hermann.location_source == "address"
    assert harris.geocode_match == "Exact" and hermann.geocode_match == "Non_Exact"
    assert harris.distance_km != hermann.distance_km


def test_kingwood_po_box_zip_is_placed_by_street_address(con):
    # 77325 is a PO-box ZIP with no census centroid, so the geocode can't be checked
    # against it and is accepted. Picking the numerically nearest ZIP (77326) would have
    # put this hospital 40 miles away.
    found = find_hospitals(con, "77339", limit=1)
    assert found[0].ccn == "450775"
    assert found[0].distance_km < 5


def test_geocode_far_from_own_zip_is_rejected(con):
    # Altus Houston (Alief, 77072) was geocoded Non_Exact to the east side of the city,
    # 42 km away. It must fall back to its ZIP and not appear as nearest to 77049.
    altus = by_ccn(find_hospitals(con, "77072", limit=1), "670135")
    assert altus.location_source == "zip"
    assert altus.geocode_match is None
    assert altus.location_note == "Non_Exact geocode rejected: 42 km from the 77072 centroid"
    assert all(h.ccn != "670135" for h in find_hospitals(con, "77049", limit=1))


def test_zip_centroid_distance_is_an_upper_bound(con):
    # 670122 has a freeway address the Census geocoder cannot match. It's in the query
    # ZIP, so the bound is the ZIP's own radius (4.2 km), not a misleading 0.0.
    methodist = by_ccn(find_hospitals(con, "77385", limit=3), "670122")
    assert methodist.location_source == "zip"
    assert methodist.distance_is_bound
    assert methodist.distance_km == pytest.approx(4.2, abs=0.1)


def test_unresolved_hospital_is_excluded_and_counted(con):
    # 999999 has no geocode and a PO-box ZIP with no centroid.
    assert all(h.ccn != "999999" for h in find_hospitals(con, "77386", limit=100))
    assert location_counts(con) == {"address": 9, "zip": 2, "unresolved": 1}


def test_federal_hospitals_excluded_by_default(con):
    assert "HOUSTON VA MEDICAL CENTER" not in names(find_hospitals(con, "77030", 3))
    assert "HOUSTON VA MEDICAL CENTER" in names(find_hospitals(con, "77030", 3, include_federal=True))


def test_ccn_keeps_letters_and_leading_zeros(con):
    va = by_ccn(find_hospitals(con, "77030", 3, include_federal=True), "45074F")
    assert va.ccn == "45074F"


def test_works_without_geocoded_coordinates():
    con = store.connect(":memory:")
    load_zcta(con, str(FIXTURES / "zcta.txt"))
    load_hospitals(con, str(FIXTURES / "hospitals.csv"))
    assert location_counts(con)["address"] == 0
    assert all(h.location_source == "zip" for h in find_hospitals(con, "77030"))


@pytest.mark.parametrize("limit", [0, -1])
def test_nonpositive_limit_rejected(con, limit):
    with pytest.raises(ValueError):
        find_hospitals(con, "77030", limit=limit)


def test_unknown_zip_raises(con):
    with pytest.raises(UnknownZip):
        find_hospitals(con, "00000")
