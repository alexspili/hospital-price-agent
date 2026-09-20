from hpa import demo


def test_replay_needs_nothing_but_the_json():
    data = {
        "recorded_on": "2026-09-18",
        "zips": {"77339": [{"ccn": "450775", "name": "HCA Houston Healthcare Kingwood", "distance_km": 3.0, "approximate": False,
                            "steps": ["cms-hpt.txt found at https://www.hcahoustonhealthcare.com/cms-hpt.txt", "price file json, 860 MB"],
                            "ok": True, "reason": None, "mrf_url": "https://x/f.json"}]},
        "services": {"knee mri": {"service": "MRI scan of leg joint", "codes": "CPT 73721", "reviewed": False, "hospitals": [
            {"name": "HCA Houston Healthcare Kingwood", "verdict": "modifier-specific lines only", "detail": "", "lines": 50, "headline": None},
            {"name": "Elite Hospital Kingwood", "verdict": "unknown: no billing class stated", "detail": "", "lines": 1,
             "headline": {"cash": 2735.8, "gross": 5471.59, "min": 431.06, "max": 574.74, "context": "both", "ref": "row 1570", "description": "MRI"}},
        ]}},
    }
    lines = []
    demo.replay(data, out=lines.append)
    text = "\n".join(lines)
    assert "nearest 1 hospital to the centre of 77339" in text
    assert "HCA Houston Healthcare Kingwood: cms-hpt.txt found" in text
    assert "cash $2,735.80  gross $5,471.59  [both]  row 1570" in text
    assert "modifier-specific lines only" in text
