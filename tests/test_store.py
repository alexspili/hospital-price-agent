from hpa import store

ROW = ("INSERT INTO hospital_files VALUES ('450289', 'HARRIS', now() - INTERVAL {days} DAY, true, 'cms-hpt', 'example.test', "
       "NULL, NULL, NULL, 'https://example.test/f.csv', 'csv-wide', 1000, NULL, NULL, NULL, '', '[]', 1.0)")


def test_a_stale_discovery_is_still_evidence_for_a_read():
    """A live run looks again after the TTL; a read of what is stored does not throw the
    location of a file away because the discovery is old."""
    con = store.connect(":memory:")
    con.execute(ROW.format(days=40))
    assert store.cached_discovery(con, "450289") is None
    rec = store.cached_discovery(con, "450289", within_ttl=False)
    assert rec["ok"] and rec["stale"] and rec["mrf_url"] == "https://example.test/f.csv"
    con.execute(ROW.format(days=1))
    assert store.cached_discovery(con, "450289")["stale"] is False
