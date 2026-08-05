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


# Machine CRUD Tests
def test_machine_crud_operations(client, db):
    """Test machine create, read, update operations."""
    # Create factory, dept, line first
    factory_res = client.post("/factories", json={"name": "Test", "code": "TST"})
    factory_id = factory_res.json()["id"]
    
    line_res = client.post(f"/factories/{factory_id}/production-lines",
        json={"name": "Line 1", "code": "L1"})
    line_id = line_res.json()["id"]
    
    # Create machine
    machine_data = {"name": "CNC-1", "code": "CNC001", "type": "CNC", "status": "active"}
    res = client.post(f"/factories/{factory_id}/production-lines/{line_id}/machines",
        json=machine_data)
    assert res.status_code == 201
    machine = res.json()
    assert machine["name"] == "CNC-1"
    assert machine["status"] == "active"
    
    # Read machine
    res = client.get(f"/factories/{factory_id}/production-lines/{line_id}/machines/{machine['id']}")
    assert res.status_code == 200
    assert res.json()["code"] == "CNC001"


def test_machine_uniqueness_constraint(client, db):
    """Test machine code uniqueness per production line."""
    factory_res = client.post("/factories", json={"name": "Test2", "code": "TS2"})
    factory_id = factory_res.json()["id"]
    
    line_res = client.post(f"/factories/{factory_id}/production-lines",
        json={"name": "Line2", "code": "L2"})
    line_id = line_res.json()["id"]
    
    # Create first machine
    machine_data = {"name": "Machine1", "code": "M001", "type": "Assembly", "status": "active"}
    res1 = client.post(f"/factories/{factory_id}/production-lines/{line_id}/machines",
        json=machine_data)
    assert res1.status_code == 201
    
    # Try duplicate code
    res2 = client.post(f"/factories/{factory_id}/production-lines/{line_id}/machines",
        json=machine_data)
    assert res2.status_code == 409  # Conflict - duplicate code


def test_machine_status_soft_delete(client, db):
    """Test machine soft delete via status change."""
    factory_res = client.post("/factories", json={"name": "Test3", "code": "TS3"})
    factory_id = factory_res.json()["id"]
    
    line_res = client.post(f"/factories/{factory_id}/production-lines",
        json={"name": "Line3", "code": "L3"})
    line_id = line_res.json()["id"]
    
    machine_res = client.post(f"/factories/{factory_id}/production-lines/{line_id}/machines",
        json={"name": "TestMachine", "code": "TM001", "type": "Test", "status": "active"})
    machine_id = machine_res.json()["id"]
    
    # Change status to inactive
    patch_res = client.patch(f"/factories/{factory_id}/production-lines/{line_id}/machines/{machine_id}",
        json={"status": "inactive"})
    assert patch_res.status_code == 200
    assert patch_res.json()["status"] == "inactive"


def test_machine_relationships(client, db):
    """Test machine relationships with production line."""
    factory_res = client.post("/factories", json={"name": "RelTest", "code": "RT"})
    factory_id = factory_res.json()["id"]
    
    line_res = client.post(f"/factories/{factory_id}/production-lines",
        json={"name": "RelLine", "code": "RL"})
    line_id = line_res.json()["id"]
    
    machine_res = client.post(f"/factories/{factory_id}/production-lines/{line_id}/machines",
        json={"name": "RelMachine", "code": "RM001", "type": "Drill", "status": "active"})
    
    # Verify relationship
    machines = client.get(f"/factories/{factory_id}/production-lines/{line_id}/machines").json()
    assert len(machines["items"]) == 1
    assert machines["items"][0]["production_line_id"] == line_id


def test_machine_crud_operations() -> None:
    """Test machine CRUD operations with correct pattern."""
    auth_client = _authenticated_client()
    
    # Create factory
    factory_res = auth_client.post(
        "/factories",
        json={"name": "Machine Test Factory", "code": "MTF"}
    )
    assert factory_res.status_code == 201
    factory_id = factory_res.json()["id"]
    
    # Create production line
    line_res = auth_client.post(
        f"/factories/{factory_id}/production-lines",
        json={"name": "Test Line", "code": "TL"}
    )
    assert line_res.status_code == 201
    line_id = line_res.json()["id"]
    
    # Create machine
    machine_res = auth_client.post(
        f"/factories/{factory_id}/production-lines/{line_id}/machines",
        json={"name": "CNC-1", "code": "CNC001", "type": "CNC", "status": "active"}
    )
    assert machine_res.status_code == 201
    machine = machine_res.json()
    assert machine["name"] == "CNC-1"
    assert machine["code"] == "CNC001"
    assert machine["status"] == "active"
    machine_id = machine["id"]
    
    # Read machine
    get_res = auth_client.get(
        f"/factories/{factory_id}/production-lines/{line_id}/machines/{machine_id}"
    )
    assert get_res.status_code == 200
    assert get_res.json()["code"] == "CNC001"
    
    # Update machine status
    update_res = auth_client.patch(
        f"/factories/{factory_id}/production-lines/{line_id}/machines/{machine_id}",
        json={"status": "inactive"}
    )
    assert update_res.status_code == 200
    assert update_res.json()["status"] == "inactive"


def test_machine_uniqueness_constraint() -> None:
    """Test machine code uniqueness per production line."""
    auth_client = _authenticated_client()
    
    # Create factory and production line
    factory_res = auth_client.post(
        "/factories",
        json={"name": "Unique Test Factory", "code": "UTF"}
    )
    factory_id = factory_res.json()["id"]
    
    line_res = auth_client.post(
        f"/factories/{factory_id}/production-lines",
        json={"name": "Unique Test Line", "code": "UTL"}
    )
    line_id = line_res.json()["id"]
    
    # Create first machine
    machine_data = {"name": "Machine-1", "code": "M001", "type": "Assembly", "status": "active"}
    res1 = auth_client.post(
        f"/factories/{factory_id}/production-lines/{line_id}/machines",
        json=machine_data
    )
    assert res1.status_code == 201
    
    # Try create duplicate code
    res2 = auth_client.post(
        f"/factories/{factory_id}/production-lines/{line_id}/machines",
        json=machine_data
    )
    assert res2.status_code == 409  # Conflict


def test_machine_status_soft_delete() -> None:
    """Test machine soft delete via status change."""
    auth_client = _authenticated_client()
    
    # Create factory, line, machine
    factory_res = auth_client.post(
        "/factories",
        json={"name": "Soft Delete Factory", "code": "SDF"}
    )
    factory_id = factory_res.json()["id"]
    
    line_res = auth_client.post(
        f"/factories/{factory_id}/production-lines",
        json={"name": "Soft Delete Line", "code": "SDL"}
    )
    line_id = line_res.json()["id"]
    
    machine_res = auth_client.post(
        f"/factories/{factory_id}/production-lines/{line_id}/machines",
        json={"name": "Delete Test", "code": "DT001", "type": "Test", "status": "active"}
    )
    assert machine_res.status_code == 201
    machine_id = machine_res.json()["id"]
    
    # Soft delete by changing status
    delete_res = auth_client.patch(
        f"/factories/{factory_id}/production-lines/{line_id}/machines/{machine_id}",
        json={"status": "inactive"}
    )
    assert delete_res.status_code == 200
    assert delete_res.json()["status"] == "inactive"


def test_machine_relationships() -> None:
    """Test machine relationships with production line."""
    auth_client = _authenticated_client()
    
    # Create factory, department, line, machine
    factory_res = auth_client.post(
        "/factories",
        json={"name": "Relationship Factory", "code": "RF"}
    )
    factory_id = factory_res.json()["id"]
    
    line_res = auth_client.post(
        f"/factories/{factory_id}/production-lines",
        json={"name": "Relationship Line", "code": "RL"}
    )
    line_id = line_res.json()["id"]
    
    machine_res = auth_client.post(
        f"/factories/{factory_id}/production-lines/{line_id}/machines",
        json={"name": "Relationship Machine", "code": "RM001", "type": "Drill", "status": "active"}
    )
    assert machine_res.status_code == 201
    machine = machine_res.json()
    assert machine["production_line_id"] == line_id
    
    # Verify machine in production line list
    machines_res = auth_client.get(
        f"/factories/{factory_id}/production-lines/{line_id}/machines"
    )
    assert machines_res.status_code == 200
    machines = machines_res.json()
    assert len(machines["items"]) >= 1
    assert any(m["id"] == machine["id"] for m in machines["items"])
