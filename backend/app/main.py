from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import ApiError, documents
from app.config import Settings, get_settings
from app.db import init_db, make_engine


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        (settings.data_dir / "uploads").mkdir(parents=True, exist_ok=True)
        app.state.engine = make_engine(settings)
        init_db(app.state.engine)
        yield
        app.state.engine.dispose()

    app = FastAPI(title="Industry Mentor Review Assistant", lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(ApiError)
    async def api_error(_: Request, e: ApiError):
        return JSONResponse({"detail": e.detail, "code": e.code}, status_code=e.status)

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "llm_configured": settings.llm_configured}

    app.include_router(documents.router)
    return app


app = create_app()
