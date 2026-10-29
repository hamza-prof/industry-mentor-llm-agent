import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlmodel import Session

from app import kb
from app import prompts as prompt_store
from app.api import ApiError, comments, documents, prompts, reviews
from app.api import kb as kb_api
from app.config import Settings, get_settings
from app.db import init_db, make_engine
from app.llm import get_vision_model
from app.runner import recover_stuck


def create_app(settings: Settings | None = None) -> FastAPI:
    app_log = logging.getLogger("app")  # LLM usage lines; uvicorn only configures its own loggers
    if not app_log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s %(message)s"))
        app_log.addHandler(handler)
        app_log.setLevel(logging.INFO)
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        (settings.data_dir / "uploads").mkdir(parents=True, exist_ok=True)
        app.state.engine = make_engine(settings)
        init_db(app.state.engine)
        with Session(app.state.engine) as session:
            prompt_store.seed_defaults(session)
        recover_stuck(app.state.engine)
        yield
        app.state.engine.dispose()

    app = FastAPI(title="Industry Mentor Review Assistant", lifespan=lifespan)
    app.state.settings = settings
    app.state.kb_store = None  # built on first use (api.kb.kb_store); tests may inject one
    app.state.review_models = None  # tests inject fake models; None = build from settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(ApiError)
    async def api_error(_: Request, e: ApiError):
        return JSONResponse({"detail": e.detail, "code": e.code, **e.extra}, status_code=e.status)

    @app.get("/api/health")
    def health() -> dict:
        s = app.state.settings
        with Session(app.state.engine) as session:
            reindex = kb.needs_reindex(session, s)
        return {
            "status": "ok",
            "llm_configured": s.llm_configured,
            "vision_configured": get_vision_model(s) is not None,
            "kb_configured": s.embeddings_configured,
            "kb_needs_reindex": reindex,
            "max_upload_mb": s.max_upload_mb,
        }

    app.include_router(documents.router)
    app.include_router(prompts.router)
    app.include_router(kb_api.router)
    app.include_router(reviews.router)
    app.include_router(comments.router)
    return app


app = create_app()
