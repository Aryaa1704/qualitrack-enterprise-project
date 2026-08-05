# QualiTrack

QualiTrack is a Manufacturing Quality Inspection & Defect Analytics Platform.

This repository contains the Phase 4 foundation: a FastAPI application shell, template layout, static styling, settings, SQLite/SQLAlchemy wiring, a health-check endpoint, JWT-backed user authentication, and factory management, departments, production lines, and machines. It does not include role permissions, products, or batches yet.

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
- Machines: open a factory detail page, then use the Machines section under its production lines.


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
- `GET /factories` returns a paginated factory list.
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

Factory, department, production line, and machine pages and APIs require an authenticated user session.

## Tests

```bash
pytest
```
