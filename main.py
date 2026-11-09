import os
import mimetypes
import traceback
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from typing import List, Optional
import httpx
from dotenv import load_dotenv

from database import (
    init_db,
    add_file,
    get_file,
    list_files,
    delete_file,
    create_folder,
    list_folders,
    get_folder,
    get_breadcrumbs,
    delete_folder,
)

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
if not BOT_TOKEN or not CHAT_ID:
    raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in .env")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
FILE_DOWNLOAD_URL = f"https://api.telegram.org/file/bot{BOT_TOKEN}"

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MiB

app = FastAPI(title="TelDrive")

@app.on_event("startup")
async def startup():
    await init_db()

# Serve static directory if it exists
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

def guess_content_type(filename: str) -> str:
    content_type, _ = mimetypes.guess_type(filename)
    if not content_type:
        ext = filename.split(".")[-1].lower() if "." in filename else ""
        ext_map = {
            "mp3": "audio/mpeg",
            "wav": "audio/wav",
            "flac": "audio/flac",
            "aac": "audio/aac",
            "ogg": "audio/ogg",
            "m4a": "audio/mp4",
            "mp4": "video/mp4",
            "webm": "video/webm",
            "mkv": "video/x-matroska",
            "mov": "video/quicktime",
            "pdf": "application/pdf",
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "gif": "image/gif",
            "webp": "image/webp",
            "svg": "image/svg+xml",
            "txt": "text/plain; charset=utf-8",
            "html": "text/html",
            "js": "text/javascript",
            "css": "text/css",
            "json": "application/json",
            "md": "text/markdown",
        }
        content_type = ext_map.get(ext, "application/octet-stream")
    return content_type

@app.get("/", response_class=HTMLResponse)
async def root():
    index_file = Path(__file__).parent / "static" / "index.html"
    if not index_file.exists():
        index_file = Path(__file__).parent / "telegram-drive" / "frontend" / "index.html"
    return HTMLResponse(content=index_file.read_text(encoding="utf-8"))

# Folder Endpoints
@app.get("/folders")
async def api_list_folders(parent_id: Optional[int] = Query(None)):
    return await list_folders(parent_id)

@app.post("/folders")
async def api_create_folder(
    name: str = Form(...),
    parent_id: Optional[int] = Form(None)
):
    folder_id = await create_folder(name.strip(), parent_id)
    folder = await get_folder(folder_id)
    return {"status": "success", "folder": folder}

@app.delete("/folders/{folder_id}")
async def api_delete_folder(folder_id: int):
    success = await delete_folder(folder_id)
    if not success:
        raise HTTPException(status_code=404, detail="Folder not found")
    return {"status": "deleted"}

@app.get("/breadcrumbs")
async def api_breadcrumbs(folder_id: Optional[int] = Query(None)):
    return await get_breadcrumbs(folder_id)

# File Endpoints
@app.get("/files")
async def get_files(
    search: Optional[str] = Query(None),
    folder_id: Optional[int] = Query(None)
):
    rows = await list_files(search, folder_id)
    files = []
    for r in rows:
        files.append({
            "id": r["id"],
            "filename": r["file_name"],
            "file_name": r["file_name"],
            "size": r["file_size"],
            "file_size": r["file_size"],
            "folder_id": r.get("folder_id"),
            "content_type": guess_content_type(r["file_name"]),
            "uploaded_at": r["uploaded_at"],
        })
    return files

@app.post("/upload")
async def upload_file(
    file: Optional[UploadFile] = File(None),
    files: Optional[List[UploadFile]] = File(None),
    folder_id: Optional[int] = Form(None)
):
    upload_list = []
    if file:
        upload_list.append(file)
    if files:
        upload_list.extend(files)

    if not upload_list:
        raise HTTPException(status_code=400, detail="No files uploaded")

    results = []
    tg_url = f"{TELEGRAM_API_URL}/sendDocument"

    async with httpx.AsyncClient(timeout=120.0) as client:
        for upload in upload_list:
            try:
                content = await upload.read()
                file_size = len(content)
                if file_size > MAX_FILE_SIZE:
                    results.append({"filename": upload.filename, "error": "Exceeds 50MB limit"})
                    continue

                files_payload = {"document": (upload.filename, content)}
                data = {"chat_id": CHAT_ID}
                response = await client.post(tg_url, data=data, files=files_payload)

                if response.status_code != 200:
                    results.append({"filename": upload.filename, "error": response.text})
                    continue

                res_json = response.json()
                if not res_json.get("ok"):
                    results.append({"filename": upload.filename, "error": res_json.get("description")})
                    continue

                msg = res_json.get("result", {})
                file_id = None
                if "document" in msg:
                    file_id = msg["document"]["file_id"]
                elif "photo" in msg:
                    file_id = msg["photo"][-1]["file_id"]
                elif "audio" in msg:
                    file_id = msg["audio"]["file_id"]
                elif "video" in msg:
                    file_id = msg["video"]["file_id"]

                if not file_id:
                    results.append({"filename": upload.filename, "error": "No file_id in Telegram response"})
                    continue

                record_id = await add_file(upload.filename, file_id, file_size, folder_id)
                results.append({
                    "id": record_id,
                    "filename": upload.filename,
                    "file_size": file_size,
                    "folder_id": folder_id,
                    "status": "success"
                })
            except Exception as e:
                results.append({"filename": upload.filename, "error": str(e)})

    return {"results": results, "status": "success"}

async def _stream_file_from_telegram(file_id: int, inline: bool):
    record = await get_file(file_id)
    if not record:
        raise HTTPException(status_code=404, detail="File not found")

    telegram_file_id = record["file_id"]
    filename = record["file_name"]
    content_type = guess_content_type(filename)
    disposition = "inline" if inline else "attachment"

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(f"{TELEGRAM_API_URL}/getFile", params={"file_id": telegram_file_id})
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Failed to fetch file info from Telegram")
        json_resp = resp.json()
        if not json_resp.get("ok"):
            raise HTTPException(status_code=502, detail="Telegram API error while fetching file info")

        file_path = json_resp["result"]["file_path"]
        download_url = f"{FILE_DOWNLOAD_URL}/{file_path}"

        async def file_iterator():
            async with client.stream("GET", download_url) as stream:
                async for chunk in stream.aiter_bytes(chunk_size=16384):
                    yield chunk

        headers = {
            "Content-Disposition": f'{disposition}; filename="{filename}"',
            "Content-Type": content_type,
            "Accept-Ranges": "bytes",
        }
        return StreamingResponse(file_iterator(), media_type=content_type, headers=headers)

@app.get("/files/{file_id}/download")
@app.get("/api/download/{file_id}")
async def download_file_route(file_id: int):
    return await _stream_file_from_telegram(file_id, inline=False)

@app.get("/files/{file_id}/preview")
@app.get("/api/preview/{file_id}")
async def preview_file_route(file_id: int):
    return await _stream_file_from_telegram(file_id, inline=True)

@app.delete("/files/{file_id}")
@app.delete("/api/files/{file_id}")
async def delete_file_route(file_id: int):
    success = await delete_file(file_id)
    if not success:
        raise HTTPException(status_code=404, detail="File not found")
    return {"status": "deleted"}
