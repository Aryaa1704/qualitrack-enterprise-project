# QualiTrack

QualiTrack is a production-ready FastAPI portfolio application for manufacturing quality inspection, defect tracking, reporting, and role-based plant operations.

## Project overview

QualiTrack helps manufacturing teams manage factories, departments, production lines, machines, products, batches, quality inspections, defects, dashboards, reports, activity logs, notifications, and global search from one web application.

Demo roles:

| Role | Demo username | Password | Access summary |
| --- | --- | --- | --- |
| Admin | `admin_demo` | `DemoPass123!` | Full access, including user role management. |
| Quality Manager | `manager_demo` | `DemoPass123!` | Quality workflows, dashboards, reports, and view-only master data. |
| Inspector | `inspector_demo` | `DemoPass123!` | Inspection and defect workflows plus profile access. |

## Architecture summary

```text
app/
├── core/          # Settings and configuration
├── database/      # SQLAlchemy engine, session, and base metadata
├── models/        # SQLAlchemy models for users, plant hierarchy, quality data, audit logs
├── routers/       # FastAPI route modules and HTML/API handlers
├── schemas/       # Pydantic request/response schemas
├── services/      # Authentication and activity-log helpers
├── static/        # CSS, JavaScript, and image assets
├── templates/     # Jinja2 pages and reusable components
└── main.py        # FastAPI app assembly, router registration, error handlers
migrations/        # Alembic migration history
scripts/           # Release/demo operational scripts
tests/             # Regression tests
```

The application uses FastAPI, SQLAlchemy 2.x, SQLite by default, Alembic-ready migrations, Jinja2 templates, vanilla JavaScript, Chart.js, JWT cookie authentication, and role-based access control.

## Setup from a fresh clone

1. Create and activate a virtual environment:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Create local configuration:

   ```bash
   cp .env.example .env
   ```

4. Run database migrations:

   ```bash
   alembic upgrade head
   ```

5. Seed demo data:

   ```bash
   python scripts/seed_demo.py
   ```

6. Start the app:

   ```bash
   uvicorn app.main:app --reload
   ```

7. Open the application:

   - Home: <http://127.0.0.1:8000/>
   - API docs: <http://127.0.0.1:8000/docs>
   - Health check: <http://127.0.0.1:8000/health>

## Main modules

- **Authentication**: registration, login, logout, profile, JWT cookies, and admin role management.
- **Factory hierarchy**: factories, departments, production lines, and machines.
- **Product and batch management**: product catalog, production batch assignment, validation, filtering, and history.
- **Inspections**: quality inspection creation, editing, pass/fail scoring, detail pages, and batch history.
- **Defects**: failed-inspection defect logging, corrective actions, resolution status, and analytics grouping.
- **Dashboard**: live inspection summaries, pass/fail rates, trends, top defects, top inspectors, and activity feed.
- **Reports**: inspection, defect, factory, and batch reports with CSV exports.
- **Activity logs and notifications**: audit trail for important user actions and recent-activity notifications.
- **Global search**: searchable products, batches, inspections, and defects.

## API behavior

All API errors use a consistent response envelope:

```json
{
  "detail": "Human-readable error or validation details",
  "code": "machine_readable_code"
}
```

Common codes include `not_authenticated`, `not_authorized`, `not_found`, `conflict`, and `validation_error`.

## Screenshots

Add portfolio screenshots here after deploying or running locally:

- Home/dashboard screenshot: `docs/screenshots/dashboard.png`
- Factory hierarchy screenshot: `docs/screenshots/factories.png`
- Inspection workflow screenshot: `docs/screenshots/inspections.png`
- Defect analytics screenshot: `docs/screenshots/defects.png`
- Reports screenshot: `docs/screenshots/reports.png`

## Testing

Run the regression suite:

```bash
pytest
```

Run a fresh database smoke test:

```bash
rm -f qualitrack.db
alembic upgrade head
python scripts/seed_demo.py
uvicorn app.main:app --reload
```

## Deployment guide

### Render or Railway

1. Create a new Python web service from this repository.
2. Set the start command:

   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port $PORT
   ```

3. Add environment variables:

   ```text
   DATABASE_URL=sqlite:///./qualitrack.db
   SECRET_KEY=<strong-random-secret>
   DEBUG=false
   ```

4. Run migrations before the first web process starts. On platforms with release commands, use:

   ```bash
   alembic upgrade head && python scripts/seed_demo.py
   ```

For a production team deployment, use a managed PostgreSQL database URL instead of SQLite and run migrations as a release step.

### Docker-compatible command

If deploying inside a Python container, install dependencies and run:

```bash
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## License

See [LICENSE](LICENSE).
