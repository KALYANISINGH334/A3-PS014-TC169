import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NETPULSE_DB_PATH", str(tmp_path / "observations.sqlite3"))
    with TestClient(app) as client:
        yield client


def observation(**updates):
    payload = {"timestamp": "2026-01-01T12:00:00Z", "access_medium": "Wi-Fi", "medium_verified": True,
               "verification_source": "participant_attestation", "latency_ms": 0, "packet_loss_pct": 0}
    return payload | updates


def test_empty_store_and_round_trip(client):
    assert client.get("/measurements").json()["items"] == []
    created = client.post("/measurements", json=observation())
    assert created.status_code == 201
    assert created.json()["latency_ms"] == 0
    assert created.json()["dns_ms"] is None
    records = client.get("/measurements").json()
    assert records["total"] == 1
    assert records["items"][0] == created.json()


@pytest.mark.parametrize("updates", [
    {"packet_loss_pct": 101}, {"latency_ms": -1}, {"timestamp": "2026-01-01T12:00:00"},
    {"timestamp": "2999-01-01T12:00:00Z"}, {"access_medium": "invented"},
    {"precise_address": "should not be collected"}, {"verification_source": "unverified"},
    {"medium_verified": False}, {"status": "failed"}, {"latency_ms": None, "packet_loss_pct": None},
    {"latency_ms": "NaN"},
])
def test_malformed_payload_rejected(client, updates):
    assert client.post("/measurements", json=observation(**updates)).status_code == 422
    assert client.get("/measurements").json()["total"] == 0


def test_pagination_and_utc_order(client):
    client.post("/measurements", json=observation(timestamp="2026-01-01T13:00:00+02:00"))
    client.post("/measurements", json=observation(timestamp="2026-01-01T12:00:00Z"))
    page = client.get("/measurements?limit=1&offset=1").json()
    assert page["total"] == 2
    assert page["items"][0]["timestamp"] == "2026-01-01T11:00:00Z"
    assert client.get("/measurements?limit=0").status_code == 422


def test_storage_failure_is_actionable(client, monkeypatch):
    import sqlite3
    from backend import storage
    def fail(*args):
        raise sqlite3.OperationalError("private database details")
    monkeypatch.setattr(storage, "list_measurements", fail)
    response = client.get("/measurements")
    assert response.status_code == 503
    assert "private" not in response.text


def test_subsecond_ordering(client):
    client.post("/measurements", json=observation(timestamp="2026-01-01T12:00:00Z"))
    client.post("/measurements", json=observation(timestamp="2026-01-01T12:00:00.500000Z"))
    assert client.get("/measurements").json()["items"][0]["timestamp"] == "2026-01-01T12:00:00.500000Z"


def test_additive_migration_preserves_existing_rows(tmp_path, monkeypatch):
    import sqlite3
    path = tmp_path / 'old.sqlite3'
    monkeypatch.setenv('NETPULSE_DB_PATH', str(path))
    with sqlite3.connect(path) as conn:
        conn.execute('''CREATE TABLE measurements (id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL, access_medium TEXT NOT NULL, medium_verified INTEGER NOT NULL,
            verification_source TEXT NOT NULL, isp TEXT, location_category TEXT, status TEXT NOT NULL,
            latency_ms REAL, packet_loss_pct REAL, dns_ms REAL, throughput_mbps REAL)''')
        conn.execute("INSERT INTO measurements (timestamp,access_medium,medium_verified,verification_source,status,latency_ms) VALUES ('2026-01-01T00:00:00Z','Unknown',0,'unverified','success',14)")
    with TestClient(app) as client:
        records = client.get('/measurements').json()
        assert records['total'] == 1
        assert records['items'][0]['latency_ms'] == 14
        assert records['items'][0]['participant_id'] is None
        assert records['items'][0]['collection_errors'] == []


def test_optional_bearer_token_protects_reads_and_writes(client, monkeypatch):
    monkeypatch.setenv('NETPULSE_UPLOAD_TOKEN', 'test-only-secret')
    assert client.get('/health').status_code == 200
    assert client.get('/measurements').status_code == 401
    assert client.post('/measurements', json=observation()).status_code == 401
    headers = {'Authorization': 'Bearer test-only-secret'}
    assert client.post('/measurements', json=observation(), headers=headers).status_code == 201
    assert client.get('/measurements', headers=headers).status_code == 200
