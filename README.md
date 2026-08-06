# QualiTrack

QualiTrack is a Manufacturing Quality Inspection & Defect Analytics Platform.

This repository contains the Phase 5 foundation: a FastAPI application shell, template layout, static styling, settings, SQLite/SQLAlchemy wiring, a health-check endpoint, JWT-backed user authentication, factory management, departments, production lines, machines, products, and production batches, inspections, defect tracking, a live analytics dashboard, and read-only reports with CSV exports. It does not include role permissions yet.

## For builders: what this means in simple words

Think of this phase like preparing an empty factory building before machines arrive:

- **FastAPI app**: the main web application engine.
- **Router/API foundation**: the place where future screens and API endpoints will be connected.
- **Database session wiring**: the safe connection path to the future SQLite database.
- **Templates and CSS**: the basic page frame and visual style.
- **Health check**: a simple endpoint that says, "the app is alive."
- **Authentication**: inspectors can register, log in, log out, and view a protected profile.
- **Factory management**: authenticated users can create, review, update, and soft-delete factories.
- **Departments and production lines**: authenticated users can manage factory-scoped departments and production lines, including optional department grouping for lines.
- **Machines**: authenticated users can manage equipment under production lines, change machine status, and filter machines by status, production line, or factory.
- **Products**: authenticated users can manage product catalog records, enforce unique SKU codes, and search/filter product lists.
- **Batches**: authenticated users can assign product batches to production lines, validate manufacturing/expiry dates, enforce unique batch numbers, filter by relationship/status/date range, and view product batch history.
- **Dashboard analytics**: authenticated users can view live inspection summaries, pass/fail rates, 30-day trends, top defects, top inspectors, and recent inspections.
- **Reports**: authenticated users can review inspection, defect, factory, and batch reports with matching CSV exports.
- **Global search and standardized filters**: authenticated users can search products, batches, inspections, and defects from the nav, and list pages share search, sorting, and page-size controls.

## Project structure

```text
QualiTrack/
├── app/
│   ├── api/
│   ├── core/
│   ├── database/
│   ├── models/
│   ├── schemas/
│   ├── services/
│   ├── templates/
│   ├── static/
│   │   ├── css/
│   │   ├── js/
│   │   └── images/
│   ├── routers/
│   ├── utils/
│   └── main.py
├── migrations/
│   └── versions/
├── tests/
├── requirements.txt
├── README.md
├── .gitignore
├── .env.example
├── LICENSE
└── run.py
```

## Setup

Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Optionally copy the example environment file:

```bash
cp .env.example .env
```

## Run the app

```bash
uvicorn app.main:app --reload
```

Or:

```bash
python run.py
```

Then open:

- Home page: <http://127.0.0.1:8000/>
- Swagger API docs: <http://127.0.0.1:8000/docs>
- Health check: <http://127.0.0.1:8000/health>
- Register: <http://127.0.0.1:8000/auth/register>
- Login: <http://127.0.0.1:8000/auth/login>
- Profile: <http://127.0.0.1:8000/auth/profile>
- Factories: <http://127.0.0.1:8000/factories>
- Products: <http://127.0.0.1:8000/products>
- Batches: <http://127.0.0.1:8000/batches>
- Machines: open a factory detail page, then use the Machines section under its production lines.
- Dashboard: <http://127.0.0.1:8000/dashboard>
- Reports: <http://127.0.0.1:8000/reports>
- Global search: <http://127.0.0.1:8000/search?q=sample>


## Report endpoints

- `GET /reports/inspection` returns filtered inspection report data or renders the inspection report page.
- `GET /reports/inspection/export` downloads the filtered inspection report as CSV.
- `GET /reports/defect` returns filtered defect report data or renders the defect report page.
- `GET /reports/defect/export` downloads the filtered defect report as CSV.
- `GET /reports/factory` returns factory-level pass/fail inspection aggregates or renders the factory report page.
- `GET /reports/factory/export` downloads the factory report as CSV.
- `GET /reports/batch` returns batch-level inspection and defect counts or renders the batch report page.
- `GET /reports/batch/export` downloads the batch report as CSV.

## Authentication endpoints

- `POST /auth/register` creates a user account with the default `inspector` role.
- `POST /auth/login` validates credentials, issues a JWT access token, and stores it in an HTTP-only cookie for browser sessions.
- `GET /auth/me` returns the logged-in user's public profile details.
- `POST /auth/logout` clears the browser session cookie.

Run migrations before first use so the `users` table exists:

```bash
alembic upgrade head
```

## Factory endpoints

- `POST /factories` creates a factory.
- `GET /factories` returns a paginated factory list with `search`, `sort_by`, `sort_order`, `page`, and `page_size` query parameters.
- `GET /factories/{factory_id}` returns one factory.
- `PUT /factories/{factory_id}` updates a factory.
- `DELETE /factories/{factory_id}` soft-deletes a factory by marking it inactive.

## Department and production line endpoints

- `POST /factories/{factory_id}/departments` creates a factory-scoped department.
- `GET /factories/{factory_id}/departments` returns active departments with pagination.
- `GET /factories/{factory_id}/departments/{dept_id}` returns one active department.
- `PUT /factories/{factory_id}/departments/{dept_id}` updates a department.
- `DELETE /factories/{factory_id}/departments/{dept_id}` soft-deletes a department by marking it inactive.
- `POST /factories/{factory_id}/production-lines` creates a factory-scoped production line.
- `GET /factories/{factory_id}/production-lines` returns active production lines with pagination.
- `GET /factories/{factory_id}/production-lines/{line_id}` returns one active production line.
- `PUT /factories/{factory_id}/production-lines/{line_id}` updates a production line.
- `DELETE /factories/{factory_id}/production-lines/{line_id}` soft-deletes a production line by marking it inactive.

## Machine endpoints

- `POST /factories/{factory_id}/production-lines/{line_id}/machines` creates a machine under a production line.
- `GET /factories/{factory_id}/production-lines/{line_id}/machines` returns machines and supports `status`, `status_filter`, `production_line_id`, and `factory_filter_id` query filters.
- `GET /factories/{factory_id}/production-lines/{line_id}/machines/{machine_id}` returns one machine.
- `PUT /factories/{factory_id}/production-lines/{line_id}/machines/{machine_id}` updates a machine.
- `PATCH /factories/{factory_id}/production-lines/{line_id}/machines/{machine_id}/status` changes only the machine status.
- `DELETE /factories/{factory_id}/production-lines/{line_id}/machines/{machine_id}` soft-deletes a machine by marking it inactive.

## Product endpoints

- `POST /products` creates a product.
- `GET /products` returns products with search, category, status, sorting, and pagination filters.
- `GET /products/{product_id}` returns one product; browser views include batch history.
- `PUT /products/{product_id}` updates a product.
- `DELETE /products/{product_id}` soft-deletes a product by marking it inactive.

## Batch endpoints

- `POST /batches` creates a batch assigned to a product and production line.
- `GET /batches` returns batches with search, product, production line, status, manufacturing date range, sorting, and pagination filters.
- `GET /batches/{batch_id}` returns one batch.
- `PUT /batches/{batch_id}` updates a batch.
- `DELETE /batches/{batch_id}` soft-deletes a batch by marking it inactive.

Factory, department, production line, machine, product, and batch pages and APIs require an authenticated user session.

## Tests

```bash
pytest
```


## Quality inspections

Authenticated inspectors can create, edit, delete, search, and filter batch quality inspections. New inspections are always attributed to the logged-in user, auto-calculate Pass/Fail status from inspection checks, and appear in batch inspection history.

## Defect tracking

Failed inspections can have one or more linked defects. Authenticated users can add defects from a failed inspection detail page, edit corrective actions and statuses, mark defects resolved, filter the defect list by type/severity/status/date range, and read grouped counts for future dashboard analytics.

## Defect endpoints

- `POST /defects` creates a defect linked to a failed inspection.
- `GET /defects` returns defects with search, type, severity, status, created-date range, sorting, and pagination filters.
- `GET /defects/stats` returns defect counts grouped by type and by severity.
- `GET /defects/{defect_id}` returns one defect.
- `PUT /defects/{defect_id}` updates a defect and automatically sets `resolved_date` when status becomes `Resolved`.
- `DELETE /defects/{defect_id}` deletes a defect.

## Dashboard analytics

The authenticated dashboard page uses Chart.js and client-side `fetch()` calls so charts are populated from live API data instead of hard-coded template values. It includes summary cards, pass/fail distribution, a 30-day inspection trend, most common defects, top inspectors, and a simple recent-inspections activity feed.

## Dashboard endpoints

- `GET /dashboard/summary` returns today's inspection count, live pass/fail percentages, batches with zero inspections, and unresolved high-severity defects.
- `GET /dashboard/trend` returns daily inspection counts for the last 30 days.
- `GET /dashboard/top-defects` returns defect counts grouped by defect type for charting.
- `GET /dashboard/top-inspector` returns inspection counts grouped by inspector for charting.
