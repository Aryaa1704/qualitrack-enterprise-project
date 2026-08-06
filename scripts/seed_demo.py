"""Seed a QualiTrack database with realistic demo data for portfolio reviews."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.database.session import SessionLocal
from app.models.factory import Batch, Defect, Department, Factory, Inspection, Machine, Product, ProductionLine
from app.models.user import User
from app.services.auth import get_password_hash

DEMO_PASSWORD = "DemoPass123!"


def _get_or_create_user(db, username: str, email: str, role: str) -> User:
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        user = User(username=username, email=email, hashed_password=get_password_hash(DEMO_PASSWORD), role=role, is_active=True)
        db.add(user)
        db.flush()
    else:
        user.email = email
        user.role = role
        user.is_active = True
    return user


def seed() -> None:
    """Insert deterministic demo records without altering the database schema."""

    with SessionLocal() as db:
        admin = _get_or_create_user(db, "admin_demo", "admin.demo@qualitrack.local", "admin")
        manager = _get_or_create_user(db, "manager_demo", "manager.demo@qualitrack.local", "quality_manager")
        inspector = _get_or_create_user(db, "inspector_demo", "inspector.demo@qualitrack.local", "inspector")

        if db.scalar(select(Factory).where(Factory.code == "DET-01")) is not None:
            db.commit()
            print("Demo data already present. Refreshed demo users only.")
            return

        factories = [
            Factory(name="Detroit Precision Plant", code="DET-01", location="Detroit, MI", status="active"),
            Factory(name="Austin Assembly Works", code="AUS-02", location="Austin, TX", status="active"),
            Factory(name="Cleveland Packaging Center", code="CLE-03", location="Cleveland, OH", status="active"),
        ]
        db.add_all(factories)
        db.flush()

        departments: list[Department] = []
        lines: list[ProductionLine] = []
        machines: list[Machine] = []
        for factory in factories:
            quality = Department(factory_id=factory.id, name="Quality Assurance", code="QA", status="active")
            assembly = Department(factory_id=factory.id, name="Final Assembly", code="ASM", status="active")
            db.add_all([quality, assembly])
            db.flush()
            departments.extend([quality, assembly])
            line_a = ProductionLine(factory_id=factory.id, department_id=assembly.id, name="Assembly Line A", code="LINE-A", status="active")
            line_b = ProductionLine(factory_id=factory.id, department_id=quality.id, name="Inspection Line B", code="LINE-B", status="active")
            db.add_all([line_a, line_b])
            db.flush()
            lines.extend([line_a, line_b])
            machines.extend([
                Machine(production_line_id=line_a.id, name="Torque Station", code="TOR-1", type="Assembly", status="active"),
                Machine(production_line_id=line_b.id, name="Vision Scanner", code="VIS-1", type="Inspection", status="active"),
            ])
        db.add_all(machines)

        products = [
            Product(name="AeroValve Housing", category="Aerospace", sku_code="AVH-100", status="active"),
            Product(name="MedPump Cartridge", category="Medical", sku_code="MPC-220", status="active"),
            Product(name="EV Sensor Module", category="Automotive", sku_code="EVS-310", status="active"),
            Product(name="Control Panel Kit", category="Industrial", sku_code="CPK-440", status="active"),
        ]
        db.add_all(products)
        db.flush()

        batches: list[Batch] = []
        today = date.today()
        for index, product in enumerate(products, start=1):
            batch = Batch(
                product_id=product.id,
                production_line_id=lines[index % len(lines)].id,
                batch_number=f"BATCH-2026-{index:03d}",
                manufacturing_date=today - timedelta(days=10 + index),
                expiry_date=today + timedelta(days=180 + index),
                quantity=1000 + index * 250,
                status="completed",
            )
            batches.append(batch)
        db.add_all(batches)
        db.flush()

        inspections = [
            Inspection(batch_id=batches[0].id, inspector_id=inspector.id, scratch="pass", color="pass", weight_actual=10.1, weight_spec=10.0, dimensions_actual="10x5x2", dimensions_spec="10x5x2", packaging="pass", functional_test="pass", overall_status="Pass", inspection_score=98, remarks="Production-ready sample."),
            Inspection(batch_id=batches[1].id, inspector_id=inspector.id, scratch="fail", color="pass", weight_actual=8.8, weight_spec=9.0, dimensions_actual="8x4x2", dimensions_spec="8x4x2", packaging="pass", functional_test="fail", overall_status="Fail", inspection_score=72, remarks="Scratch and functional failures found."),
            Inspection(batch_id=batches[2].id, inspector_id=manager.id, scratch="pass", color="fail", weight_actual=5.0, weight_spec=5.0, dimensions_actual="6x3x1", dimensions_spec="6x3x1", packaging="pass", functional_test="pass", overall_status="Fail", inspection_score=84, remarks="Paint color mismatch requires rework."),
        ]
        db.add_all(inspections)
        db.flush()

        db.add_all([
            Defect(inspection_id=inspections[1].id, defect_type="Scratch", severity="Medium", description="Visible scratch on exterior housing.", corrective_action="Retrain handling station operators.", status="In Progress"),
            Defect(inspection_id=inspections[1].id, defect_type="Loose Component", severity="High", description="Functional test failed due to loose connector.", corrective_action="Connector torque audit opened.", status="Open"),
            Defect(inspection_id=inspections[2].id, defect_type="Paint Issue", severity="Low", description="Color shade outside approved range.", corrective_action="Rework through paint booth.", status="Resolved", resolved_date=datetime.now(timezone.utc)),
        ])
        db.commit()
        print("Seeded QualiTrack demo data.")
        print(f"Demo password for all roles: {DEMO_PASSWORD}")


if __name__ == "__main__":
    seed()
