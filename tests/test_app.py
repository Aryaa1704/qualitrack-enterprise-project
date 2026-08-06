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
    assert "/activity-logs" in paths
    assert "/activity-logs/recent" in paths
    assert "/factories" in paths
    assert "/factories/{factory_id}" in paths
    assert "post" in paths["/factories"]
    assert "get" in paths["/factories"]
    assert "get" in paths["/factories/{factory_id}"]
    assert "put" in paths["/factories/{factory_id}"]
    assert "delete" in paths["/factories/{factory_id}"]


def _authenticated_client(role: str = "admin") -> TestClient:
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
    from app.database.session import SessionLocal
    from app.models.user import User
    from sqlalchemy import select
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == username))
        assert user is not None
        user.role = role
        db.commit()

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



def test_openapi_schema_includes_machine_endpoints() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    collection = "/factories/{factory_id}/production-lines/{line_id}/machines"
    detail = "/factories/{factory_id}/production-lines/{line_id}/machines/{machine_id}"
    status_path = "/factories/{factory_id}/production-lines/{line_id}/machines/{machine_id}/status"
    assert collection in paths
    assert detail in paths
    assert status_path in paths
    assert {"post", "get"}.issubset(paths[collection])
    assert {"get", "put", "delete"}.issubset(paths[detail])
    assert "patch" in paths[status_path]


def _create_factory_line(auth_client: TestClient) -> tuple[dict, dict]:
    unique = uuid4().hex[:8]
    factory_response = auth_client.post(
        "/factories",
        json={"name": f"Machine Factory {unique}", "code": f"MF-{unique}", "location": "Toledo, OH"},
    )
    assert factory_response.status_code == 201
    factory = factory_response.json()
    line_response = auth_client.post(
        f"/factories/{factory['id']}/production-lines",
        json={"name": f"Machine Line {unique}", "code": f"ML-{unique}"},
    )
    assert line_response.status_code == 201
    return factory, line_response.json()


def test_machine_crud_status_change_and_uniqueness() -> None:
    auth_client = _authenticated_client()
    factory, line = _create_factory_line(auth_client)
    base_url = f"/factories/{factory['id']}/production-lines/{line['id']}/machines"

    create_response = auth_client.post(
        base_url,
        json={"name": "CNC-1", "code": "CNC001", "type": "CNC", "status": "active"},
    )
    assert create_response.status_code == 201
    machine = create_response.json()
    assert machine["production_line_id"] == line["id"]
    assert machine["factory_id"] == factory["id"]
    assert machine["status"] == "active"

    duplicate_response = auth_client.post(
        base_url,
        json={"name": "CNC Duplicate", "code": "CNC001", "type": "CNC", "status": "active"},
    )
    assert duplicate_response.status_code == 409

    read_response = auth_client.get(f"{base_url}/{machine['id']}")
    assert read_response.status_code == 200
    assert read_response.json()["code"] == "CNC001"

    update_response = auth_client.put(
        f"{base_url}/{machine['id']}",
        json={"name": "CNC-1 Updated", "type": "Milling"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "CNC-1 Updated"
    assert update_response.json()["type"] == "Milling"

    status_response = auth_client.patch(f"{base_url}/{machine['id']}/status", json={"status": "maintenance"})
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "maintenance"

    delete_response = auth_client.delete(f"{base_url}/{machine['id']}")
    assert delete_response.status_code == 200
    assert delete_response.json()["status"] == "inactive"


def test_machine_filters_by_status_line_and_factory() -> None:
    auth_client = _authenticated_client()
    factory, first_line = _create_factory_line(auth_client)
    second_line_response = auth_client.post(
        f"/factories/{factory['id']}/production-lines",
        json={"name": "Second Machine Line", "code": f"SML-{uuid4().hex[:8]}"},
    )
    assert second_line_response.status_code == 201
    second_line = second_line_response.json()

    first_url = f"/factories/{factory['id']}/production-lines/{first_line['id']}/machines"
    second_url = f"/factories/{factory['id']}/production-lines/{second_line['id']}/machines"
    active_response = auth_client.post(first_url, json={"name": "Robot Arm", "code": "RA1", "type": "Robot"})
    maintenance_response = auth_client.post(
        second_url,
        json={"name": "Welder", "code": "W1", "type": "Welder", "status": "maintenance"},
    )
    assert active_response.status_code == 201
    assert maintenance_response.status_code == 201

    status_filter = auth_client.get(f"{first_url}?status=maintenance&production_line_id={second_line['id']}")
    assert status_filter.status_code == 200
    assert status_filter.json()["total"] == 1
    assert status_filter.json()["items"][0]["status"] == "maintenance"

    line_filter = auth_client.get(f"{first_url}?production_line_id={first_line['id']}")
    assert line_filter.status_code == 200
    assert line_filter.json()["total"] == 1
    assert line_filter.json()["items"][0]["production_line_id"] == first_line["id"]

    factory_filter = auth_client.get(f"{first_url}?factory_filter_id={factory['id']}")
    assert factory_filter.status_code == 200
    assert factory_filter.json()["total"] == 1


def _create_line(auth_client: TestClient) -> dict:
    factory = _create_factory(auth_client)
    response = auth_client.post(
        f"/factories/{factory['id']}/production-lines",
        json={"name": "Phase 5 Line", "code": f"P5L-{uuid4().hex[:6]}", "status": "active"},
    )
    assert response.status_code == 201
    return response.json()


def _create_product(auth_client: TestClient, suffix: str | None = None) -> dict:
    unique = suffix or uuid4().hex[:8]
    response = auth_client.post(
        "/products",
        json={"name": f"Widget {unique}", "category": "Widgets", "sku_code": f"SKU-{unique}", "status": "active"},
    )
    assert response.status_code == 201
    return response.json()


def test_openapi_schema_includes_product_and_batch_endpoints() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/products" in paths
    assert "/products/{product_id}" in paths
    assert "/batches" in paths
    assert "/batches/{batch_id}" in paths
    assert {"post", "get"}.issubset(paths["/products"])
    assert {"get", "put", "delete"}.issubset(paths["/products/{product_id}"])
    assert {"post", "get"}.issubset(paths["/batches"])
    assert {"get", "put", "delete"}.issubset(paths["/batches/{batch_id}"])


def test_product_crud_search_filter_pagination_and_batch_history() -> None:
    auth_client = _authenticated_client()
    unique = uuid4().hex[:8]
    product = _create_product(auth_client, unique)

    duplicate_response = auth_client.post(
        "/products",
        json={"name": "Duplicate", "category": "Widgets", "sku_code": product["sku_code"]},
    )
    assert duplicate_response.status_code == 409

    read_response = auth_client.get(f"/products/{product['id']}")
    assert read_response.status_code == 200
    assert read_response.json()["sku_code"] == product["sku_code"]

    update_response = auth_client.put(f"/products/{product['id']}", json={"name": "Updated Widget", "category": "Updated"})
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "Updated Widget"

    for index in range(11):
        response = auth_client.post(
            "/products",
            json={"name": f"Gadget {unique} {index}", "category": "Gadgets", "sku_code": f"GAD-{unique}-{index}"},
        )
        assert response.status_code == 201

    list_response = auth_client.get(f"/products?search=Gadget {unique}&category=Gadgets&status_filter=active&page=1&per_page=5")
    assert list_response.status_code == 200
    assert list_response.json()["pages"] >= 2
    assert len(list_response.json()["items"]) == 5

    line = _create_line(auth_client)
    batch_response = auth_client.post(
        "/batches",
        json={
            "product_id": product["id"],
            "production_line_id": line["id"],
            "batch_number": f"BATCH-HIST-{unique}",
            "manufacturing_date": "2026-08-01",
            "expiry_date": "2026-09-01",
            "quantity": 100,
            "status": "planned",
        },
    )
    assert batch_response.status_code == 201
    history_response = auth_client.get(f"/products/{product['id']}", headers={"accept": "text/html"})
    assert history_response.status_code == 200
    assert f"BATCH-HIST-{unique}" in history_response.text

    delete_response = auth_client.delete(f"/products/{product['id']}")
    assert delete_response.status_code == 200
    assert delete_response.json()["status"] == "inactive"


def test_batch_crud_relationship_validation_filter_and_pagination() -> None:
    auth_client = _authenticated_client()
    unique = uuid4().hex[:8]
    product = _create_product(auth_client, unique)
    line = _create_line(auth_client)

    invalid_date_response = auth_client.post(
        "/batches",
        json={
            "product_id": product["id"],
            "production_line_id": line["id"],
            "batch_number": f"BAD-DATE-{unique}",
            "manufacturing_date": "2026-09-01",
            "expiry_date": "2026-08-01",
            "quantity": 100,
        },
    )
    assert invalid_date_response.status_code == 422

    create_response = auth_client.post(
        "/batches",
        json={
            "product_id": product["id"],
            "production_line_id": line["id"],
            "batch_number": f"BATCH-{unique}-0",
            "manufacturing_date": "2026-08-01",
            "expiry_date": "2026-09-01",
            "quantity": 100,
            "status": "planned",
        },
    )
    assert create_response.status_code == 201
    batch = create_response.json()
    assert batch["product_id"] == product["id"]
    assert batch["production_line_id"] == line["id"]

    duplicate_response = auth_client.post(
        "/batches",
        json={
            "product_id": product["id"],
            "production_line_id": line["id"],
            "batch_number": batch["batch_number"],
            "manufacturing_date": "2026-08-02",
            "expiry_date": "2026-09-02",
            "quantity": 50,
        },
    )
    assert duplicate_response.status_code == 409

    read_response = auth_client.get(f"/batches/{batch['id']}")
    assert read_response.status_code == 200
    assert read_response.json()["batch_number"] == batch["batch_number"]

    update_response = auth_client.put(f"/batches/{batch['id']}", json={"quantity": 125, "status": "in_progress"})
    assert update_response.status_code == 200
    assert update_response.json()["quantity"] == 125
    assert update_response.json()["status"] == "in_progress"

    for index in range(1, 12):
        response = auth_client.post(
            "/batches",
            json={
                "product_id": product["id"],
                "production_line_id": line["id"],
                "batch_number": f"BATCH-{unique}-{index}",
                "manufacturing_date": f"2026-08-{index + 1:02d}",
                "expiry_date": f"2026-09-{index + 1:02d}",
                "quantity": 100 + index,
                "status": "completed",
            },
        )
        assert response.status_code == 201

    filtered_response = auth_client.get(
        f"/batches?search=BATCH-{unique}&product_id={product['id']}&production_line_id={line['id']}&status_filter=completed&start_date=2026-08-02&end_date=2026-08-12&page=1&per_page=5"
    )
    assert filtered_response.status_code == 200
    assert filtered_response.json()["pages"] >= 2
    assert len(filtered_response.json()["items"]) == 5

    delete_response = auth_client.delete(f"/batches/{batch['id']}")
    assert delete_response.status_code == 200
    assert delete_response.json()["status"] == "inactive"


def _create_batch(auth_client: TestClient, suffix: str | None = None) -> dict:
    unique = suffix or uuid4().hex[:8]
    product = _create_product(auth_client, f"IB-{unique}")
    line = _create_line(auth_client)
    response = auth_client.post(
        "/batches",
        json={
            "product_id": product["id"],
            "production_line_id": line["id"],
            "batch_number": f"INS-BATCH-{unique}",
            "manufacturing_date": "2026-08-01",
            "expiry_date": "2026-09-01",
            "quantity": 100,
            "status": "completed",
        },
    )
    assert response.status_code == 201
    return response.json()


def _inspection_payload(batch_id: int, **overrides: object) -> dict:
    payload: dict[str, object] = {
        "batch_id": batch_id,
        "scratch": "pass",
        "color": "pass",
        "weight_actual": 10.1,
        "weight_spec": 10.0,
        "dimensions_actual": "10x20x30",
        "dimensions_spec": "10x20x30",
        "packaging": "pass",
        "functional_test": "pass",
        "inspection_score": 98,
        "remarks": "Within tolerance",
    }
    payload.update(overrides)
    return payload


def test_openapi_schema_includes_inspection_endpoints() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/inspections" in paths
    assert "/inspections/{inspection_id}" in paths
    assert "/inspections/batch/{batch_id}/history" in paths
    assert "/inspections/search" in paths
    assert "/inspections/filter" in paths
    assert {"post", "get"}.issubset(paths["/inspections"])
    assert {"get", "put", "delete"}.issubset(paths["/inspections/{inspection_id}"])


def test_inspection_workflow_calculation_inspector_history_edit_delete_and_filters() -> None:
    auth_client = _authenticated_client()
    batch = _create_batch(auth_client)
    me_response = auth_client.get("/auth/me")
    assert me_response.status_code == 200
    current_user_id = me_response.json()["id"]

    create_response = auth_client.post(
        "/inspections",
        json=_inspection_payload(batch["id"], inspector_id=999999, color="fail", remarks="Color is outside tolerance"),
    )
    assert create_response.status_code == 201
    inspection = create_response.json()
    assert inspection["overall_status"] == "Fail"
    assert inspection["inspector_id"] == current_user_id

    override_response = auth_client.post(
        "/inspections",
        json=_inspection_payload(batch["id"], scratch="fail", overall_status="Pass", remarks="Engineering waiver approved"),
    )
    assert override_response.status_code == 201
    assert override_response.json()["overall_status"] == "Pass"

    missing_remarks_response = auth_client.post(
        "/inspections",
        json=_inspection_payload(batch["id"], scratch="fail", overall_status="Pass", remarks=""),
    )
    assert missing_remarks_response.status_code == 422

    history_response = auth_client.get(f"/inspections/batch/{batch['id']}/history")
    assert history_response.status_code == 200
    assert len(history_response.json()) == 2

    html_history_response = auth_client.get(f"/batches/{batch['id']}", headers={"accept": "text/html"})
    assert html_history_response.status_code == 200
    assert "Inspection History" in html_history_response.text
    assert "Color is outside tolerance" not in html_history_response.text

    update_response = auth_client.put(
        f"/inspections/{inspection['id']}",
        json={"color": "pass", "overall_status": "Pass", "remarks": "Corrected on recheck", "inspection_score": 100},
    )
    assert update_response.status_code == 200
    assert update_response.json()["overall_status"] == "Pass"
    assert update_response.json()["inspection_score"] == 100

    list_response = auth_client.get(f"/inspections?search={batch['batch_number']}&batch_id={batch['id']}&status_filter=Pass&page=1&per_page=1")
    assert list_response.status_code == 200
    assert list_response.json()["pages"] >= 2
    assert len(list_response.json()["items"]) == 1

    search_response = auth_client.get(f"/inspections/search?q={batch['batch_number']}&status_filter=Pass")
    assert search_response.status_code == 200
    assert search_response.json()["total"] == 2

    filter_response = auth_client.get(f"/inspections/filter?batch_id={batch['id']}&inspector_id={current_user_id}&status_filter=Pass")
    assert filter_response.status_code == 200
    assert filter_response.json()["total"] == 2

    delete_response = auth_client.delete(f"/inspections/{inspection['id']}")
    assert delete_response.status_code == 200

    updated_history_response = auth_client.get(f"/inspections/batch/{batch['id']}/history")
    assert updated_history_response.status_code == 200
    assert len(updated_history_response.json()) == 1


def test_openapi_schema_includes_defect_endpoints() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/defects" in paths
    assert "/defects/stats" in paths
    assert "/defects/{defect_id}" in paths
    assert {"post", "get"}.issubset(paths["/defects"])
    assert {"get", "put", "delete"}.issubset(paths["/defects/{defect_id}"])
    assert "get" in paths["/defects/stats"]


def test_defect_crud_filters_stats_resolution_and_html_flow() -> None:
    auth_client = _authenticated_client()
    batch = _create_batch(auth_client)
    pass_response = auth_client.post("/inspections", json=_inspection_payload(batch["id"]))
    fail_response = auth_client.post(
        "/inspections",
        json=_inspection_payload(batch["id"], scratch="fail", remarks="Scratch found during final inspection", inspection_score=72),
    )
    assert pass_response.status_code == 201
    assert fail_response.status_code == 201
    pass_inspection = pass_response.json()
    fail_inspection = fail_response.json()

    rejected_response = auth_client.post(
        "/defects",
        json={
            "inspection_id": pass_inspection["id"],
            "defect_type": "Scratch",
            "severity": "Low",
            "description": "Should not attach to passed inspection",
        },
    )
    assert rejected_response.status_code == 422

    create_response = auth_client.post(
        "/defects",
        json={
            "inspection_id": fail_inspection["id"],
            "defect_type": "Scratch",
            "severity": "High",
            "description": "Deep scratch on product housing",
            "corrective_action": "Route to rework",
            "status": "Open",
        },
    )
    assert create_response.status_code == 201
    defect = create_response.json()
    assert defect["inspection_id"] == fail_inspection["id"]
    assert defect["resolved_date"] is None

    html_detail_response = auth_client.get(f"/inspections/{fail_inspection['id']}", headers={"accept": "text/html"})
    assert html_detail_response.status_code == 200
    assert "Add Defect" in html_detail_response.text
    assert "Deep scratch on product housing" in html_detail_response.text
    assert "Scratch" in html_detail_response.text

    second_response = auth_client.post(
        "/defects",
        json={
            "inspection_id": fail_inspection["id"],
            "defect_type": "Crack",
            "severity": "Medium",
            "description": "Hairline crack on bracket",
            "status": "In Progress",
        },
    )
    assert second_response.status_code == 201

    resolve_response = auth_client.put(
        f"/defects/{defect['id']}",
        json={"status": "Resolved", "corrective_action": "Housing replaced"},
    )
    assert resolve_response.status_code == 200
    assert resolve_response.json()["status"] == "Resolved"
    assert resolve_response.json()["resolved_date"] is not None

    filter_response = auth_client.get("/defects?defect_type=Scratch&severity=High&status_filter=Resolved")
    assert filter_response.status_code == 200
    assert filter_response.json()["total"] == 1
    assert filter_response.json()["items"][0]["id"] == defect["id"]

    stats_response = auth_client.get("/defects/stats")
    assert stats_response.status_code == 200
    stats = stats_response.json()
    assert stats["by_type"]["Scratch"] >= 1
    assert stats["by_type"]["Crack"] >= 1
    assert stats["by_severity"]["High"] >= 1
    assert stats["by_severity"]["Medium"] >= 1

    delete_response = auth_client.delete(f"/defects/{defect['id']}")
    assert delete_response.status_code == 200


def test_openapi_schema_includes_dashboard_endpoints() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/dashboard/summary" in paths
    assert "/dashboard/trend" in paths
    assert "/dashboard/top-defects" in paths
    assert "/dashboard/top-inspector" in paths
    assert "get" in paths["/dashboard/summary"]
    assert "get" in paths["/dashboard/trend"]
    assert "get" in paths["/dashboard/top-defects"]
    assert "get" in paths["/dashboard/top-inspector"]


def test_dashboard_apis_return_live_aggregated_data_and_update() -> None:
    auth_client = _authenticated_client()
    batch = _create_batch(auth_client, f"DASH-{uuid4().hex[:6]}")
    pending_batch = _create_batch(auth_client, f"DASH-PENDING-{uuid4().hex[:6]}")

    dashboard_page = auth_client.get("/dashboard", headers={"accept": "text/html"})
    assert dashboard_page.status_code == 200
    assert "Quality Dashboard" in dashboard_page.text
    assert pending_batch["batch_number"] not in dashboard_page.text

    pass_response = auth_client.post("/inspections", json=_inspection_payload(batch["id"], inspection_score=96))
    fail_response = auth_client.post(
        "/inspections",
        json=_inspection_payload(batch["id"], scratch="fail", remarks="Dashboard fail sample", inspection_score=71),
    )
    assert pass_response.status_code == 201
    assert fail_response.status_code == 201
    fail_inspection = fail_response.json()

    defect_response = auth_client.post(
        "/defects",
        json={
            "inspection_id": fail_inspection["id"],
            "defect_type": "Paint Issue",
            "severity": "High",
            "description": "Paint chip visible on dashboard sample",
            "status": "Open",
        },
    )
    assert defect_response.status_code == 201

    summary_response = auth_client.get("/dashboard/summary")
    trend_response = auth_client.get("/dashboard/trend")
    defects_response = auth_client.get("/dashboard/top-defects")
    inspectors_response = auth_client.get("/dashboard/top-inspector")

    assert summary_response.status_code == 200
    assert trend_response.status_code == 200
    assert defects_response.status_code == 200
    assert inspectors_response.status_code == 200

    summary = summary_response.json()
    assert summary["today_inspections"] >= 2
    assert summary["pass_percent"] > 0
    assert summary["fail_percent"] > 0
    assert summary["pending_inspections"] >= 1
    assert summary["critical_defects"] >= 1

    trend = trend_response.json()
    assert len(trend["labels"]) == 30
    assert len(trend["counts"]) == 30
    assert sum(trend["counts"]) >= 2

    defects = defects_response.json()
    assert "Paint Issue" in defects["labels"]
    paint_index = defects["labels"].index("Paint Issue")
    assert defects["counts"][paint_index] >= 1

    inspectors = inspectors_response.json()
    me_response = auth_client.get("/auth/me")
    assert me_response.status_code == 200
    assert me_response.status_code == 200
    assert me_response.json()["username"]
    assert len(inspectors["labels"]) == len(inspectors["counts"])
    assert len(inspectors["labels"]) <= 8

    before_count = summary["today_inspections"]
    new_response = auth_client.post("/inspections", json=_inspection_payload(batch["id"], inspection_score=99))
    assert new_response.status_code == 201
    refreshed_summary = auth_client.get("/dashboard/summary").json()
    assert refreshed_summary["today_inspections"] == before_count + 1


def test_openapi_schema_includes_report_endpoints() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    for path in (
        "/reports/inspection",
        "/reports/inspection/export",
        "/reports/defect",
        "/reports/defect/export",
        "/reports/factory",
        "/reports/factory/export",
        "/reports/batch",
        "/reports/batch/export",
    ):
        assert path in paths
        assert "get" in paths[path]


def test_reports_filter_summaries_and_csv_exports() -> None:
    auth_client = _authenticated_client()
    batch = _create_batch(auth_client, f"RPT-{uuid4().hex[:6]}")
    me_response = auth_client.get("/auth/me")
    assert me_response.status_code == 200
    current_user_id = me_response.json()["id"]

    pass_response = auth_client.post("/inspections", json=_inspection_payload(batch["id"], inspection_score=97))
    fail_response = auth_client.post(
        "/inspections",
        json=_inspection_payload(batch["id"], scratch="fail", remarks="Report failure sample", inspection_score=66),
    )
    assert pass_response.status_code == 201
    assert fail_response.status_code == 201
    fail_inspection = fail_response.json()

    defect_response = auth_client.post(
        "/defects",
        json={
            "inspection_id": fail_inspection["id"],
            "defect_type": "Crack",
            "severity": "High",
            "description": "Report crack sample",
            "status": "Open",
        },
    )
    assert defect_response.status_code == 201

    inspection_report = auth_client.get(f"/reports/inspection?batch_id={batch['id']}&inspector_id={current_user_id}&status_filter=Fail")
    assert inspection_report.status_code == 200
    inspection_data = inspection_report.json()
    assert inspection_data["summary"]["total"] == 1
    assert inspection_data["summary"]["fail_percent"] == 100
    assert inspection_data["items"][0]["overall_status"] == "Fail"

    inspection_csv = auth_client.get(f"/reports/inspection/export?batch_id={batch['id']}&status_filter=Fail")
    assert inspection_csv.status_code == 200
    assert "text/csv" in inspection_csv.headers["content-type"]
    assert "Report" not in inspection_csv.text
    assert batch["batch_number"] in inspection_csv.text

    defect_report = auth_client.get("/reports/defect?defect_type=Crack&severity=High&status_filter=Open")
    assert defect_report.status_code == 200
    defect_data = defect_report.json()
    assert defect_data["summary"]["open"] >= 1
    assert defect_data["summary"]["critical"] >= 1
    assert any(item["description"] == "Report crack sample" for item in defect_data["items"])

    defect_csv = auth_client.get("/reports/defect/export?defect_type=Crack&severity=High&status_filter=Open")
    assert defect_csv.status_code == 200
    assert "Report crack sample" in defect_csv.text

    factory_report = auth_client.get("/reports/factory")
    assert factory_report.status_code == 200
    assert factory_report.json()["summary"]["pass_count"] >= 1
    assert factory_report.json()["summary"]["fail_count"] >= 1

    factory_csv = auth_client.get("/reports/factory/export")
    assert factory_csv.status_code == 200
    assert "Factory ID,Factory,Code,Total Inspections,Pass,Fail" in factory_csv.text

    batch_report = auth_client.get("/reports/batch")
    assert batch_report.status_code == 200
    assert any(item["batch_number"] == batch["batch_number"] and item["defect_count"] >= 1 for item in batch_report.json()["items"])

    batch_csv = auth_client.get("/reports/batch/export")
    assert batch_csv.status_code == 200
    assert batch["batch_number"] in batch_csv.text


def test_openapi_includes_global_search_without_duplicate_routes() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/search" in paths
    route_keys = [(tuple(sorted(route.methods or [])), route.path) for route in app.routes if hasattr(route, "methods")]
    assert len(route_keys) == len(set(route_keys))


def test_standard_list_query_parameters_and_global_search() -> None:
    auth_client = _authenticated_client()
    unique = uuid4().hex[:8]
    factory_response = auth_client.post("/factories", json={"name": f"Search Plant {unique}", "code": f"SP-{unique}", "location": "Akron, OH"})
    assert factory_response.status_code == 201
    factory = factory_response.json()
    line_response = auth_client.post(f"/factories/{factory['id']}/production-lines", json={"name": f"Search Line {unique}", "code": f"SL-{unique}"})
    assert line_response.status_code == 201
    product_response = auth_client.post("/products", json={"name": f"Search Widget {unique}", "category": "Widgets", "sku_code": f"SKU-{unique}"})
    assert product_response.status_code == 201
    product = product_response.json()
    batch_response = auth_client.post("/batches", json={"product_id": product["id"], "production_line_id": line_response.json()["id"], "batch_number": f"B-{unique}", "manufacturing_date": "2026-08-01", "expiry_date": "2026-09-01", "quantity": 12})
    assert batch_response.status_code == 201
    batch = batch_response.json()
    inspection_response = auth_client.post("/inspections", json={"batch_id": batch["id"], "scratch": "fail", "color": "pass", "weight_actual": 10, "weight_spec": 10, "dimensions_actual": "1x1", "dimensions_spec": "1x1", "packaging": "pass", "functional_test": "pass", "inspection_score": 80})
    assert inspection_response.status_code == 201
    defect_response = auth_client.post("/defects", json={"inspection_id": inspection_response.json()["id"], "defect_type": "Scratch", "severity": "High", "description": f"Search defect {unique}"})
    assert defect_response.status_code == 201

    checks = ["/factories", "/products", "/batches", "/inspections", "/defects"]
    for path in checks:
        response = auth_client.get(f"{path}?search={unique}&sort_by=id&sort_order=desc&page=1&page_size=1")
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["per_page"] == 1
        assert data["total"] >= 1

    search_response = auth_client.get(f"/search?q={unique}")
    assert search_response.status_code == 200
    grouped = search_response.json()
    assert all(group in grouped for group in ["products", "batches", "inspections", "defects"])
    assert grouped["products"]
    assert grouped["batches"]
    assert grouped["inspections"]
    assert grouped["defects"]


def test_rbac_role_permissions_and_admin_role_management() -> None:
    admin_client = _authenticated_client("admin")
    manager_client = _authenticated_client("quality_manager")
    inspector_client = _authenticated_client("inspector")

    assert admin_client.post("/factories", json={"name": "RBAC Plant", "code": f"RB-{uuid4().hex[:6]}", "location": "Detroit, MI"}).status_code == 201
    assert manager_client.get("/factories").status_code == 200
    assert manager_client.post("/factories", json={"name": "Manager Plant", "code": f"MP-{uuid4().hex[:6]}", "location": "Detroit, MI"}).status_code == 403
    assert inspector_client.get("/factories").status_code == 403
    assert inspector_client.get("/dashboard/summary").status_code == 403
    assert admin_client.get("/auth/users").status_code == 200

    target = inspector_client.get("/auth/me").json()
    update_response = admin_client.put(f"/auth/users/{target['id']}/role", json={"role": "quality_manager"})
    assert update_response.status_code == 200
    assert update_response.json()["role"] == "quality_manager"


def test_activity_logs_capture_events_filters_recent_and_dashboard() -> None:
    auth_client = _authenticated_client("admin")
    batch = _create_batch(auth_client, f"ACT-{uuid4().hex[:6]}")

    login_logs = auth_client.get("/activity-logs?action=login")
    assert login_logs.status_code == 200
    assert any(item["action"] == "login" for item in login_logs.json()["items"])

    inspection_response = auth_client.post(
        "/inspections",
        json=_inspection_payload(batch["id"], scratch="fail", remarks="Activity fail sample", inspection_score=70),
    )
    assert inspection_response.status_code == 201
    inspection = inspection_response.json()

    defect_response = auth_client.post(
        "/defects",
        json={"inspection_id": inspection["id"], "defect_type": "Scratch", "severity": "High", "description": "Activity defect sample"},
    )
    assert defect_response.status_code == 201
    defect = defect_response.json()

    update_response = auth_client.put(f"/defects/{defect['id']}", json={"status": "In Progress"})
    assert update_response.status_code == 200

    today = "2026-08-06"
    filtered = auth_client.get(f"/activity-logs?action=defect_updated&user_id={auth_client.get('/auth/me').json()['id']}&start_date={today}&end_date={today}")
    assert filtered.status_code == 200
    assert filtered.json()["total"] >= 1
    assert filtered.json()["items"][0]["action"] == "defect_updated"

    recent = auth_client.get("/activity-logs/recent?limit=5")
    assert recent.status_code == 200
    assert any(item["description"].startswith("Updated defect") for item in recent.json())

    dashboard = auth_client.get("/dashboard", headers={"accept": "text/html"})
    assert dashboard.status_code == 200
    assert "Updated defect" in dashboard.text
    assert "View all activity" in dashboard.text

    html_logs = auth_client.get("/activity-logs?action=defect_updated", headers={"accept": "text/html"})
    assert html_logs.status_code == 200
    assert "Activity Logs" in html_logs.text
    assert "Updated defect" in html_logs.text


def test_activity_logs_record_report_exports_and_rbac() -> None:
    admin_client = _authenticated_client("admin")
    inspector_client = _authenticated_client("inspector")

    assert inspector_client.get("/activity-logs").status_code == 403
    assert inspector_client.get("/activity-logs/recent").status_code == 200

    export_response = admin_client.get("/reports/batch/export")
    assert export_response.status_code == 200

    logs = admin_client.get("/activity-logs?action=report_exported")
    assert logs.status_code == 200
    assert any(item["description"] == "Exported batch report" for item in logs.json()["items"])


def test_api_errors_use_standard_shape() -> None:
    response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated", "code": "not_authenticated"}


def test_validation_errors_use_standard_shape() -> None:
    auth_client = _authenticated_client()
    response = auth_client.post("/factories", json={"name": "", "code": "", "location": ""})

    assert response.status_code == 422
    payload = response.json()
    assert payload["code"] == "validation_error"
    assert payload["detail"] == "Invalid factory data"
