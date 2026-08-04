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


def test_openapi_schema_includes_health_auth_and_factory_endpoints() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/health" in paths
    assert "/auth/register" in paths
    assert "/auth/login" in paths
    assert "/auth/me" in paths
    assert "/auth/logout" in paths
    assert "/factories" in paths
    assert "/factories/{factory_id}" in paths
    assert "post" in paths["/factories"]
    assert "get" in paths["/factories"]
    assert "get" in paths["/factories/{factory_id}"]
    assert "put" in paths["/factories/{factory_id}"]
    assert "delete" in paths["/factories/{factory_id}"]


def _authenticated_client() -> TestClient:
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")

    unique = uuid4().hex[:8]
    username = f"inspector_{unique}"
    email = f"inspector_{unique}@gmail.com"
    auth_client = TestClient(app)
    register_response = auth_client.post(
        "/auth/register",
        data={"username": username, "email": email, "password": "securepass123"},
    )
    assert register_response.status_code == 201

    login_response = auth_client.post(
        "/auth/login",
        data={"username": username, "password": "securepass123"},
    )
    assert login_response.status_code == 200
    assert "access_token" in auth_client.cookies
    return auth_client


def test_register_login_me_and_profile_flow() -> None:
    auth_client = _authenticated_client()

    anonymous_profile = client.get("/auth/profile", follow_redirects=False)
    assert anonymous_profile.status_code == 303
    assert anonymous_profile.headers["location"] == "/auth/login"

    me_response = auth_client.get("/auth/me")
    assert me_response.status_code == 200

    profile_response = auth_client.get("/auth/profile")
    assert profile_response.status_code == 200
    assert me_response.json()["username"] in profile_response.text


def test_factory_crud_api_and_protection() -> None:
    auth_client = _authenticated_client()

    unauthenticated_response = client.get("/factories")
    assert unauthenticated_response.status_code == 401

    unique = uuid4().hex[:8]
    create_response = auth_client.post(
        "/factories",
        json={
            "name": "North Plant",
            "code": f"NP-{unique}",
            "location": "Cleveland, OH",
            "status": "active",
        },
    )
    assert create_response.status_code == 201
    factory = create_response.json()
    assert factory["name"] == "North Plant"
    assert factory["status"] == "active"

    detail_response = auth_client.get(f"/factories/{factory['id']}")
    assert detail_response.status_code == 200
    assert detail_response.json()["code"] == factory["code"]

    update_response = auth_client.put(
        f"/factories/{factory['id']}",
        json={"name": "North Plant Updated", "location": "Detroit, MI"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "North Plant Updated"
    assert update_response.json()["location"] == "Detroit, MI"

    delete_response = auth_client.delete(f"/factories/{factory['id']}")
    assert delete_response.status_code == 200
    assert delete_response.json()["status"] == "inactive"


def test_factory_list_paginates() -> None:
    auth_client = _authenticated_client()
    unique = uuid4().hex[:8]

    for index in range(12):
        response = auth_client.post(
            "/factories",
            json={
                "name": f"Factory {index}",
                "code": f"PG-{unique}-{index}",
                "location": "Austin, TX",
                "status": "active",
            },
        )
        assert response.status_code == 201

    first_page = auth_client.get("/factories?page=1&per_page=5")
    second_page = auth_client.get("/factories?page=2&per_page=5")

    assert first_page.status_code == 200
    assert second_page.status_code == 200
    assert first_page.json()["pages"] >= 2
    assert len(first_page.json()["items"]) == 5
    assert len(second_page.json()["items"]) == 5
