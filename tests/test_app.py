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


def _create_factory(auth_client: TestClient) -> dict:
    unique = uuid4().hex[:8]
    response = auth_client.post(
        "/factories",
        json={
            "name": f"Factory {unique}",
            "code": f"F-{unique}",
            "location": "Columbus, OH",
            "status": "active",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_openapi_schema_includes_department_and_production_line_endpoints() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/factories/{factory_id}/departments" in paths
    assert "/factories/{factory_id}/departments/{dept_id}" in paths
    assert "/factories/{factory_id}/production-lines" in paths
    assert "/factories/{factory_id}/production-lines/{line_id}" in paths
    assert {"post", "get"}.issubset(paths["/factories/{factory_id}/departments"])
    assert {"get", "put", "delete"}.issubset(paths["/factories/{factory_id}/departments/{dept_id}"])
    assert {"post", "get"}.issubset(paths["/factories/{factory_id}/production-lines"])
    assert {"get", "put", "delete"}.issubset(paths["/factories/{factory_id}/production-lines/{line_id}"])


def test_department_crud_soft_delete_pagination_and_uniqueness() -> None:
    auth_client = _authenticated_client()
    factory = _create_factory(auth_client)

    create_response = auth_client.post(
        f"/factories/{factory['id']}/departments",
        json={"name": "Assembly", "code": "ASM", "status": "active"},
    )
    assert create_response.status_code == 201
    department = create_response.json()
    assert department["factory_id"] == factory["id"]
    assert department["code"] == "ASM"

    duplicate_response = auth_client.post(
        f"/factories/{factory['id']}/departments",
        json={"name": "Assembly Duplicate", "code": "ASM", "status": "active"},
    )
    assert duplicate_response.status_code == 400

    read_response = auth_client.get(f"/factories/{factory['id']}/departments/{department['id']}")
    assert read_response.status_code == 200
    assert read_response.json()["id"] == department["id"]

    update_response = auth_client.put(
        f"/factories/{factory['id']}/departments/{department['id']}",
        json={"name": "Final Assembly", "code": "FASM"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "Final Assembly"

    unique = uuid4().hex[:8]
    for index in range(11):
        response = auth_client.post(
            f"/factories/{factory['id']}/departments",
            json={"name": f"Department {index}", "code": f"D-{unique}-{index}"},
        )
        assert response.status_code == 201

    page_response = auth_client.get(f"/factories/{factory['id']}/departments?page=1&per_page=5")
    assert page_response.status_code == 200
    assert page_response.json()["pages"] >= 2
    assert len(page_response.json()["items"]) == 5

    delete_response = auth_client.delete(f"/factories/{factory['id']}/departments/{department['id']}")
    assert delete_response.status_code == 200
    assert delete_response.json()["status"] == "inactive"

    list_response = auth_client.get(f"/factories/{factory['id']}/departments?per_page=50")
    assert list_response.status_code == 200
    assert department["id"] not in [item["id"] for item in list_response.json()["items"]]

    deleted_read_response = auth_client.get(f"/factories/{factory['id']}/departments/{department['id']}")
    assert deleted_read_response.status_code == 404


def test_production_line_crud_nullable_department_relationships_and_uniqueness() -> None:
    auth_client = _authenticated_client()
    factory = _create_factory(auth_client)
    department_response = auth_client.post(
        f"/factories/{factory['id']}/departments",
        json={"name": "Packaging", "code": "PKG"},
    )
    assert department_response.status_code == 201
    department = department_response.json()

    line_response = auth_client.post(
        f"/factories/{factory['id']}/production-lines",
        json={"name": "Line 1", "code": "L1", "department_id": department["id"], "status": "active"},
    )
    assert line_response.status_code == 201
    line = line_response.json()
    assert line["factory_id"] == factory["id"]
    assert line["department_id"] == department["id"]

    nullable_response = auth_client.post(
        f"/factories/{factory['id']}/production-lines",
        json={"name": "Unassigned Line", "code": "UA"},
    )
    assert nullable_response.status_code == 201
    assert nullable_response.json()["department_id"] is None

    duplicate_response = auth_client.post(
        f"/factories/{factory['id']}/production-lines",
        json={"name": "Duplicate Line", "code": "L1"},
    )
    assert duplicate_response.status_code == 400

    read_response = auth_client.get(f"/factories/{factory['id']}/production-lines/{line['id']}")
    assert read_response.status_code == 200
    assert read_response.json()["id"] == line["id"]

    update_response = auth_client.put(
        f"/factories/{factory['id']}/production-lines/{line['id']}",
        json={"name": "Line 1 Updated", "department_id": None},
    )
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "Line 1 Updated"
    assert update_response.json()["department_id"] is None

    unique = uuid4().hex[:8]
    for index in range(10):
        response = auth_client.post(
            f"/factories/{factory['id']}/production-lines",
            json={"name": f"Line {index}", "code": f"L-{unique}-{index}"},
        )
        assert response.status_code == 201

    page_response = auth_client.get(f"/factories/{factory['id']}/production-lines?page=1&per_page=5")
    assert page_response.status_code == 200
    assert page_response.json()["pages"] >= 2
    assert len(page_response.json()["items"]) == 5

    delete_response = auth_client.delete(f"/factories/{factory['id']}/production-lines/{line['id']}")
    assert delete_response.status_code == 200
    assert delete_response.json()["status"] == "inactive"

    deleted_read_response = auth_client.get(f"/factories/{factory['id']}/production-lines/{line['id']}")
    assert deleted_read_response.status_code == 404


def _create_production_line(auth_client: TestClient, factory_id: int, code: str = "ML1") -> dict:
    response = auth_client.post(
        f"/factories/{factory_id}/production-lines",
        json={"name": f"Machine Line {code}", "code": code, "status": "active"},
    )
    assert response.status_code == 201
    return response.json()


def test_openapi_schema_includes_machine_endpoints() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    collection = "/factories/{factory_id}/production-lines/{line_id}/machines"
    detail = "/factories/{factory_id}/production-lines/{line_id}/machines/{machine_id}"
    status_path = "/factories/{factory_id}/production-lines/{line_id}/machines/{machine_id}/status"
    assert "/factories/{factory_id}/machines" in paths
    assert collection in paths
    assert detail in paths
    assert status_path in paths
    assert "get" in paths["/factories/{factory_id}/machines"]
    assert "post" in paths[collection]
    assert {"get", "put", "delete"}.issubset(paths[detail])
    assert "patch" in paths[status_path]


def test_machine_crud_status_change_filters_and_factory_detail_display() -> None:
    auth_client = _authenticated_client()
    factory = _create_factory(auth_client)
    line = _create_production_line(auth_client, factory["id"], "ML1")
    other_line = _create_production_line(auth_client, factory["id"], "ML2")

    create_response = auth_client.post(
        f"/factories/{factory['id']}/production-lines/{line['id']}/machines",
        json={"name": "CNC Mill", "code": "CNC-1", "type": "CNC", "status": "active"},
    )
    assert create_response.status_code == 201
    machine = create_response.json()
    assert machine["production_line_id"] == line["id"]
    assert machine["status"] == "active"

    duplicate_response = auth_client.post(
        f"/factories/{factory['id']}/production-lines/{line['id']}/machines",
        json={"name": "Duplicate CNC", "code": "CNC-1", "type": "CNC"},
    )
    assert duplicate_response.status_code == 400

    other_response = auth_client.post(
        f"/factories/{factory['id']}/production-lines/{other_line['id']}/machines",
        json={"name": "Robot Arm", "code": "ROB-1", "type": "Robot", "status": "inactive"},
    )
    assert other_response.status_code == 201

    detail_response = auth_client.get(
        f"/factories/{factory['id']}/production-lines/{line['id']}/machines/{machine['id']}"
    )
    assert detail_response.status_code == 200
    assert detail_response.json()["code"] == "CNC-1"

    update_response = auth_client.put(
        f"/factories/{factory['id']}/production-lines/{line['id']}/machines/{machine['id']}",
        json={"name": "CNC Mill Updated", "type": "Precision CNC"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "CNC Mill Updated"
    assert update_response.json()["type"] == "Precision CNC"

    status_response = auth_client.patch(
        f"/factories/{factory['id']}/production-lines/{line['id']}/machines/{machine['id']}/status",
        json={"status": "maintenance"},
    )
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "maintenance"

    maintenance_filter = auth_client.get(f"/factories/{factory['id']}/machines?status=maintenance")
    assert maintenance_filter.status_code == 200
    assert [item["id"] for item in maintenance_filter.json()["items"]] == [machine["id"]]

    line_filter = auth_client.get(f"/factories/{factory['id']}/machines?production_line_id={other_line['id']}")
    assert line_filter.status_code == 200
    assert [item["id"] for item in line_filter.json()["items"]] == [other_response.json()["id"]]

    detail_page = auth_client.get(f"/factories/{factory['id']}", headers={"accept": "text/html"})
    assert detail_page.status_code == 200
    assert "CNC Mill Updated" in detail_page.text
    assert "Production line machines" in detail_page.text

    delete_response = auth_client.delete(
        f"/factories/{factory['id']}/production-lines/{line['id']}/machines/{machine['id']}"
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["status"] == "inactive"

    inactive_filter = auth_client.get(f"/factories/{factory['id']}/machines?status=inactive")
    assert inactive_filter.status_code == 200
    assert machine["id"] in [item["id"] for item in inactive_filter.json()["items"]]
