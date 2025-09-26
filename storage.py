import sqlite3
import time
from datetime import datetime, timezone
from typing import Optional, Tuple, List

DB_PATH = "defense_leaderboard.db"

def utcnow_i() -> int:
    return int(time.time())

# ---------- Helpers ----------
def with_db(func):
    def wrapper(*args, **kwargs):
        con = sqlite3.connect(DB_PATH, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            res = func(con, *args, **kwargs)
            con.commit()
            return res
        finally:
            con.close()
    return wrapper

def create_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages(
            message_id INTEGER PRIMARY KEY,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            created_ts INTEGER NOT NULL,
            outcome TEXT,
            incomplete INTEGER,
            last_ts INTEGER NOT NULL,
            creator_id INTEGER
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS participants(
            message_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            added_by INTEGER,
            source TEXT,
            ts INTEGER NOT NULL,
            PRIMARY KEY(message_id, user_id)
        )
    """)
    con.commit()
    con.close()

# ---------- Messages ----------
@with_db
def upsert_message(con: sqlite3.Connection, message_id: int, guild_id: int, channel_id: int, created_ts: int, creator_id: Optional[int] = None):
    cur = con.cursor()
    cur.execute("""
        INSERT INTO messages(message_id, guild_id, channel_id, created_ts, outcome, incomplete, last_ts, creator_id)
        VALUES (?,?,?,?,NULL,0,?,?)
        ON CONFLICT(message_id) DO NOTHING
    """, (message_id, guild_id, channel_id, created_ts, utcnow_i(), creator_id))

@with_db
def get_message_creator(con: sqlite3.Connection, message_id: int) -> Optional[int]:
    cur = con.cursor()
    cur.execute("SELECT creator_id FROM messages WHERE message_id=?", (message_id,))
    row = cur.fetchone()
    return row["creator_id"] if row else None

# ---------- Participants ----------
@with_db
def add_participant(con: sqlite3.Connection, message_id: int, user_id: int, added_by: Optional[int] = None, source: str = "reaction") -> bool:
    """Ajoute un participant, retourne True si inséré, False si déjà présent."""
    cur = con.cursor()
    try:
        cur.execute("""
            INSERT INTO participants(message_id, user_id, added_by, source, ts)
            VALUES (?,?,?,?,?)
        """, (message_id, user_id, added_by, source, utcnow_i()))
        return True
    except sqlite3.IntegrityError:
        return False

@with_db
def get_participants_detailed(con: sqlite3.Connection, message_id: int) -> List[Tuple[int, Optional[int], int]]:
    """Retourne [(user_id, added_by, ts), ...]"""
    cur = con.cursor()
    cur.execute("SELECT user_id, added_by, ts FROM participants WHERE message_id=? ORDER BY ts ASC", (message_id,))
    return [(row["user_id"], row["added_by"], row["ts"]) for row in cur.fetchall()]

@with_db
def get_first_defender(con: sqlite3.Connection, message_id: int) -> Optional[int]:
    cur = con.cursor()
    cur.execute("SELECT user_id FROM participants WHERE message_id=? ORDER BY ts ASC LIMIT 1", (message_id,))
    row = cur.fetchone()
    return row["user_id"] if row else None
