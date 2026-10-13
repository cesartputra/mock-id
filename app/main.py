import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from app.controller.verification import router
from app.controller.registration import router as registration_router
from app.config import DATA
from app.model.repository import Repository
from app.services.sessions import SessionService
from app.services.capture_registry import RedisCaptureRegistry
from app.services.pipeline import VerificationService
from app.services.secrets_store import SecretBox
from app.services.auth import AuthService
from app.services.evidence import EvidenceStore, S3PrivateStorage
from app.services.workflow import WorkflowService
from app.services.manual import ManualService
from app.services.slik import SlikService
from app.services.inference_queue import InferenceQueue
from app.controller.auth import router as auth_router
from app.controller.applications import router as applications_router
import os
import re


@asynccontextmanager
async def lifespan(app):
    app.state.repository = Repository(app.state.data_directory)
    app.state.repository.migrate()
    app.state.box = SecretBox(app.state.data_directory)
    app.state.auth = AuthService(app.state.repository, app.state.box)
    storage = (
        S3PrivateStorage(
            os.environ["MOCK_ID_EVIDENCE_BUCKET"], os.getenv("MOCK_ID_S3_ENDPOINT")
        )
        if os.getenv("MOCK_ID_EVIDENCE_BUCKET")
        else None
    )
    app.state.evidence = EvidenceStore(app.state.repository, app.state.box, storage)
    app.state.workflow = WorkflowService(
        app.state.repository, app.state.box, app.state.evidence
    )
    app.state.manual = ManualService(app.state.workflow)
    app.state.slik = SlikService(app.state.workflow)
    app.state.slik.recover_inflight()
    app.state.inference_queue = InferenceQueue()
    registry = (
        RedisCaptureRegistry(
            os.environ["MOCK_ID_REDIS_URL"], os.environ["MOCK_ID_GATEWAY_ID"]
        )
        if os.getenv("MOCK_ID_REDIS_URL")
        else None
    )
    app.state.sessions = SessionService(registry)
    app.state.verifier = VerificationService(app.state.repository)

    async def expire_sessions():
        while True:
            await asyncio.sleep(30)
            app.state.sessions.purge()
            await asyncio.to_thread(app.state.evidence.purge)

    cleanup = asyncio.create_task(expire_sessions())
    try:
        yield
    finally:
        cleanup.cancel()
        try:
            await cleanup
        except asyncio.CancelledError:
            pass
        app.state.sessions.items.clear()
        app.state.inference_queue.close()


def create_app(data_directory=DATA):
    app = FastAPI(
        title="mock-id local identity verification",
        version="3.1.4",
        lifespan=lifespan,
        telemetry={
            "tracing": False,
            "metrics": False,
            "logs": False,
            "operation_spans": False,
            "auto_configure": False,
        },
    )
    app.state.data_directory = data_directory
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=os.getenv(
            "MOCK_ID_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver"
        ).split(","),
    )

    @app.middleware("http")
    async def local_requests(request: Request, call_next):
        if request.method not in [
            "GET",
            "HEAD",
            "OPTIONS",
        ] and request.url.path.startswith("/api/"):
            if request.headers.get("X-Local-Client") != "mock-id":
                return JSONResponse(
                    {"detail": "Gunakan klien lokal mock-id."}, status_code=403
                )
            origin = request.headers.get("origin")
            if origin and origin not in [
                str(request.base_url).rstrip("/"),
                f"http://127.0.0.1:{request.url.port or 80}",
                f"http://localhost:{request.url.port or 80}",
            ]:
                return JSONResponse(
                    {"detail": "Origin tidak diizinkan."}, status_code=403
                )
        content_length = request.headers.get("content-length", "0")
        try:
            if int(content_length) > 32 * 1024 * 1024:
                return JSONResponse(
                    {"detail": "Request melebihi batas 32 MB."}, status_code=413
                )
        except ValueError:
            return JSONResponse(
                {"detail": "Content-Length tidak valid."}, status_code=400
            )
        try:
            path = request.url.path
            if path.startswith("/api/"):
                if (
                    os.getenv("MOCK_ID_MODE", "demo") == "production"
                    and request.url.scheme != "https"
                ):
                    raise HTTPException(
                        400, "API produksi membutuhkan TLS melalui gateway terpercaya."
                    )
                if path in ["/api/auth/login", "/api/auth/signup", "/api/auth/guest"]:
                    bucket = "auth:" + app.state.box.subject(
                        request.client.host if request.client else "local"
                    )
                    app.state.auth.limit(bucket, 20, 60)
                else:
                    header = request.headers.get("Authorization", "")
                    token = (
                        header[7:]
                        if header.startswith("Bearer ")
                        else (
                            request.cookies.get("mock_id_guest")
                            if request.headers.get("X-Workspace-Mode") == "public"
                            else (
                                request.cookies.get("mock_id_session")
                                if request.headers.get("X-Workspace-Mode") == "operator"
                                else request.cookies.get("mock_id_session")
                                or request.cookies.get("mock_id_guest")
                            )
                        )
                    )
                    request.state.actor = app.state.auth.principal(token)
                    request.state.auth_token = token
                    who = request.state.actor
                    if path.startswith("/api/sessions"):
                        if who["role"] not in ["applicant", "admin"]:
                            raise HTTPException(
                                403, "Gunakan akun pemohon untuk capture."
                            )
                        app.state.auth.limit("capture:" + who["id"], 480, 60)
                        match = re.match(r"^/api/sessions/([^/]+)/", path)
                        if match:
                            session = app.state.sessions.get(match[1])
                            if session.owner_id != who["id"]:
                                raise HTTPException(404, "Sesi tidak ditemukan.")
                            if session.application_id:
                                with app.state.repository.connect() as con:
                                    application = app.state.workflow.get(
                                        con, session.application_id
                                    )
                                if application["revision"] != session.revision:
                                    raise HTTPException(
                                        409,
                                        "Sesi capture lama. Gunakan pengambilan terbaru.",
                                    )
                    elif (
                        path.startswith("/api/settings")
                        or path.startswith("/api/policy/")
                        or path.startswith("/api/operator/")
                    ):
                        if who["role"] != "admin":
                            raise HTTPException(
                                403, "Hanya administrator memiliki kewenangan ini."
                            )
                    elif path.startswith("/api/workspace") or path.startswith(
                        "/api/records/"
                    ):
                        if who["role"] not in ["helpdesk", "admin"]:
                            raise HTTPException(
                                403, "Workspace memerlukan akun operator."
                            )
                    elif request.method not in ["GET", "HEAD", "OPTIONS"]:
                        app.state.auth.limit("writes:" + who["id"], 60, 60)
            response = await call_next(request)
        except HTTPException as exc:
            response = JSONResponse(
                {"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers
            )
        except Exception:
            if not request.url.path.startswith("/api/"):
                raise
            error_id = uuid.uuid4().hex[:12]
            logging.getLogger(__name__).error(
                "API failure %s; method %s", error_id, request.method
            )
            response = JSONResponse(
                {
                    "detail": "Server mengalami gangguan. Coba kembali; jika berulang, periksa log server.",
                    "code": "internal_error",
                    "request_id": error_id,
                },
                status_code=500,
            )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    app.include_router(auth_router)
    app.include_router(applications_router)
    app.include_router(router)
    app.include_router(registration_router)
    static = Path(__file__).parent / "view" / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(static / "index.html")

    from fastapi.openapi.utils import get_openapi

    def authenticated_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
        schemes = schema.setdefault("components", {}).setdefault("securitySchemes", {})
        schemes["BearerAuth"] = {"type": "http", "scheme": "bearer"}
        schemes["SessionCookie"] = {
            "type": "apiKey",
            "in": "cookie",
            "name": "mock_id_session",
        }
        schemes["BrowserCookie"] = {
            "type": "apiKey",
            "in": "cookie",
            "name": "mock_id_guest",
        }
        for path, operations in schema["paths"].items():
            if not path.startswith("/api/"):
                continue
            for method, operation in operations.items():
                if method not in ["get", "post", "put", "patch", "delete"]:
                    continue
                if path in ["/api/auth/login", "/api/auth/signup", "/api/auth/guest"]:
                    operation["security"] = [{"APIKeyHeader": []}]
                elif method == "get":
                    operation["security"] = [
                        {"BearerAuth": []},
                        {"SessionCookie": []},
                        {"BrowserCookie": []},
                    ]
                else:
                    operation["security"] = [
                        {"BearerAuth": [], "APIKeyHeader": []},
                        {"SessionCookie": [], "APIKeyHeader": []},
                        {"BrowserCookie": [], "APIKeyHeader": []},
                    ]
        app.openapi_schema = schema
        return schema

    app.openapi = authenticated_openapi
    return app


app = create_app()
