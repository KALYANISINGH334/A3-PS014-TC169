from datetime import date

import pytest

from dashboard.analytics import comparisons, filter_frame, summaries, to_frame
from dashboard.charts import comparison_chart, distribution_chart, history_chart


def rows():
    return [
        {"id": 1, "timestamp": "2026-01-01T12:00:00Z", "access_medium": "Wi-Fi", "medium_verified": True, "status": "success", "latency_ms": 0, "packet_loss_pct": 0},
        {"id": 2, "timestamp": "2026-01-02T12:00:00Z", "access_medium": "Wi-Fi", "medium_verified": True, "status": "partial", "latency_ms": 20},
        {"id": 3, "timestamp": "2026-01-02T13:00:00Z", "access_medium": "Ethernet", "medium_verified": False, "status": "success", "latency_ms": 100},
        {"id": 4, "timestamp": "2026-01-02T14:00:00Z", "access_medium": "Wi-Fi", "medium_verified": True, "status": "failed", "latency_ms": 999},
    ]


def test_medians_missing_and_zero():
    stats = summaries(to_frame(rows()))
    assert stats["latency_ms"] == {"median": 20.0, "count": 3}
    assert stats["packet_loss_pct"] == {"median": 0.0, "count": 1}
    assert stats["dns_ms"] == {"median": None, "count": 0}
    assert summaries(to_frame([]))["latency_ms"]["median"] is None


def test_comparisons_exclude_unverified_and_failed():
    groups = comparisons(to_frame(rows()))
    assert groups.access_medium.tolist() == ["Wi-Fi"]
    assert groups.iloc[0].latency_ms == 10
    assert groups.iloc[0].observations == 2
    assert groups.iloc[0].packet_loss_pct_n == 1
    assert groups.iloc[0].dns_ms_n == 0
    assert comparisons(to_frame([])).empty


def test_date_and_medium_filters():
    frame = to_frame(rows())
    filtered = filter_frame(frame, date(2026, 1, 2), date(2026, 1, 2), ["Wi-Fi"], True)
    assert filtered.id.tolist() == [2, 4]
    assert filter_frame(frame, mediums=[]).empty


def test_nonfinite_values_are_missing():
    frame = to_frame([rows()[0] | {"latency_ms": float("inf")}])
    assert summaries(frame)["latency_ms"]["median"] is None


@pytest.mark.parametrize("key", ["latency_ms", "packet_loss_pct", "dns_ms", "throughput_mbps"])
def test_figures_keep_metric_units(key):
    frame = to_frame(rows())
    chart = history_chart(frame, key)
    assert "UTC" in chart.layout.xaxis.title.text
    groups = comparisons(frame)
    comparison = comparison_chart(groups, key)
    assert comparison.layout.yaxis.title.text
    assert distribution_chart(frame).layout.yaxis.title.text == "Observation count"
