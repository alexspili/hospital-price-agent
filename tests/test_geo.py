import pytest

from hpa.geo import haversine_km


def test_same_point_is_zero():
    assert haversine_km(29.7, -95.4, 29.7, -95.4) == 0


def test_houston_to_dallas():
    # ZIP centroids 77030 (Texas Medical Center) and 75201 (downtown Dallas); 367.6 km
    # cross-checked with the spherical law of cosines.
    assert haversine_km(29.705557, -95.401754, 32.788309, -96.799572) == pytest.approx(367.6, abs=0.1)


def test_symmetric():
    a = haversine_km(29.7, -95.4, 30.2, -95.5)
    b = haversine_km(30.2, -95.5, 29.7, -95.4)
    assert a == pytest.approx(b)
