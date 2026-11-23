from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import router
from app.config import get_settings
from app.keitaro.client import KeitaroError
from app.logs import setup_logging
from app.services.campaigns import StorageError, ValidationError
from app.services.editor import NotFound

STATIC = Path(__file__).parent / "static"

setup_logging(get_settings().log_level)
app = FastAPI(title="Keitaro campaign tool")
app.include_router(router)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.exception_handler(ValidationError)
def _validation(_: Request, error: ValidationError):
    return JSONResponse(status_code=400, content={"detail": str(error)})


@app.exception_handler(NotFound)
def _not_found(_: Request, error: NotFound):
    return JSONResponse(status_code=404, content={"detail": str(error)})


@app.exception_handler(StorageError)
def _storage(_: Request, error: StorageError):
    return JSONResponse(status_code=503, content={"detail": str(error)})


@app.exception_handler(KeitaroError)
def _keitaro(_: Request, error: KeitaroError):
    # 4xx от Keitaro отдаём как есть, остальное — 502: проблема на стороне трекера.
    status = error.status if 400 <= error.status < 500 else 502
    return JSONResponse(status_code=status, content={"detail": f"Keitaro: {error.message}"})


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/campaigns/{campaign_id}", include_in_schema=False)
def editor_page(campaign_id: int):
    return FileResponse(STATIC / "editor.html")
