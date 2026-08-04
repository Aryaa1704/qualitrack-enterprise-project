from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "QualiTrack"}


def test_home_page_renders() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Track inspections" in response.text


def test_openapi_schema_includes_health_and_auth_endpoints() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/health" in paths
    assert "/auth/register" in paths
    assert "/auth/login" in paths
    assert "/auth/me" in paths
    assert "/auth/logout" in paths


def test_register_login_me_and_profile_flow() -> None:
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")

    unique = uuid4().hex[:8]
    username = f"inspector_{unique}"
    email = f"inspector_{unique}@example.com"

    with TestClient(app) as auth_client:
        anonymous_profile = auth_client.get("/auth/profile", follow_redirects=False)
        assert anonymous_profile.status_code == 303
        assert anonymous_profile.headers["location"] == "/auth/login"

        register_response = auth_client.post(
            "/auth/register",
            data={"username": username, "email": email, "password": "securepass123"},
        )
        assert register_response.status_code == 201
        assert register_response.json()["username"] == username

        login_response = auth_client.post(
            "/auth/login",
            data={"username": username, "password": "securepass123"},
        )
        assert login_response.status_code == 200
        assert login_response.json()["access_token"]
        assert "access_token" in auth_client.cookies

        me_response = auth_client.get("/auth/me")
        assert me_response.status_code == 200
        assert me_response.json()["email"] == email

        profile_response = auth_client.get("/auth/profile")
        assert profile_response.status_code == 200
        assert username in profile_response.text
