"""Database connection helper. Reads credentials from .env (never hard-code passwords)."""
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def get_engine():
    # URL.create escapes special characters in the password (e.g. '@' or '#').
    url = URL.create(
        "postgresql+psycopg2",
        username=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", 5432)),
        database=os.environ["DB_NAME"],
    )
    return create_engine(url)


if __name__ == "__main__":
    with get_engine().connect() as conn:
        print(conn.execute(text("select version()")).scalar())