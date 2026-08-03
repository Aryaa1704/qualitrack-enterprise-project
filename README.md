# QualiTrack

QualiTrack is a Manufacturing Quality Inspection & Defect Analytics Platform.

This repository currently contains the Phase 0 foundation: a FastAPI application shell, template layout, static styling, settings, SQLite/SQLAlchemy wiring, and a health-check endpoint. It does not include authentication, database models, CRUD screens, or business workflows yet.

## For builders: what this means in simple words

Think of this phase like preparing an empty factory building before machines arrive:

- **FastAPI app**: the main web application engine.
- **Router/API foundation**: the place where future screens and API endpoints will be connected.
- **Database session wiring**: the safe connection path to the future SQLite database.
- **Templates and CSS**: the basic page frame and visual style.
- **Health check**: a simple endpoint that says, "the app is alive."

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

## Tests

```bash
pytest
```
