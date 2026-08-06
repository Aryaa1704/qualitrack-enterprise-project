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


def _create_phase6_batch(auth_client: TestClient, suffix: str | None = None) -> dict:
    unique = f"{suffix}-{uuid4().hex[:8]}" if suffix else uuid4().hex[:8]
    product = _create_product(auth_client, f"I-{unique}")
    line = _create_line(auth_client)
    response = auth_client.post(
        "/batches",
        json={
            "product_id": product["id"],
            "production_line_id": line["id"],
            "batch_number": f"INS-BATCH-{unique}",
            "manufacturing_date": "2026-08-01",
            "expiry_date": "2026-09-01",
            "quantity": 250,
            "status": "planned",
        },
    )
    assert response.status_code == 201
    return response.json()


def _inspection_payload(batch_id: int, **overrides: object) -> dict:
    payload = {
        "batch_id": batch_id,
        "scratch": "pass",
        "color": "pass",
        "weight_actual": 10.1,
        "weight_spec": 10.0,
        "dimensions_actual": "10x10x10",
        "dimensions_spec": "10x10x10",
        "packaging": "pass",
        "functional_test": "pass",
        "remarks": "",
    }
    payload.update(overrides)
    return payload


def test_openapi_schema_includes_inspection_endpoints() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/inspections" in paths
    assert "/inspections/search" in paths
    assert "/inspections/filter" in paths
    assert "/inspections/{inspection_id}" in paths
    assert "/batches/{batch_id}/inspections" in paths
    assert {"post", "get"}.issubset(paths["/inspections"])
    assert "get" in paths["/inspections/search"]
    assert "get" in paths["/inspections/filter"]
    assert {"get", "put", "delete"}.issubset(paths["/inspections/{inspection_id}"])
    assert "get" in paths["/batches/{batch_id}/inspections"]


def test_inspection_workflow_current_inspector_status_override_edit_delete_and_history() -> None:
    auth_client = _authenticated_client()
    batch = _create_phase6_batch(auth_client)
    current_user = auth_client.get("/auth/me").json()

    create_response = auth_client.post(
        "/inspections",
        json=_inspection_payload(batch["id"], inspector_id=999999),
    )
    assert create_response.status_code == 201
    inspection = create_response.json()
    assert inspection["inspector_id"] == current_user["id"]
    assert inspection["overall_status"] == "Pass"
    assert inspection["inspection_score"] == 100.0

    fail_response = auth_client.post(
        "/inspections",
        json=_inspection_payload(batch["id"], scratch="fail"),
    )
    assert fail_response.status_code == 201
    assert fail_response.json()["overall_status"] == "Fail"
    assert fail_response.json()["inspection_score"] == 75.0

    invalid_override = auth_client.post(
        "/inspections",
        json=_inspection_payload(batch["id"], scratch="fail", overall_status="Pass"),
    )
    assert invalid_override.status_code == 422

    override_response = auth_client.post(
        "/inspections",
        json=_inspection_payload(
            batch["id"],
            scratch="fail",
            overall_status="Pass",
            remarks="Supervisor accepted cosmetic scratch after review.",
        ),
    )
    assert override_response.status_code == 201
    assert override_response.json()["overall_status"] == "Pass"

    history_response = auth_client.get(f"/batches/{batch['id']}/inspections")
    assert history_response.status_code == 200
    assert history_response.json()["total"] == 3

    batch_detail_response = auth_client.get(f"/batches/{batch['id']}", headers={"accept": "text/html"})
    assert batch_detail_response.status_code == 200
    assert "Quality inspections" in batch_detail_response.text

    update_response = auth_client.put(
        f"/inspections/{inspection['id']}",
        json={"packaging": "fail", "remarks": "Packaging seam failed final review."},
    )
    assert update_response.status_code == 200
    assert update_response.json()["inspector_id"] == current_user["id"]
    assert update_response.json()["overall_status"] == "Fail"
    assert update_response.json()["inspection_score"] == 75.0

    delete_response = auth_client.delete(f"/inspections/{inspection['id']}")
    assert delete_response.status_code == 200
    deleted_read = auth_client.get(f"/inspections/{inspection['id']}")
    assert deleted_read.status_code == 404

    updated_history = auth_client.get(f"/batches/{batch['id']}/inspections")
    assert updated_history.status_code == 200
    assert updated_history.json()["total"] == 2


def test_inspection_search_filter_and_pagination() -> None:
    auth_client = _authenticated_client()
    first_batch = _create_phase6_batch(auth_client, "FILTER-A")
    second_batch = _create_phase6_batch(auth_client, "FILTER-B")
    inspector = auth_client.get("/auth/me").json()

    for index in range(12):
        target_batch = first_batch if index < 7 else second_batch
        response = auth_client.post(
            "/inspections",
            json=_inspection_payload(
                target_batch["id"],
                scratch="fail" if index % 2 else "pass",
                remarks="Filter failure" if index % 2 else "",
            ),
        )
        assert response.status_code == 201

    list_response = auth_client.get("/inspections?page=1&per_page=5")
    assert list_response.status_code == 200
    assert list_response.json()["pages"] >= 3
    assert len(list_response.json()["items"]) == 5

    search_response = auth_client.get(f"/inspections/search?q={first_batch['batch_number']}&page=1&per_page=5")
    assert search_response.status_code == 200
    assert search_response.json()["total"] == 7

    filter_response = auth_client.get(
        f"/inspections/filter?batch_id={first_batch['id']}&inspector_id={inspector['id']}&status_filter=Fail&page=1&per_page=5"
    )
    assert filter_response.status_code == 200
    assert filter_response.json()["total"] == 3
    assert all(item["overall_status"] == "Fail" for item in filter_response.json()["items"])
