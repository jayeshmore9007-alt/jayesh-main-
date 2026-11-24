from fastapi.testclient import TestClient
from app.main import app

def test_health():
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["ok"] is True

def test_cache_config():
    with TestClient(app) as client:
        response = client.get("/api/cache/config")
        assert response.status_code == 200
        assert response.json()["requested_ttl"] == "30m"
