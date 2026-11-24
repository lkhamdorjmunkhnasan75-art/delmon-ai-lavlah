"""Read-only public directory API. No tenant identity is accepted here."""
import os
from contextlib import closing
from fastapi import FastAPI, Query, HTTPException
import psycopg
from psycopg.rows import dict_row

app = FastAPI(title="DELMON LAVLAH public directory")
SQL = """
SELECT organization_id, name, category_slug, description, source_url,
       verified_at, expires_at
FROM lavlah.public_directory
WHERE strpos(lower(name), lower(%s)) > 0
  AND (%s = '' OR category_slug = %s)
ORDER BY lower(name), organization_id
LIMIT %s OFFSET %s
"""

def search_directory(q, category, limit, offset):
    # Dedicated server-side login must inherit only lavlah_public_reader.
    with closing(psycopg.connect(os.environ["LAVLAH_PUBLIC_DSN"], row_factory=dict_row,
                                 connect_timeout=5)) as conn:
        with conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            conn.execute("SET LOCAL statement_timeout = '3s'")
            conn.execute("SET LOCAL ROLE lavlah_public_reader")
            return conn.execute(SQL, (q, category, category, limit, offset)).fetchall()

@app.get("/v1/directory")
def directory(q: str = Query("", max_length=120),
              category: str = Query("", max_length=80, pattern=r"^([a-z0-9]+(-[a-z0-9]+)*)?$"),
              limit: int = Query(20, ge=1, le=100),
              offset: int = Query(0, ge=0, le=10000)):
    try:
        rows = search_directory(q.strip(), category, limit, offset)
    except (psycopg.Error, KeyError):
        raise HTTPException(503, "Directory temporarily unavailable") from None
    fields = ("organization_id", "name", "category_slug", "description",
              "source_url", "verified_at", "expires_at")
    return {"items": [{k: row[k] for k in fields} for row in rows],
            "limit": limit, "offset": offset}

# Serve the initial mobile UI on the same origin as the directory API.
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
WEB_DIR = Path(__file__).resolve().parents[1] / "web"
app.mount("/ui", StaticFiles(directory=WEB_DIR), name="ui")

@app.get("/", include_in_schema=False)
def home():
    return FileResponse(WEB_DIR / "index.html")
