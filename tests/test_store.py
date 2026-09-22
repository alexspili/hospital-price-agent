from hpa import store

ROW = ("INSERT INTO hospital_files VALUES ('450289', 'HARRIS', now() - INTERVAL {days} DAY, true, 'cms-hpt', 'example.test', "
       "NULL, NULL, NULL, 'https://example.test/f.csv', 'csv-wide', 1000, NULL, NULL, NULL, '', '[]', 1.0, NULL)")


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


def test_a_failure_from_an_older_discovery_is_looked_at_again():
    con = store.connect(":memory:")
    con.execute("INSERT INTO hospital_files (ccn, name, discovered_at, ok, method, reason, steps, seconds, discovery_version) "
                "VALUES ('450867', 'SETON', now(), false, 'failed', 'no index', '[]', 1.0, '1')")
    assert store.cached_discovery(con, "450867") is None  # discovery learned something since
    con.execute("UPDATE hospital_files SET discovery_version = ?", [store.DISCOVERY_VERSION])
    assert store.cached_discovery(con, "450867")["ok"] is False  # the same failure by today's discovery is cached
