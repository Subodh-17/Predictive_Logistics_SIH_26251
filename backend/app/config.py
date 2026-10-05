import os
from pathlib import Path

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://logistics:logistics@localhost:5432/logistics")
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:8080,http://127.0.0.1:5173").split(",") if o.strip()]
# schema.sql / seed.sql are mounted into the Postgres container; the backend can also apply them itself (dev convenience)
DB_DIR = Path(os.getenv("DB_DIR", str(Path(__file__).resolve().parents[2] / "db")))
AUTO_INIT_DB = os.getenv("AUTO_INIT_DB", "1") == "1"
DB_WAIT_SECONDS = int(os.getenv("DB_WAIT_SECONDS", "60"))
DATA_NOTICE = "Prototype uses fictional synthetic logistics data and is intended for decision-support demonstration only."
