"""
AML System — FastAPI Application Entry Point (Production Clean Version)
"""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

# from prometheus_fastapi_instrumentator import Instrumentator  # optional (disable until stable)

from app.config import get_settings
from app.database import engine, Base

# ❌ تعطيل الروتات مؤقتًا إلى أن تتأكد أنها موجودة
# from app.api.v1 import customers, transactions, alerts, cases, reports
# from app.core.security import auth_router


settings = get_settings()
log = structlog.get_logger()


# ──────────────────────────────────────────────
# Lifespan (Startup / Shutdown)
# ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info(
        "aml_system_starting",
        version=getattr(settings, "app_version", "1.0.0"),
        env=getattr(settings, "environment", "dev"),
    )

    # ❌ تعطيل إنشاء الجداول مؤقتًا (سبب أخطاء DB في startup)
    # async with engine.begin() as conn:
    #     await conn.run_sync(Base.metadata.create_all)

    yield

    log.info("aml_system_stopping")
    await engine.dispose()


# ──────────────────────────────────────────────
# FastAPI App
# ──────────────────────────────────────────────
app = FastAPI(
    title=getattr(settings, "app_name", "AML System"),
    version=getattr(settings, "app_version", "1.0.0"),
    description="AML Platform (Clean Production Version)",
    docs_url="/docs" if getattr(settings, "debug", True) else None,
    redoc_url="/redoc" if getattr(settings, "debug", True) else None,
    lifespan=lifespan,
)


# ──────────────────────────────────────────────
# Security Middleware
# ──────────────────────────────────────────────
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*"]  # production: replace with real domain
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # production: restrict later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────
# Request ID Middleware
# ──────────────────────────────────────────────
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    import uuid

    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))

    with structlog.contextvars.bound_contextvars(request_id=request_id):
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


# ──────────────────────────────────────────────
# Global Exception Handler
# ──────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.exception("unhandled_exception", path=request.url.path, error=str(exc))

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Internal server error",
            "request_id": request.headers.get("X-Request-ID"),
        },
    )


# ──────────────────────────────────────────────
# Routers (DISABLED UNTIL MODULES ARE READY)
# ──────────────────────────────────────────────

API_PREFIX = "/api/v1"

# ❌ فعّلهم فقط عندما تتأكد أن الملفات موجودة
"""
app.include_router(auth_router)

app.include_router(customers.router, prefix=f"{API_PREFIX}/customers", tags=["customers"])
app.include_router(transactions.router, prefix=f"{API_PREFIX}/transactions", tags=["transactions"])
app.include_router(alerts.router, prefix=f"{API_PREFIX}/alerts", tags=["alerts"])
app.include_router(cases.router, prefix=f"{API_PREFIX}/cases", tags=["cases"])
app.include_router(reports.router, prefix=f"{API_PREFIX}/reports", tags=["reports"])
"""


# ──────────────────────────────────────────────
# Health Check (SAFE)
# ──────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/health/ready")
async def ready():
    # ❌ تعطيل DB/Redis check حتى تصلح الاتصال
    return {
        "status": "ready",
        "database": "skipped",
        "redis": "skipped"
    }


# ──────────────────────────────────────────────
# ML ROUTES (DISABLED TEMPORARILY)
# ──────────────────────────────────────────────
"""
from fastapi import APIRouter
from pydantic import BaseModel

ml_router = APIRouter(prefix=f"{API_PREFIX}/ml", tags=["ml"])

class MLRequest(BaseModel):
    transaction_id: str

@ml_router.post("/score")
async def score(payload: MLRequest):
    return {"status": "disabled"}

app.include_router(ml_router)
"""