import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from backend.routes import router as api_router
from backend.database import init_db, add_file
import traceback
import httpx
from fastapi import UploadFile, File, HTTPException

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Telegram Drive", docs_url="/docs")

# Mount frontend static files
app.mount("/static", StaticFiles(directory=BASE_DIR / "frontend"), name="static")

# Include API router
app.include_router(api_router, prefix="/api")

# Initialize DB on startup
@app.on_event("startup")
async def startup():
    await init_db()

# Root serves the frontend UI (index.html)
from fastapi.responses import HTMLResponse
import pathlib

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root():
    index_path = pathlib.Path(__file__).resolve().parent / "frontend" / "index.html"
    return HTMLResponse(content=index_path.read_text())