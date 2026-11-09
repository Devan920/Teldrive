import mimetypes
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from typing import List, Optional
import httpx

from .config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from .database import (
    init_db,
    add_file,
    list_files,
    get_file,
    delete_file,
    create_folder,
    list_folders,
    get_folder,
    get_breadcrumbs,
    delete_folder,
)
from .telegram import send_document, get_file_path, stream_telegram_file, MAX_FILE_SIZE, TELEGRAM_API_URL, FILE_DOWNLOAD_URL

router = APIRouter()

def guess_content_type(filename: str) -> str:
    content_type, _ = mimetypes.guess_type(filename)
    if not content_type:
        ext = filename.split(".")[-1].lower() if "." in filename else ""
        ext_map = {
            "mp3": "audio/mpeg", "wav": "audio/wav", "flac": "audio/flac", "aac": "audio/aac",
            "ogg": "audio/ogg", "m4a": "audio/mp4", "mp4": "video/mp4", "webm": "video/webm",
            "mkv": "video/x-matroska", "mov": "video/quicktime", "pdf": "application/pdf",
            "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif",
            "webp": "image/webp", "svg": "image/svg+xml", "txt": "text/plain; charset=utf-8",
            "html": "text/html", "js": "text/javascript", "css": "text/css", "json": "application/json",
            "md": "text/markdown"
        }
        content_type = ext_map.get(ext, "application/octet-stream")
    return content_type

@router.on_event("startup")
async def startup_db():
    await init_db()

# Folders
@router.get("/folders")
async def api_list_folders(parent_id: Optional[int] = Query(None)):
    return await list_folders(parent_id)

@router.post("/folders")
async def api_create_folder(
    name: str = Form(...),
    parent_id: Optional[int] = Form(None)
):
    folder_id = await create_folder(name.strip(), parent_id)
    folder = await get_folder(folder_id)
    return {"status": "success", "folder": folder}

@router.delete("/folders/{folder_id}")
async def api_delete_folder(folder_id: int):
    success = await delete_folder(folder_id)
    if not success:
        raise HTTPException(status_code=404, detail="Folder not found")
    return {"status": "deleted"}

@router.get("/breadcrumbs")
async def api_breadcrumbs(folder_id: Optional[int] = Query(None)):
    return await get_breadcrumbs(folder_id)

# Files
@router.get("/files")
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

@router.post("/upload")
async def upload_files(
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
    for upload in upload_list:
        content = await upload.read()
        if len(content) > MAX_FILE_SIZE:
            results.append({"filename": upload.filename, "error": "Exceeds 50MB limit"})
            continue
        try:
            doc = await send_document(content, upload.filename, upload.content_type or "application/octet-stream")
            file_id = doc["file_id"]
            file_size = doc.get("file_size", len(content))
            record_id = await add_file(upload.filename, file_id, file_size, folder_id)
            results.append({"filename": upload.filename, "id": record_id, "folder_id": folder_id, "status": "uploaded"})
        except Exception as e:
            results.append({"filename": upload.filename, "error": str(e)})

    return JSONResponse(content={"results": results, "status": "success"})

async def _stream_file(file_id: int, inline: bool):
    record = await get_file(file_id)
    if not record:
        raise HTTPException(status_code=404, detail="File not found")
    try:
        file_path = await get_file_path(record["file_id"])
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    filename = record["file_name"]
    content_type = guess_content_type(filename)
    disposition = "inline" if inline else "attachment"

    async def generator():
        async for chunk in stream_telegram_file(file_path):
            yield chunk

    headers = {
        "Content-Disposition": f'{disposition}; filename="{filename}"',
        "Content-Type": content_type,
        "Accept-Ranges": "bytes",
    }
    return StreamingResponse(generator(), media_type=content_type, headers=headers)

@router.get("/download/{file_id}")
async def download_file_route(file_id: int):
    return await _stream_file(file_id, inline=False)

@router.get("/preview/{file_id}")
async def preview_file_route(file_id: int):
    return await _stream_file(file_id, inline=True)

@router.delete("/files/{file_id}")
async def delete_record(file_id: int):
    deleted = await delete_file(file_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="File not found")
    return {"status": "deleted"}
