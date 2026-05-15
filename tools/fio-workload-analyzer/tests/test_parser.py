"""Unit tests for the FIO JSON parser."""
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.log_parser import parse_fio_json

_SAMPLE = {
    "jobs": [{
        "read": {
            "iops": 125000.0, "iops_stddev": 1200.0,
            "bw": 500000, "bw_dev": 5000,
            "lat_ns": {"mean": 200000, "stddev": 15000, "min": 50000, "max": 5000000},
            "clat_ns": {
                "percentile": {
                    "50.000000": 180000, "90.000000": 280000, "95.000000": 350000,
                    "99.000000": 600000, "99.900000": 2000000, "99.990000": 4000000,
                }
            },
            "total_ios": 7500000, "io_bytes": 30720000000,
        },
        "write": {
            "iops": 0.0, "iops_stddev": 0.0,
            "bw": 0, "bw_dev": 0,
            "lat_ns": {"mean": 0, "stddev": 0, "min": 0, "max": 0},
            "clat_ns": {"percentile": {}},
            "total_ios": 0, "io_bytes": 0,
        },
        "usr_cpu": 8.2, "sys_cpu": 2.1, "ctx": 55000,
    }]
}


def test_parse_basic():
    r = parse_fio_json(json.dumps(_SAMPLE), job_id=1)
    assert r is not None
    assert r.job_id == 1
    assert abs(r.read_iops - 125000.0) < 1
    assert r.read_bw_kbps == 500000
    assert r.read_clat_p50_ns == 180000
    assert r.read_clat_p99_ns == 600000
    assert r.read_clat_p9999_ns == 4000000
    assert r.write_iops == 0.0


def test_derived_metrics():
    r = parse_fio_json(json.dumps(_SAMPLE), job_id=1)
    # P99.9 / P50 = 2000000 / 180000 ≈ 11.1
    assert r.lat_tail_ratio is not None
    assert r.lat_tail_ratio > 10


def test_invalid_json():
    r = parse_fio_json("not json", job_id=1)
    assert r is None


def test_empty_jobs():
    r = parse_fio_json(json.dumps({"jobs": []}), job_id=1)
    assert r is None


if __name__ == "__main__":
    test_parse_basic()
    test_derived_metrics()
    test_invalid_json()
    test_empty_jobs()
    print("All tests passed.")
