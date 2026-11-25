"""Read-only public directory API. No tenant identity is accepted here."""
import os
import logging
from lavlah.grounded_ai import respond as grounded_answer
from lavlah import authenticated_chat as identity_chat
from contextlib import closing
from fastapi import FastAPI, Query, HTTPException, Response, Request
from fastapi.responses import JSONResponse
from lavlah.pilot_security import enabled as pilot_enabled, security, event
from fastapi.exceptions import RequestValidationError
from lavlah.api_limits import reserve, Limited, principal_bucket
from lavlah.synthetic_identity import validate, configured_key
import asyncio
from starlette.concurrency import run_in_threadpool
from lavlah.identity_store import check_connection, checked_dsn, profile, revoke_token
from pydantic import BaseModel, Field, ConfigDict
from lavlah.mongolian_qa import answer as directory_answer
import psycopg
from psycopg.rows import dict_row

app = FastAPI(title="DELMON LAVLAH public directory")

@app.middleware("http")
async def pilot_guard(request: Request, call_next):
    if not request.url.path.startswith("/v1/pilot/"):
        return await call_next(request)
    def reject(status,code):
        event(code)
        headers={"Cache-Control":"no-store"}
        if status==429:headers["Retry-After"]="60"
        return JSONResponse({"detail":code},status_code=status,headers=headers)
    if not pilot_enabled():
        return reject(404,"pilot_disabled")
    if request.client is None or request.client.host not in ("127.0.0.1","::1","testclient"):
        return reject(403,"pilot_loopback_required")
    if request.method=="POST":
        if request.headers.get("content-type","").split(";")[0].strip().lower()!="application/json":
            return reject(415,"invalid_content_type")
        # Bound actual streamed bytes rather than trusting Content-Length.
        import asyncio
        try:
            async with asyncio.timeout(5):
                chunks=[]
                size=0
                async for chunk in request.stream():
                    size+=len(chunk)
                    if size>4096:return reject(413,"body_too_large")
                    chunks.append(chunk)
                request._body=b"".join(chunks)
        except TimeoutError:
            return reject(408,"body_timeout")
    if request.url.path.startswith("/v1/pilot/identity/"):
        if not security.allow("identity",120):return reject(429,"identity_rate_limited")
    elif request.url.path=="/v1/pilot/login":
        if not security.allow("login",10):
            return reject(429,"login_rate_limited")
    else:
        token=request.headers.get("authorization","")
        key=security.authorize(token[7:]) if token.startswith("Bearer ") else None
        if not key:return reject(401,"session_required")
        if request.url.path!="/v1/pilot/logout" and not security.allow("ask:"+key,20):
            return reject(429,"request_rate_limited")
    response=await call_next(request)
    response.headers["Cache-Control"]="no-store"
    if response.status_code>=500:event("pilot_backend_error")
    return response

# Outer guard: explicitly enabled only in isolated pilot. No forwarded identity.
@app.middleware("http")
async def shared_limits(request: Request, call_next):
    path=request.url.path
    if not path.startswith("/v1/"):
        return await call_next(request)
    def deny(status,code,retry=None):
        event(code)
        headers={"Cache-Control":"no-store"}
        if retry is not None:headers["Retry-After"]=str(retry)
        return JSONResponse({"detail":code},status_code=status,headers=headers)
    if os.getenv("LAVLAH_ENV")=="production":
        if path.startswith("/v1/pilot/"):
            return deny(404,"pilot_disabled")
        return deny(503,"production_disabled")
    if os.getenv("LAVLAH_ENABLE_SHARED_LIMITS")!="1":
        return await call_next(request)
    if not pilot_enabled():
        return deny(503,"limits_configuration")
    if request.client is None or request.client.host not in ("127.0.0.1","::1","testclient"):
        return deny(403,"untrusted_peer")
    if any(k in request.headers for k in ("forwarded","x-forwarded-for","x-real-ip","x-forwarded-host","x-forwarded-proto")):
        return deny(403,"forwarded_identity_denied")
    budgets={"global":300}
    if path=="/v1/pilot/login":
        budgets["login"]=10
    elif path.startswith("/v1/pilot/identity/"):
        try:
            auth=request.headers.get("authorization","")
            if not auth.startswith("Bearer "):raise ValueError()
            claims=validate(auth[7:],configured_key())
            budgets[principal_bucket(claims["sub"])]=20
        except ValueError:
            budgets["invalid_identity"]=20
    elif path.startswith("/v1/pilot/"):
        auth=request.headers.get("authorization","")
        key=security.authorize(auth[7:]) if auth.startswith("Bearer ") else None
        if key:budgets["session:"+key]=20
        else:budgets["anonymous"]=60
    else:
        budgets["directory"]=120
    try:
        async with asyncio.timeout(8):
            await run_in_threadpool(reserve,budgets)
            response=await call_next(request)
    except Limited as exc:
        return deny(429,"shared_rate_limited",exc.retry)
    except TimeoutError:
        return deny(504,"request_deadline")
    except (psycopg.Error,ValueError,KeyError):
        return deny(503,"limits_unavailable")
    response.headers["Cache-Control"]="no-store"
    return response

@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc):
    # Never echo raw input, including passwords and questions.
    return JSONResponse({"detail":"Invalid input"},status_code=422,headers={"Cache-Control":"no-store"})

class PilotLogin(BaseModel):
    model_config=ConfigDict(extra="forbid")
    password: str=Field(min_length=1,max_length=128)

@app.post("/v1/pilot/login")
def pilot_login(body: PilotLogin):
    token=security.login(body.password)
    if not token:raise HTTPException(401,"Invalid credentials")
    return {"token":token,"expires_in":900}

@app.post("/v1/pilot/logout")
def pilot_logout(request: Request):
    security.logout(request.headers["authorization"][7:])
    return {"status":"logged_out"}

def identity_bearer(request):
    token=request.headers.get("authorization","")
    if not token.startswith("Bearer "):raise HTTPException(401,"Identity required")
    return token[7:]

@app.get("/v1/pilot/identity/me")
def identity_me(request: Request):
    try:return profile(identity_bearer(request))
    except ValueError:raise HTTPException(401,"Invalid identity") from None
    except (psycopg.Error,KeyError):raise HTTPException(503,"Identity unavailable") from None

@app.post("/v1/pilot/identity/revoke")
def identity_revoke(request: Request):
    try:revoke_token(identity_bearer(request))
    except ValueError:raise HTTPException(401,"Invalid identity") from None
    except (psycopg.Error,KeyError):raise HTTPException(503,"Identity unavailable") from None
    return {"status":"revoked"}

SQL = """
SELECT organization_id, name, category_slug, description, source_url,
       verified_at, expires_at
FROM lavlah.public_directory
WHERE strpos(lower(name), lower(%s)) > 0
  AND (%s = '' OR category_slug = %s)
ORDER BY lower(name), organization_id
LIMIT %s OFFSET %s
"""

def read_public(sql, params=()):
    # Dedicated server-side login must inherit only lavlah_public_reader.
    mode=os.getenv("LAVLAH_ENV")
    if mode=="production":
        raise psycopg.OperationalError("Production not authorized")
    pilot=mode=="pilot"
    try:
        dsn=checked_dsn("LAVLAH_PUBLIC_DSN","lavlah_integration_login") if pilot else os.environ["LAVLAH_PUBLIC_DSN"]
    except ValueError:raise psycopg.OperationalError("Pilot configuration rejected") from None
    options={"hostaddr":"127.0.0.1"} if pilot else {}
    with closing(psycopg.connect(dsn, row_factory=dict_row,connect_timeout=5,**options)) as conn:
        with conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            conn.execute("SET LOCAL statement_timeout = '3s'")
            if pilot:
                try:check_connection(conn,"lavlah_integration_login")
                except ValueError:raise psycopg.OperationalError("Pilot identity rejected") from None
            conn.execute("SET LOCAL ROLE lavlah_public_reader")
            return conn.execute(sql, params).fetchall()

def search_directory(q, category, limit, offset):
    return read_public(SQL, (q, category, category, limit, offset))

@app.get("/v1/directory/categories")
def categories():
    try:
        rows = read_public("SELECT slug AS category_slug, name FROM lavlah.public_category_names ORDER BY slug")
    except (psycopg.Error, KeyError):
        raise HTTPException(503, "Directory temporarily unavailable") from None
    return {"items": [row["category_slug"] for row in rows], "names": {row["category_slug"]: row["name"] for row in rows}}

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

class PilotQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1,max_length=240)

@app.post("/v1/pilot/ask")
def ask_pilot(body: PilotQuestion, response: Response):
    # Explicit opt-in; no billing and no production exposure.
    if os.environ.get("LAVLAH_ENABLE_PILOT_QA")!="1":
        raise HTTPException(404,"Not found")
    response.headers["Cache-Control"]="no-store"
    try:
        return directory_answer(body.question,search_directory)
    except ValueError:
        raise HTTPException(422,"Invalid question") from None
    except (psycopg.Error,KeyError):
        raise HTTPException(503,"Directory temporarily unavailable") from None

@app.post("/v1/pilot/grounded-ask")
def grounded_ask(body: PilotQuestion, response: Response):
    if os.environ.get("LAVLAH_ENABLE_PILOT_QA")!="1" or os.environ.get("LAVLAH_ENABLE_MOCK_AI")!="1":
        raise HTTPException(404,"Not found")
    response.headers["Cache-Control"]="no-store"
    try:
        result=grounded_answer(body.question,search_directory)
    except ValueError:
        raise HTTPException(422,"Invalid question") from None
    except (psycopg.Error,KeyError):
        raise HTTPException(503,"Directory temporarily unavailable") from None
    # Numeric mock metrics only; never log question, source content or identifiers.
    logging.getLogger("lavlah.mock_usage").info("mock_usage %s",result["usage"])
    return result

class ChatFeedback(BaseModel):
    model_config=ConfigDict(extra="forbid",strict=True)
    usage_id: str=Field(min_length=36,max_length=36)
    rating: int=Field(ge=-1,le=1)

def chat_gate():
    if not identity_chat.enabled():raise HTTPException(404,"Not found")

@app.post("/v1/pilot/identity/chat")
def authenticated_ask(body: PilotQuestion,request: Request):
    chat_gate()
    try:return identity_chat.ask(identity_bearer(request),body.question,search_directory)
    except identity_chat.ChatPrivacy:raise HTTPException(422,"Question rejected by privacy filter") from None
    except identity_chat.ChatLimit:raise HTTPException(429,"Daily mock budget reached",headers={"Retry-After":"60"}) from None
    except ValueError:raise HTTPException(401,"Invalid identity or question") from None
    except (psycopg.Error,KeyError):raise HTTPException(503,"Chat unavailable") from None

@app.post("/v1/pilot/identity/feedback")
def authenticated_feedback(body: ChatFeedback,request: Request):
    chat_gate()
    try:return identity_chat.feedback(identity_bearer(request),body.usage_id,body.rating)
    except ValueError:raise HTTPException(403,"Feedback unavailable") from None
    except (psycopg.Error,KeyError):raise HTTPException(503,"Chat unavailable") from None

# Serve the initial mobile UI on the same origin as the directory API.
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
WEB_DIR = Path(__file__).resolve().parents[1] / "web"
app.mount("/ui", StaticFiles(directory=WEB_DIR), name="ui")

@app.get("/", include_in_schema=False)
def home():
    return FileResponse(WEB_DIR / "index.html")
