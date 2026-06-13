"""CipherPipe database — SQLite persistence."""
import sqlite3, time, os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cipherpipe.db")


def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS rooms (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id     TEXT NOT NULL UNIQUE,
            name        TEXT NOT NULL DEFAULT '',
            created_at  REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id      TEXT NOT NULL,
            from_agent   TEXT NOT NULL,
            ciphertext   TEXT NOT NULL,
            nonce        TEXT NOT NULL,
            received_at  REAL NOT NULL,
            FOREIGN KEY (room_id) REFERENCES rooms(room_id)
        );
        CREATE INDEX IF NOT EXISTS idx_msg_room ON messages(room_id, received_at DESC);
    """)
    conn.commit()
    return conn


def create_room(conn, room_id: str, name: str = ""):
    conn.execute("INSERT OR IGNORE INTO rooms (room_id, name, created_at) VALUES (?, ?, ?)",
                 (room_id, name, time.time()))
    conn.commit()


def list_rooms(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT r.room_id, r.name, r.created_at, COUNT(m.id) as msg_count "
        "FROM rooms r LEFT JOIN messages m ON r.room_id = m.room_id "
        "GROUP BY r.room_id ORDER BY r.created_at DESC"
    ).fetchall()
    return [{"room_id": r["room_id"], "name": r["name"],
             "created_at": r["created_at"], "message_count": r["msg_count"]} for r in rows]


def insert_message(conn, room_id: str, from_agent: str, ciphertext: str, nonce: str):
    conn.execute("INSERT INTO messages (room_id, from_agent, ciphertext, nonce, received_at) "
                 "VALUES (?, ?, ?, ?, ?)",
                 (room_id, from_agent, ciphertext, nonce, time.time()))
    conn.commit()


def get_messages(conn, room_id: str, limit: int = 50, before_id: int = None) -> list[dict]:
    if before_id:
        rows = conn.execute(
            "SELECT id, room_id, from_agent, ciphertext, nonce, received_at "
            "FROM messages WHERE room_id = ? AND id < ? ORDER BY id DESC LIMIT ?",
            (room_id, before_id, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, room_id, from_agent, ciphertext, nonce, received_at "
            "FROM messages WHERE room_id = ? ORDER BY id DESC LIMIT ?",
            (room_id, limit)
        ).fetchall()
    rows = list(rows)
    rows.reverse()
    return [{"id": r["id"], "room_id": r["room_id"], "from": r["from_agent"],
             "ciphertext": r["ciphertext"], "nonce": r["nonce"],
             "received_at": r["received_at"]} for r in rows]
