"""Health check endpoint."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter()

DB_SESSION = Depends(get_db)


@router.get("/health")
def health_check(db: Session = DB_SESSION) -> dict[str, str]:
    """Health check endpoint with DB connectivity verification."""
    db.scalar(select(1))
    return {"status": "ok"}
