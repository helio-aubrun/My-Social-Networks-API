import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from .config import get_settings
from .database import Base, engine
from .middleware import BodySizeLimitMiddleware, RateLimiter, RateLimitMiddleware, SecurityHeadersMiddleware
from .routers import albums, auth, carpools, events, groups, polls, shopping, threads, ticketing, users

logger = logging.getLogger("api")
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    logger.info("[API] base de données prête")
    yield
    engine.dispose()
    logger.info("[CLOSE] connexions à la base de données fermées")


app = FastAPI(
    title="My Social Networks API",
    description=(
        "API de gestion d'un réseau social : utilisateurs, événements, groupes, fils de discussion, "
        "albums photo, sondages, billetterie, shopping list et covoiturage.\n\n"
        "Authentification : `POST /auth/login` puis en-tête `Authorization: Bearer <token>`."
    ),
    version="2.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)

app.state.rate_limiter = RateLimiter(
    global_limit=settings.rate_limit_per_hour,
    login_limit=settings.login_rate_limit,
    login_window_seconds=settings.login_rate_window_minutes * 60,
    enabled=settings.rate_limit_enabled,
)

app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)
app.add_middleware(RateLimitMiddleware, limiter=app.state.rate_limiter)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)
app.add_middleware(SecurityHeadersMiddleware)


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError):
    logger.warning("[CONFLICT] %s %s -> %s", request.method, request.url.path, exc.orig)
    return JSONResponse(status_code=409, content={"detail": "Ressource déjà existante ou en conflit"})


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    logger.exception("[ERROR] %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Erreur interne du serveur"})


for module in (auth, users, events, groups, threads, albums, polls, ticketing, shopping, carpools):
    app.include_router(module.router)


@app.get("/", tags=["Santé"])
def root():
    """Vérifie que l'API répond."""
    return {"status": "ok"}
