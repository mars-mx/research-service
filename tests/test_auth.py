"""API key validation tests."""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from src.auth.dependencies import require_api_key
from src.config import Settings, get_settings

API_KEY = "test-secret-key"


def _make_app() -> FastAPI:
    app = FastAPI()

    def _override_settings() -> Settings:
        return Settings(api_key=API_KEY)  # type: ignore[call-arg]

    app.dependency_overrides[get_settings] = _override_settings

    @app.get("/protected")
    async def protected(key: str = Depends(require_api_key)):
        return {"status": "ok"}

    @app.get("/health")
    async def health():
        return {"status": "healthy"}

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_make_app())


class TestApiKeyAuth:
    def test_valid_key(self, client: TestClient) -> None:
        resp = client.get("/protected", headers={"X-API-Key": API_KEY})
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_missing_key(self, client: TestClient) -> None:
        resp = client.get("/protected")
        assert resp.status_code == 401

    def test_wrong_key(self, client: TestClient) -> None:
        resp = client.get("/protected", headers={"X-API-Key": "wrong-key"})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid API key"

    def test_empty_key(self, client: TestClient) -> None:
        resp = client.get("/protected", headers={"X-API-Key": ""})
        assert resp.status_code == 401

    def test_health_no_auth(self, client: TestClient) -> None:
        """Health endpoint should not require auth."""
        resp = client.get("/health")
        assert resp.status_code == 200
