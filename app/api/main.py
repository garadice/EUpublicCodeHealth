"""FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import exports, health, projects, runs
from app.core.config import get_settings
from app.core.logging import setup_logging

setup_logging()

settings = get_settings()

app = FastAPI(
    title=settings.app_title,
    version=settings.app_version,
    description="Data pipeline monitoring repository activity of OSS projects from EU public-sector catalogues",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(projects.router)
app.include_router(exports.router)
app.include_router(runs.router)
