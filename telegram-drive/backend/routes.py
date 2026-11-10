import json
import mimetypes
import traceback
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

# Chunked Upload
@router.post("/upload-chunk")
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

        async with httpx.AsyncClient(timeout=180.0) as client:
            files_payload = {"document": (part_filename, content)}
            data = {"chat_id": TELEGRAM_CHAT_ID}
            response = await client.post(tg_url, data=data, files=files_payload)

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

@router.post("/save-file-metadata")
async def save_file_metadata(
    file_name: str = Form(...),
    file_uuid: str = Form(...),
    file_size: int = Form(...),
    total_chunks: int = Form(...),
    chunks: str = Form(...),
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
            "total_chunks": r.get("total_chunks", 1),
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
        try:
            doc = await send_document(content, upload.filename, upload.content_type or "application/octet-stream")
            file_id = doc["file_id"]
            file_size = doc.get("file_size", len(content))
            chunks_json = json.dumps([file_id])
            record_id = await add_file(upload.filename, file_id, file_size, folder_id, total_chunks=1, chunks=chunks_json)
            results.append({"filename": upload.filename, "id": record_id, "folder_id": folder_id, "status": "uploaded"})
        except Exception as e:
            results.append({"filename": upload.filename, "error": str(e)})

    return JSONResponse(content={"results": results, "status": "success"})

async def _stream_file(file_id: int, inline: bool):
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

    async def generator():
        async with httpx.AsyncClient(timeout=120.0) as client:
            for tg_file_id in chunk_list:
                resp = await client.get(f"{TELEGRAM_API_URL}/getFile", params={"file_id": tg_file_id})
                if resp.status_code != 200 or not resp.json().get("ok"):
                    raise HTTPException(status_code=502, detail="Failed to fetch chunk info from Telegram")

                file_path = resp.json()["result"]["file_path"]
                download_url = f"{FILE_DOWNLOAD_URL}/{file_path}"

                async with client.stream("GET", download_url) as stream:
                    async for chunk in stream.aiter_bytes(chunk_size=16384):
                        yield chunk

    headers = {
        "Content-Disposition": f'{disposition}; filename="{filename}"',
        "Content-Type": content_type,
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size)
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
