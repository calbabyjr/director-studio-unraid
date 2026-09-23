from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import build_api_router
from .config import settings
from .core.jobs import close_execution_runtimes, recover_interrupted_jobs
from .runtime_paths import runtime_paths

# Import pipelines package so pipelines register themselves
from . import pipelines as _pipelines  # noqa: F401

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("director_studio")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    patrol_task: asyncio.Task | None = None
    review_task: asyncio.Task | None = None
    try:
        recovered = await recover_interrupted_jobs()
        if recovered:
            logger.info("recovered %d interrupted jobs on startup", len(recovered))
        if getattr(settings, "director_memory_check_enabled", True):
            from .core.projects.director_patrol import memory_patrol_loop

            patrol_task = asyncio.create_task(memory_patrol_loop())
            logger.info(
                "director memory patrol every %ss",
                getattr(settings, "director_memory_check_sec", 1800),
            )
        from .core.projects.material_review_worker import material_review_loop

        review_task = asyncio.create_task(material_review_loop())
        yield
    finally:
        for task in (patrol_task, review_task):
            if task is None:
                continue
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await close_execution_runtimes()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Director Studio",
        version="0.2.0",
        description="Extensible pre-production asset studio (pipelines + library + jobs).",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(build_api_router())

    frontend_dist = settings.frontend_dist
    if frontend_dist.is_dir():
        @app.get("/mobile", include_in_schema=False)
        async def mobile_entrypoint() -> FileResponse:
            return FileResponse(frontend_dist / "index.html")

        app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run(
        app if runtime_paths.frozen else "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=not runtime_paths.frozen,
    )


if __name__ == "__main__":
    run()
