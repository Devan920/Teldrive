import os
import json
import mimetypes
import traceback
from contextlib import asynccontextmanager
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
    toggle_star_file,
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

httpx_client: Optional[httpx.AsyncClient] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global httpx_client
    await init_db()
    httpx_client = httpx.AsyncClient(
        http2=True,
        limits=httpx.Limits(max_keepalive_connections=30, max_connections=60),
        timeout=httpx.Timeout(300.0, connect=30.0)
    )
    yield
    if httpx_client:
        await httpx_client.aclose()

app = FastAPI(title="TelDrive", lifespan=lifespan)

# Serve static directory if present
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
    index_file = Path(__file__).parent / "frontend" / "index.html"
    if not index_file.exists():
        index_file = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(content=index_file.read_text(encoding="utf-8"))

# Folder Management Routes
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

# High-Speed Concurrent Chunked Upload Route
@app.post("/upload-chunk")
async def upload_chunk(
    file: UploadFile = File(...),
    chunk_index: int = Form(...),
    total_chunks: int = Form(...),
    file_uuid: str = Form(...)
):
    try:
        content = await file.read()
        part_filename = f"{file_uuid}_part_{chunk_index}"
        tg_url = f"{TELEGRAM_API_URL}/sendDocument"

        files_payload = {"document": (part_filename, content)}
        data = {"chat_id": CHAT_ID}

        # Reuse global HTTP/2 connection pool
        response = await httpx_client.post(tg_url, data=data, files=files_payload)

        if response.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Telegram API Rejected Chunk: {response.text}")

        res_json = response.json()
        if not res_json.get("ok"):
            raise HTTPException(status_code=502, detail=f"Telegram Error: {res_json.get('description')}")

        msg = res_json.get("result", {})
        tg_file_id = None
        if "document" in msg:
            tg_file_id = msg["document"]["file_id"]
        elif "photo" in msg:
            tg_file_id = msg["photo"][-1]["file_id"]
        elif "audio" in msg:
            tg_file_id = msg["audio"]["file_id"]
        elif "video" in msg:
            tg_file_id = msg["video"]["file_id"]

        if not tg_file_id:
            raise HTTPException(status_code=500, detail="Could not extract tg_file_id from Telegram response")

        return {
            "status": "success",
            "chunk_index": chunk_index,
            "total_chunks": total_chunks,
            "tg_file_id": tg_file_id
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/save-file-metadata")
async def save_file_metadata(
    file_name: str = Form(...),
    file_uuid: str = Form(...),
    file_size: int = Form(...),
    total_chunks: int = Form(...),
    chunks: str = Form(...),  # JSON string array of Telegram file_ids
    folder_id: Optional[int] = Form(None)
):
    try:
        record_id = await add_file(
            file_name=file_name,
            file_id=file_uuid,
            file_size=file_size,
            folder_id=folder_id,
            total_chunks=total_chunks,
            chunks=chunks
        )
        return {"status": "success", "id": record_id}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# Toggle Star Route
@app.post("/files/{file_id}/star")
@app.post("/toggle-star/{file_id}")
async def toggle_star(file_id: int):
    result = await toggle_star_file(file_id)
    if not result:
        raise HTTPException(status_code=404, detail="File not found")
    return {"status": "success", **result}

# File Listing
@app.get("/files")
async def get_files(
    search: Optional[str] = Query(None),
    folder_id: Optional[int] = Query(None),
    is_starred: Optional[bool] = Query(False),
    all_files: Optional[bool] = Query(False)
):
    rows = await list_files(search=search, folder_id=folder_id, is_starred=is_starred, all_files=all_files)
    files = []
    for r in rows:
        files.append({
            "id": r["id"],
            "filename": r["file_name"],
            "file_name": r["file_name"],
            "size": r["file_size"],
            "file_size": r["file_size"],
            "folder_id": r.get("folder_id"),
            "total_chunks": r.get("total_chunks", 1),
            "is_starred": bool(r.get("is_starred", 0)),
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

    for upload in upload_list:
        try:
            content = await upload.read()
            file_size = len(content)

            files_payload = {"document": (upload.filename, content)}
            data = {"chat_id": CHAT_ID}
            response = await httpx_client.post(tg_url, data=data, files=files_payload)

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

            chunks_json = json.dumps([file_id])
            record_id = await add_file(upload.filename, file_id, file_size, folder_id, total_chunks=1, chunks=chunks_json)
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

# Sequential Chunk Streaming Generator
async def _stream_file_from_telegram(file_id: int, inline: bool):
    record = await get_file(file_id)
    if not record:
        raise HTTPException(status_code=404, detail="File not found")

    filename = record["file_name"]
    file_size = record["file_size"]
    content_type = guess_content_type(filename)
    disposition = "inline" if inline else "attachment"

    chunk_list = []
    if record.get("chunks"):
        try:
            chunk_list = json.loads(record["chunks"])
        except Exception:
            chunk_list = []

    if not chunk_list:
        chunk_list = [record["file_id"]]

    async def file_iterator():
        for tg_file_id in chunk_list:
            resp = await httpx_client.get(f"{TELEGRAM_API_URL}/getFile", params={"file_id": tg_file_id})
            if resp.status_code != 200 or not resp.json().get("ok"):
                raise HTTPException(status_code=502, detail="Failed to fetch chunk info from Telegram")

            file_path = resp.json()["result"]["file_path"]
            download_url = f"{FILE_DOWNLOAD_URL}/{file_path}"

            async with httpx_client.stream("GET", download_url) as stream:
                async for chunk in stream.aiter_bytes(chunk_size=16384):
                    yield chunk

    headers = {
        "Content-Disposition": f'{disposition}; filename="{filename}"',
        "Content-Type": content_type,
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size)
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
