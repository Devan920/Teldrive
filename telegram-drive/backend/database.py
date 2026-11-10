import os
import json
import aiosqlite

DB_PATH = os.path.join(os.path.dirname(__file__), "cloud_storage.db")

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON;")

        await db.execute("""
            CREATE TABLE IF NOT EXISTS folders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                parent_id INTEGER DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(parent_id) REFERENCES folders(id) ON DELETE CASCADE
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_name TEXT NOT NULL,
                file_id TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                folder_id INTEGER DEFAULT NULL,
                total_chunks INTEGER DEFAULT 1,
                chunks TEXT DEFAULT '[]',
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(folder_id) REFERENCES folders(id) ON DELETE CASCADE
            )
        """)

        # Migration: Add missing columns if database existed prior
        async with db.execute("PRAGMA table_info(files)") as cursor:
            columns = [row["name"] for row in await cursor.fetchall()]
            if "folder_id" not in columns:
                await db.execute("ALTER TABLE files ADD COLUMN folder_id INTEGER DEFAULT NULL")
            if "total_chunks" not in columns:
                await db.execute("ALTER TABLE files ADD COLUMN total_chunks INTEGER DEFAULT 1")
            if "chunks" not in columns:
                await db.execute("ALTER TABLE files ADD COLUMN chunks TEXT DEFAULT '[]'")

        await db.commit()

async def create_folder(name: str, parent_id: int = None) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "INSERT INTO folders (name, parent_id) VALUES (?, ?)",
            (name, parent_id)
        )
        await db.commit()
        return cursor.lastrowid

async def list_folders(parent_id: int = None) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if parent_id is None:
            query = """
                SELECT f.id, f.name, f.parent_id, f.created_at,
                       ((SELECT COUNT(*) FROM files WHERE folder_id = f.id) +
                        (SELECT COUNT(*) FROM folders WHERE parent_id = f.id)) AS item_count
                FROM folders f
                WHERE f.parent_id IS NULL
                ORDER BY f.name ASC
            """
            params = ()
        else:
            query = """
                SELECT f.id, f.name, f.parent_id, f.created_at,
                       ((SELECT COUNT(*) FROM files WHERE folder_id = f.id) +
                        (SELECT COUNT(*) FROM folders WHERE parent_id = f.id)) AS item_count
                FROM folders f
                WHERE f.parent_id = ?
                ORDER BY f.name ASC
            """
            params = (parent_id,)
        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def get_folder(folder_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM folders WHERE id = ?", (folder_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def get_breadcrumbs(folder_id: int = None) -> list:
    crumbs = [{"id": None, "name": "Home"}]
    if not folder_id:
        return crumbs

    current_id = folder_id
    chain = []
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        while current_id is not None:
            async with db.execute("SELECT id, name, parent_id FROM folders WHERE id = ?", (current_id,)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    break
                chain.append({"id": row["id"], "name": row["name"]})
                current_id = row["parent_id"]

    chain.reverse()
    return crumbs + chain

async def delete_folder(folder_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON;")
        cursor = await db.execute("DELETE FROM folders WHERE id = ?", (folder_id,))
        await db.commit()
        return cursor.rowcount > 0

async def add_file(file_name: str, file_id: str, file_size: int, folder_id: int = None, total_chunks: int = 1, chunks: str = '[]') -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "INSERT INTO files (file_name, file_id, file_size, folder_id, total_chunks, chunks) VALUES (?, ?, ?, ?, ?, ?)",
            (file_name, file_id, file_size, folder_id, total_chunks, chunks)
        )
        await db.commit()
        return cursor.lastrowid

async def get_file(record_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM files WHERE id = ?", (record_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def list_files(search: str = None, folder_id: int = None) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if search and search.strip():
            query = "SELECT * FROM files WHERE file_name LIKE ? ORDER BY id DESC"
            params = (f"%{search.strip()}%",)
        elif folder_id is None:
            query = "SELECT * FROM files WHERE folder_id IS NULL ORDER BY id DESC"
            params = ()
        else:
            query = "SELECT * FROM files WHERE folder_id = ? ORDER BY id DESC"
            params = (folder_id,)

        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def delete_file(record_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("DELETE FROM files WHERE id = ?", (record_id,))
        await db.commit()
        return cursor.rowcount > 0
