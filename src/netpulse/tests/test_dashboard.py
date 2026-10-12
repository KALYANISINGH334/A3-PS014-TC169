"""Streamlit interaction checks. Synthetic fixtures are isolated in temporary test databases."""
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from backend.main import app
from dashboard.api import APIClient

SCRIPT = str(Path(__file__).resolve().parents[1] / "dashboard" / "app.py")
PAGES = ["Overview", "Live Measurements", "Access Medium Comparison", "Historical Trends", "Data Quality & Methodology", "Settings & About"]


@pytest.fixture
def connected(tmp_path, monkeypatch):
    monkeypatch.setenv("NETPULSE_DB_PATH", str(tmp_path / "ui-test.sqlite3"))
    original = APIClient.__init__
    with TestClient(app) as backend:
        def route(request):
            response = backend.request(request.method, str(request.url), content=request.content, headers=dict(request.headers))
            return httpx.Response(response.status_code, content=response.content, headers=response.headers)
        def init(self, base_url=None, transport=None):
            original(self, "http://testserver", httpx.MockTransport(route))
        monkeypatch.setattr(APIClient, "__init__", init)
        yield backend


def open_app():
    return AppTest.from_file(SCRIPT, default_timeout=15).run()


def test_all_navigation_empty_database(connected):
    at = open_app()
    assert not at.exception
    assert at.metric[0].value == "0"
    for page in PAGES:
        at.radio[0].set_value(page).run()
        assert not at.exception, page
        assert at.title[0].value == page
    at.radio[0].set_value("Live Measurements").run()
    assert next(button for button in at.button if button.label == "Run Measurement").disabled


def test_offline_all_pages(monkeypatch):
    original = APIClient.__init__
    def unavailable(request):
        raise httpx.ConnectError("offline test", request=request)
    def init(self, base_url=None, transport=None):
        original(self, "http://offline.test", httpx.MockTransport(unavailable))
    monkeypatch.setattr(APIClient, "__init__", init)
    at = open_app()
    assert all(metric.value == "—" for metric in at.metric)
    for page in PAGES:
        at.radio[0].set_value(page).run()
        assert not at.exception
        assert at.error
    at.radio[0].set_value("Live Measurements").run()
    assert next(button for button in at.button if button.label == "Validate & save observation").disabled


def submit(at):
    next(button for button in at.button if button.label == "Validate & save observation").click().run()


def test_import_validation_and_success(connected):
    at = open_app()
    next(button for button in at.button if button.label == "Open measurement workspace").click().run()
    assert at.title[0].value == "Live Measurements"
    assert at.radio[0].value == "Live Measurements"
    submit(at)
    assert any("Confirm" in error.value for error in at.error)
    at.checkbox[0].check()
    at.text_input[0].set_value("invalid")
    submit(at)
    assert any("timestamp" in error.value for error in at.error)
    at.text_input[0].set_value("2026-01-01T12:00:00Z")
    at.number_input(key="input_latency_ms").set_value(12)
    submit(at)
    assert not at.exception
    assert any("saved to SQLite" in message.value for message in at.success), ([x.value for x in at.error], [x.value for x in at.success], connected.get("/measurements").json())
    result = connected.get("/measurements").json()
    assert result["total"] == 1
    assert result["items"][0]["latency_ms"] == 12
    assert result["items"][0]["dns_ms"] is None


def test_populated_charts_and_filters(connected):
    for medium, latency, timestamp in [("Wi-Fi", 20, "2026-01-01T00:00:00Z"), ("Ethernet", 10, "2026-01-02T00:00:00Z")]:
        assert connected.post("/measurements", json={
            "timestamp": timestamp, "access_medium": medium, "medium_verified": True,
            "verification_source": "participant_attestation", "latency_ms": latency,
            "packet_loss_pct": 0, "dns_ms": 5, "throughput_mbps": 40,
        }).status_code == 201
    at = open_app()
    assert not at.exception
    assert at.metric[0].value == "2"
    assert at.metric[1].value == "15.00 ms"
    at.multiselect[0].set_value(["Ethernet"]).run()
    assert at.metric[0].value == "1"
    assert at.metric[1].value == "10.00 ms"
    at.multiselect[0].set_value([]).run()
    assert at.metric[0].value == "0"
    # Date filters are inclusive and operate in UTC.
    from datetime import date
    at.multiselect[0].set_value(["Wi-Fi", "Ethernet"])
    at.date_input[0].set_value((date(2026, 1, 1), date(2026, 1, 1))).run()
    assert at.metric[0].value == "1"
    at.date_input[0].set_value((date(2026, 1, 1), date(2026, 1, 2))).run()
    for page, expected_charts in [("Access Medium Comparison", 4), ("Historical Trends", 5)]:
        at.radio[0].set_value(page).run()
        assert not at.exception
        assert len(at.get("plotly_chart")) == expected_charts
