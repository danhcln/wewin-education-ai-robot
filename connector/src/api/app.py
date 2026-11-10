"""
FastAPI Application Entry for WeWIN AI Website Connector.
"""
from contextlib import asynccontextmanager
import asyncio
from contextlib import suppress
from pathlib import Path, PurePosixPath
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings, BASE_DIR
from src.utils.logger import logger
from src.storage.db import get_db
from src.crawler.curated_seeds import get_curated_seeds
from src.api.routes import router

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle event: ensures database is seeded on startup."""
    logger.info("Initializing WeWIN AI Connector Backend...")
    db = get_db()
    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM pages;")
        count = cur.fetchone()[0]
        if count == 0:
            logger.info("Empty database detected. Auto-seeding curated WeWIN knowledge...")
            seeds = get_curated_seeds()
            db.index_records(seeds)
            logger.info(f"Auto-seeded {len(seeds)} verified baseline articles.")
        else:
            logger.info(f"Database ready with {count} indexed articles.")

    # Start auto-sync scheduler if enabled in configuration
    scheduler = None
    if settings.AUTO_SYNC_ENABLED and settings.SYNC_SCHEDULE_ARMED and settings.SYNC_SCHEDULER_OWNER == "internal":
        from src.sync.scheduler import get_scheduler
        scheduler = get_scheduler()
        scheduler.start()
        logger.info("Internal auto-sync armed for 08:00/20:00 Asia/Bangkok with persisted catch-up.")

    # Local TTL cleanup, not Auto-Sync: no HTTP requests or knowledge writes.
    from src.media.routes import expire_media_cache
    media_cleanup=asyncio.create_task(expire_media_cache())
    from src.media.device_control import get_control
    from src.media.orchestration import get_session
    control = get_control()
    get_session()
    try:
        control.load()
        # Presence/control is independent of legacy capture opt-in.
        control.start()
    except (OSError, ValueError):
        logger.warning('WEWIN_MEDIA control_not_started; review local configuration.')
    try:
        yield
    finally:
        get_session().shutdown()
        control.stop()
        from src.streaming.service import get_service
        get_service().stop()
        media_cleanup.cancel()
        with suppress(asyncio.CancelledError):await media_cleanup

    if scheduler:
        await scheduler.stop()
    logger.info("Shutting down WeWIN AI Connector Backend...")

def create_app(static_dir: Path | None = None) -> FastAPI:
    app = FastAPI(
        title="WeWIN AI Website Connector",
        description="Backend API and MCP Tool Server connecting XiaoZhi ESP32 AI Assistant to https://wewin.edu.vn/",
        version="1.0.0",
        lifespan=lifespan
    )

    # The Control Center and Vite proxy use same-origin requests by default.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "X-Admin-Token", "Content-Type"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin" if request.url.path=="/media" else "same-origin"
        if request.url.path.startswith(("/api/", "/sync")):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Pydantic's default errors echo input, including submitted credentials.
        errors = [{key: item[key] for key in ("type", "loc", "msg")} for item in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})

    app.include_router(router)
    from src.media.education_routes import router as education_router
    app.include_router(education_router)
    from src.api.browser_routes import router as browser_router
    app.include_router(browser_router)
    from src.media.routes import router as media_router
    app.include_router(media_router)
    from src.media.auto_routes import router as auto_media_router
    app.include_router(auto_media_router)
    from src.streaming.routes import router as stream_router
    app.include_router(stream_router)
    from src.media.voice_routes import router as voice_media_router
    app.include_router(voice_media_router)
    from src.devices.routes import router as devices_router
    app.include_router(devices_router)
    from src.mcp.mcp_server import mcp_router
    app.include_router(mcp_router)

    # Mount frontend static distribution if built
    dist_dir = (static_dir or BASE_DIR / "frontend" / "dist").resolve()
    if dist_dir.exists():
        spa_routes = {"", "assistants", "robots", "knowledge", "sync", "mcp-tools", "logs", "settings", "media"}
        public_files = {"index.html", "favicon.png", "favicon.svg", "favicon.ico", "icons.svg", "wewin_icon.png", "wewin_logo.png", "wewin_mascot.png"}
        asset_extensions = {".js", ".css", ".png", ".svg", ".ico", ".jpg", ".jpeg", ".webp", ".woff", ".woff2", ".ttf"}

        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_spa(full_path: str):
            # Reject both POSIX traversal and Windows paths/ADS; '%' also rejects
            # double-encoded input that another layer might decode differently.
            if any(char in full_path for char in ("\\", ":", "%", "\x00")):
                raise HTTPException(status_code=404)
            parts = full_path.split("/")
            if any(part in (".", "..") or part.startswith(".") for part in parts):
                raise HTTPException(status_code=404)
            route = full_path.rstrip("/")
            if route in spa_routes:
                requested = "index.html"
            elif full_path in public_files:
                requested = full_path
            elif len(parts) > 1 and parts[0] == "assets" and PurePosixPath(full_path).suffix.lower() in asset_extensions:
                requested = full_path
            else:
                raise HTTPException(status_code=404)
            try:
                target = (dist_dir / requested).resolve(strict=True)
            except (OSError, ValueError, RuntimeError):
                raise HTTPException(status_code=404) from None
            # resolve() also catches symlinks and Windows junctions escaping dist.
            if not target.is_relative_to(dist_dir) or not target.is_file():
                raise HTTPException(status_code=404)
            if target.name != "index.html" and target.suffix.lower() not in asset_extensions:
                raise HTTPException(status_code=404)
            return FileResponse(target, headers={"Cache-Control": "no-cache"} if requested == "index.html" else None)

    return app

app = create_app()
