import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from app.controller.verification import router
from app.controller.registration import router as registration_router
from app.config import DATA
from app.model.repository import Repository
from app.services.sessions import SessionService
from app.services.pipeline import VerificationService


@asynccontextmanager
async def lifespan(app):
    app.state.repository = Repository(app.state.data_directory)
    app.state.sessions = SessionService()
    app.state.verifier = VerificationService(app.state.repository)
    async def expire_sessions():
        while True:
            await asyncio.sleep(30)
            app.state.sessions.purge()
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


def create_app(data_directory=DATA):
    app = FastAPI(title='mock-id local identity verification', version='2.3.1', lifespan=lifespan,
                  telemetry={'tracing': False, 'metrics': False, 'logs': False, 'operation_spans': False, 'auto_configure': False})
    app.state.data_directory = data_directory
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])

    @app.middleware('http')
    async def local_requests(request: Request, call_next):
        if request.method not in ['GET', 'HEAD', 'OPTIONS'] and request.url.path.startswith('/api/'):
            if request.headers.get('X-Local-Client') != 'mock-id':
                return JSONResponse({'detail': 'Gunakan klien lokal mock-id.'}, status_code=403)
            origin = request.headers.get('origin')
            if origin and origin not in [f'http://127.0.0.1:{request.url.port or 80}', f'http://localhost:{request.url.port or 80}']:
                return JSONResponse({'detail': 'Origin tidak diizinkan.'}, status_code=403)
        content_length = request.headers.get('content-length', '0')
        try:
            if int(content_length) > 32 * 1024 * 1024:
                return JSONResponse({'detail': 'Request melebihi batas 32 MB.'}, status_code=413)
        except ValueError:
            return JSONResponse({'detail': 'Content-Length tidak valid.'}, status_code=400)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Cache-Control'] = 'no-store'
        return response

    app.include_router(router)
    app.include_router(registration_router)
    static = Path(__file__).parent / 'view' / 'static'
    app.mount('/static', StaticFiles(directory=static), name='static')

    @app.get('/', include_in_schema=False)
    def index():
        return FileResponse(static / 'index.html')
    return app


app = create_app()
