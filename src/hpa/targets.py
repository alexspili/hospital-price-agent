"""Which hospitals a command works on: the nearest to some ZIPs, or one CCN, each paired
with its cached discovery result (or None)."""

from hpa import store
from hpa.hospitals import UnknownZip, find_hospitals, hospital_by_ccn


def located(con, zips, ccn, limit):
    hospitals = {}
    for z in zips or []:
        for h in find_hospitals(con, z, limit):
            hospitals.setdefault(h.ccn, h)
    if ccn:
        h = hospital_by_ccn(con, ccn)
        if h is None:
            raise UnknownZip(f"no hospital with CCN {ccn}")
        hospitals[ccn] = h
    return [(h, store.cached_discovery(con, h.ccn)) for h in hospitals.values()]
