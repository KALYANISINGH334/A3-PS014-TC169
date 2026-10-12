"""Demo fixtures never enter live storage; UI switching and aggregates are explicit."""
from datetime import date

import pytest

from backend.models import MeasurementCreate
from dashboard.analytics import comparisons, daily_summary, completeness, filter_frame, to_frame
from dashboard.charts import box_chart, count_chart, completeness_chart, daily_chart
from dashboard.demo_data import DEMO_LABEL, generate_demo_records
from tests.test_dashboard import connected, open_app, PAGES


def test_reproducible_schema_and_missing_values():
    records = generate_demo_records()
    assert records == generate_demo_records()
    assert len(records) == 420
    for record in records:
        MeasurementCreate.model_validate({k: v for k, v in record.items() if k != 'id'})
    frame = to_frame(records)
    assert frame.participant_id.nunique() == 12
    assert frame.timestamp.dt.date.nunique() == 7
    assert set(frame.access_medium) == {'Wi-Fi', 'Ethernet', 'Cellular'}
    assert not frame.medium_verified.any()
    assert frame.throughput_mbps.isna().any()
    assert frame.packet_loss_pct.eq(0).any()
    assert comparisons(frame).empty  # fictional labels are never real verified labels
    groups = comparisons(frame, illustrative=True)
    assert groups.observations.sum() == 420
    assert groups.participants.tolist() == [4, 4, 4]
    assert groups.missing_any_pct.gt(0).all()


def test_daily_aggregation_and_coverage():
    frame = to_frame(generate_demo_records())
    day = filter_frame(frame, date(2026, 1, 5), date(2026, 1, 5), ['Wi-Fi'])
    summary = daily_summary(day, 'latency_ms')
    assert len(summary) == 1
    assert summary.iloc[0]['median'] == pytest.approx(day.latency_ms.median())
    assert summary.iloc[0]['count'] == day.latency_ms.count()
    coverage = completeness(frame)
    assert (coverage.Available + coverage['Missing / failed']).eq(420).all()
    for chart in [box_chart(frame, 'latency_ms'), count_chart(frame), count_chart(frame, True), completeness_chart(frame), daily_chart(frame, 'packet_loss_pct')]:
        assert chart.data
    assert daily_summary(to_frame([]), 'dns_ms').empty


def test_mode_switch_leaves_backend_empty(connected):
    at = open_app()
    assert at.metric[0].value == '0'
    at.toggle(key='demo_mode').set_value(True).run()
    assert not at.exception
    assert at.metric[0].value == '420'
    assert at.metric[5].value == '12'
    assert any(DEMO_LABEL in item.value for item in at.warning)
    assert len(at.get('plotly_chart')) == 8
    for page in PAGES:
        at.radio[0].set_value(page).run()
        assert not at.exception, page
        assert any(DEMO_LABEL in item.value for item in at.warning)
    at.radio[0].set_value('Live Measurements').run()
    assert not any(button.label == 'Validate & save observation' for button in at.button)
    assert connected.get('/measurements').json()['total'] == 0
    at.radio[0].set_value('Overview').run()
    at.multiselect[0].set_value(['Wi-Fi']).run()
    assert at.metric[0].value == '140'
    at.toggle(key='demo_mode').set_value(False).run()
    assert not at.exception
    assert at.metric[0].value == '0'
    assert connected.get('/measurements').json()['total'] == 0


def test_demo_works_offline(monkeypatch):
    from dashboard.api import APIClient, APIError
    monkeypatch.setattr(APIClient, 'health', lambda self: (_ for _ in ()).throw(APIError('Offline')))
    monkeypatch.setattr(APIClient, 'measurements', lambda self: (_ for _ in ()).throw(APIError('Offline')))
    at = open_app()
    at.toggle(key='demo_mode').set_value(True).run()
    assert not at.exception
    assert at.metric[0].value == '420'
    assert at.error  # health remains honest even in demo mode


def test_existing_real_record_not_mixed_or_changed(connected):
    payload = {'timestamp': '2026-01-01T12:00:00Z', 'latency_ms': 987,
               'access_medium': 'Wi-Fi', 'medium_verified': True,
               'verification_source': 'participant_attestation'}
    assert connected.post('/measurements', json=payload).status_code == 201
    before = connected.get('/measurements').json()
    at = open_app()
    assert at.metric[0].value == '1'
    assert at.metric[1].value == '987.00 ms'
    at.toggle(key='demo_mode').set_value(True).run()
    assert not at.exception
    assert at.metric[0].value == '420'
    assert at.metric[1].value != '987.00 ms'
    at.radio[0].set_value('Access Medium Comparison').run()
    assert not at.exception
    assert any('cannot establish real-world superiority' in item.value for item in at.markdown)
    at.radio[0].set_value('Overview').run()
    at.toggle(key='demo_mode').set_value(False).run()
    assert at.metric[0].value == '1'
    assert at.metric[1].value == '987.00 ms'
    assert connected.get('/measurements').json() == before
