import warnings
warnings.filterwarnings("ignore")

from log_config import configure_logging
configure_logging()  # install root log format before anything else logs

from pathlib import Path
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from routers import chat, training, ledger, auth_request, ledger_merge, audit, model_routes, compliance, llm_traces
from routers import auth as auth_router
from routers import admin_users
from auth_utils import get_current_user

app = FastAPI(title="Training Manager API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 公开路由（无需登录）──────────────────────────────────────────
app.include_router(auth_router.router)

# ── 业务路由（需要登录）──────────────────────────────────────────
_auth = [Depends(get_current_user)]
app.include_router(chat.router,         dependencies=_auth)
app.include_router(training.router,     dependencies=_auth)
app.include_router(ledger.router,       dependencies=_auth)
app.include_router(auth_request.router, dependencies=_auth)
app.include_router(ledger_merge.router, dependencies=_auth)
app.include_router(audit.router,        dependencies=_auth)
app.include_router(compliance.router,   dependencies=_auth)
app.include_router(model_routes.router, dependencies=_auth)

# ── 管理员路由（内部再校验 admin 角色）──────────────────────────
app.include_router(admin_users.router, dependencies=_auth)
app.include_router(llm_traces.router,  dependencies=_auth)


@app.on_event("startup")
def startup():
    from db import init_db
    from model_routes import ensure_model_routes_file
    init_db()
    ensure_model_routes_file()


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ── 托管前端静态文件（生产模式）─────────────────────────────────
_FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"
if _FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIST / "assets")), name="assets")

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):
        return FileResponse(str(_FRONTEND_DIST / "index.html"))
