# AML System (work in progress)

Early skeleton of an anti-money-laundering (AML) platform built with FastAPI.

## Current status

- Working: web app startup, `GET /health`, `GET /health/ready`, interactive docs at `/docs`
- Written but not connected: database layer (`app/database.py`) and customer / sanctions-check data model (`app/models/customer.py`)
- Not implemented yet: customers, transactions, alerts, cases and reports routes (commented out in `app/main.py`), detection engines, services, repositories
- `docker-compose.yml` is not usable yet (it references a missing `.env`, `scripts/init_db.sql` and Celery module)

## Run locally (no database needed for now)

```
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Then open http://localhost:8000/health and http://localhost:8000/docs

## Security note

Default passwords and the default `secret_key` in the code are for testing only.
Do not use real customer data until they are replaced.
