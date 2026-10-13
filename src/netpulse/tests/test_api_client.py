import httpx
import pytest

from backend.models import MeasurementCreate
from dashboard.api import APIClient, APIError


def client(handler):
    return APIClient("http://backend.test", transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("status", [422, 500, 503])
def test_http_errors(status):
    api = client(lambda request: httpx.Response(status, json={"detail": "private debug details"}))
    with pytest.raises(APIError, match=f"HTTP {status}") as error:
        api.measurements()
    assert "private" not in str(error.value)


@pytest.mark.parametrize("exception", [httpx.ConnectError, httpx.ReadTimeout])
def test_network_errors(exception):
    def fail(request):
        raise exception("test", request=request)
    with pytest.raises(APIError):
        client(fail).health()


def test_invalid_json_and_health_contract():
    with pytest.raises(APIError, match="invalid JSON"):
        client(lambda request: httpx.Response(200, text="not JSON")).health()
    with pytest.raises(APIError, match="unexpected response"):
        client(lambda request: httpx.Response(200, json={"status": "bad"})).health()


def test_malformed_measurement_response():
    with pytest.raises(APIError, match="schema"):
        client(lambda request: httpx.Response(200, json={"items": [{}]})).measurements()


def test_real_paths_and_payload_contract():
    payload = MeasurementCreate(timestamp="2026-01-01T00:00:00Z", latency_ms=12)
    seen = []
    def handler(request):
        seen.append((request.method, request.url.path))
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.method == "POST":
            import json
            return httpx.Response(201, json=json.loads(request.content) | {"id": 1})
        return httpx.Response(200, json={"items": [], "total": 0, "limit": 5000, "offset": 0})
    api = client(handler)
    api.health()
    assert api.measurements().items == []
    assert api.create(payload).id == 1
    assert seen == [("GET", "/health"), ("GET", "/measurements"), ("POST", "/measurements")]


@pytest.mark.parametrize("url", ["file:///tmp/data", "http://name:secret@host", "http://host?token=secret", "http://host:abc", "http://[invalid"])
def test_invalid_configuration(url):
    with pytest.raises(APIError):
        APIClient(url)
