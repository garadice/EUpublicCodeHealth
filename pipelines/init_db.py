from pathlib import Path
from sqlalchemy import text
from app.db import engine


def run():
    schema = Path("db/schema.sql").read_text()
    statements = [s.strip() for s in schema.split(";") if s.strip()]
    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))


if __name__ == "__main__":
    run()
