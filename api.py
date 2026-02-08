import asyncio
from pathlib import Path
from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from .database import init_db, close_db
from .core.tts_manager import tts_manager


def _maybe_load_call_me_config_for_standalone() -> None:
    """Ensure call_me_service.config is populated when running standalone.

    When running via MaiBot plugin lifecycle, CallMeStartHandler will call
    call_me_service.configure(host, port, plugin_config). But when running
    `uvicorn plugins.call_me.api:app` directly, that injection does not happen.

    This function loads plugins/call_me/config.toml only if the service has no
    config yet.
    """

    from pathlib import Path
    import logging

    logger = logging.getLogger("call_me_api")

    try:
        from .core.service import call_me_service
    except Exception as e:
        logger.warning(f"[CallMe] Cannot import call_me_service: {e}")
        return

    existing = getattr(call_me_service, "config", None)
    if isinstance(existing, dict) and existing:
        return

    config_path = Path(__file__).resolve().parent / "config.toml"
    if not config_path.exists():
        logger.info(f"[CallMe] Standalone: config.toml not found at {config_path}")
        return

    try:
        import tomllib  # py>=3.11

        with config_path.open("rb") as f:
            cfg = tomllib.load(f)
    except Exception as e:
        logger.warning(f"[CallMe] Standalone: failed to load config.toml: {e}")
        return

    server = cfg.get("server", {}) if isinstance(cfg, dict) else {}
    host = server.get("host", "127.0.0.1") if isinstance(server, dict) else "127.0.0.1"
    port = server.get("port", 8989) if isinstance(server, dict) else 8989

    call_me_service.configure(host, port, cfg)
    logger.info(f"[CallMe] Standalone: loaded config.toml ({host}:{port})")


# 生命周期管理
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时初始化数据库
    _maybe_load_call_me_config_for_standalone()
    await init_db()
    yield
    # 关闭时清理
    await tts_manager.close()
    await close_db()


def create_app() -> FastAPI:
    app = FastAPI(title="Call Me Plugin API", lifespan=lifespan)
    plugin_dir = Path(__file__).resolve().parent
    static_dir = plugin_dir / "static"
    index_html = static_dir / "index.html"

    # 允许 CORS (由配置控制，暂时全开)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    async def root():
        if index_html.exists():
            return FileResponse(index_html)
        return {"message": "Call Me Plugin API is running", "docs": "/docs", "health": "/health"}

    @app.get("/health")
    async def health_check():
        return {"status": "ok", "service": "call_me_plugin"}

    # 注册 API 路由
    from .routers import assets, presets, avatar_map, avatar_characters

    app.include_router(assets.router)
    app.include_router(presets.router)
    app.include_router(avatar_map.router)
    app.include_router(avatar_characters.router)

    # 注册 WebSocket 路由
    from .websocket_handler import router as ws_router

    app.include_router(ws_router)

    # 前端静态资源挂载（插件启动后可直接访问页面）
    assets_dir = static_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="call_me_assets")

    # SPA fallback：让 /settings 等前端路由直接可访问。
    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        if (
            not index_html.exists()
            or full_path.startswith("api/")
            or full_path.startswith("docs")
            or full_path.startswith("redoc")
            or full_path.startswith("openapi.json")
            or full_path.startswith("ws/")
        ):
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(index_html)

    return app


app = create_app()
