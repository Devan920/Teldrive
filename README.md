# Virtual Cloud Storage

A lightweight web application that uses **Telegram** as the backend storage for uploaded files.

## Features
- Drag‑and‑drop multi‑file upload with progress indication.
- Files are sent to a private Telegram channel via the Bot API.
- Metadata (original filename, Telegram `file_id`, size, MIME type, upload timestamp) stored in SQLite.
- Dashboard to list, search, download, and delete files.
- Pure FastAPI backend, no external DB server needed.
- Front‑end built with vanilla JavaScript and Tailwind CSS (via CDN).

## Tech Stack
- **Backend:** Python 3.11+, FastAPI, Uvicorn, httpx, python‑multipart, aiosqlite, python‑dotenv
- **Database:** SQLite (`files.db` created automatically)
- **Frontend:** Tailwind CSS (CDN), vanilla JS, responsive layout
- **Telegram Integration:** Bot API (`sendDocument`, `getFile`)

## Project Structure
```
├─ main.py               # FastAPI app, routes & static mounting
├─ database.py           # SQLite schema & helper functions
├─ requirements.txt      # Python dependencies
├─ .env.example          # Environment variables template
├─ static/
│   └─ index.html        # Single‑page UI dashboard
└─ README.md             # This file
```

## Setup
1. **Clone the repository** (or copy the files into a folder).
2. **Create a virtual environment** (optional but recommended):
   ```bash
   python -m venv venv
   source venv/Scripts/activate   # Windows PowerShell
   ```
3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
4. **Configure Telegram credentials**:
   - Create a Telegram bot via [@BotFather](https://t.me/BotFather) and obtain its token.
   - Add the bot to a private channel you own and note the channel's numeric ID (use @username_to_id bot if needed).
   - Copy `.env.example` to `.env` and fill in the values:
     ```
     TELEGRAM_BOT_TOKEN=YOUR_BOT_TOKEN
     TELEGRAM_CHAT_ID=YOUR_CHANNEL_ID
     ```
5. **Run the application**:
   ```bash
   uvicorn main:app --reload
   ```
   The API will be available at `http://127.0.0.1:8000` and the dashboard at the same URL.

## Usage
- **Upload** files by dragging them onto the drop zone or clicking to select.
- **Search** using the input box; filtering is performed server‑side.
- **Download** a file by clicking the *Download* link; the backend streams the file directly from Telegram.
- **Delete** a record with the *Delete* button (metadata only; the file remains on Telegram).

## Notes & Limitations
- Telegram enforces a **50 MiB** per‑file limit. Files larger than this are rejected with a friendly error message.
- Deleting a record does **not** delete the file from the Telegram channel (Telegram API does not provide a delete‑file endpoint). The record can be re‑created by re‑uploading.
- The SQLite database (`files.db`) is created in the working directory on first run.
- For production, consider:
  - Using a proper ASGI server (e.g., `gunicorn` with `uvicorn` workers).
  - Securing the API (auth, rate limiting).
  - Running behind HTTPS.

## License
MIT – feel free to adapt and extend.
