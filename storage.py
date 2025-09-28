# storage.py
import sqlite3
import time
from typing import Optional, Tuple, List, Dict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

DB_PATH = "defense_leaderboard.db"

def utcnow_i() -> int:
    return int(time.time())

# ---------- Decorator ----------
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

# ---------- Create / migrate DB ----------
def _column_exists(con: sqlite3.Connection, table: str, column: str) -> bool:
    cur = con.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())

def create_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages(
            message_id INTEGER PRIMARY KEY,
            guild_id   INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            created_ts INTEGER NOT NULL,
            outcome    TEXT,
            incomplete INTEGER,
            last_ts    INTEGER NOT NULL,
            creator_id INTEGER,
            team       INTEGER,
            attack_incomplete INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS participants(
            message_id INTEGER NOT NULL,
            user_id    INTEGER NOT NULL,
            added_by   INTEGER,
            source     TEXT,
            ts         INTEGER NOT NULL,
            PRIMARY KEY(message_id, user_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS leaderboard_posts(
            guild_id   INTEGER,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            type       TEXT NOT NULL,
            PRIMARY KEY (guild_id, type)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS leaderboard_totals(
            guild_id INTEGER NOT NULL,
            type     TEXT NOT NULL,
            user_id  INTEGER NOT NULL,
            count    INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, type, user_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS aggregates(
            guild_id INTEGER NOT NULL,
            scope    TEXT NOT NULL,
            key      TEXT NOT NULL,
            value    INTEGER NOT NULL,
            PRIMARY KEY (guild_id, scope, key)
        )
    """)

    # ---------- nouvelle table config ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS guild_config(
            guild_id INTEGER PRIMARY KEY,
            alert_channel_id INTEGER,
            leaderboard_channel_id INTEGER,
            snapshot_channel_id INTEGER,
            role_def_id INTEGER,
            role_def2_id INTEGER,
            role_test_id INTEGER,
            admin_role_id INTEGER
        )
    """)

    # migrations légères
    try:
        if not _column_exists(con, "messages", "team"):
            cur.execute("ALTER TABLE messages ADD COLUMN team INTEGER")
        if not _column_exists(con, "messages", "attack_incomplete"):
            cur.execute("ALTER TABLE messages ADD COLUMN attack_incomplete INTEGER DEFAULT 0")
        con.commit()
    except Exception:
        pass

    con.commit()
    con.close()

# ---------- Guild config ----------
@with_db
def upsert_guild_config(
    con: sqlite3.Connection,
    guild_id: int,
    alert_channel_id: int,
    leaderboard_channel_id: int,
    snapshot_channel_id: int,
    role_def_id: int,
    role_def2_id: int,
    role_test_id: int,
    admin_role_id: int
):
    con.execute("""
        INSERT INTO guild_config
        (guild_id, alert_channel_id, leaderboard_channel_id, snapshot_channel_id,
         role_def_id, role_def2_id, role_test_id, admin_role_id)
        VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(guild_id) DO UPDATE SET
            alert_channel_id=excluded.alert_channel_id,
            leaderboard_channel_id=excluded.leaderboard_channel_id,
            snapshot_channel_id=excluded.snapshot_channel_id,
            role_def_id=excluded.role_def_id,
            role_def2_id=excluded.role_def2_id,
            role_test_id=excluded.role_test_id,
            admin_role_id=excluded.admin_role_id
    """, (guild_id, alert_channel_id, leaderboard_channel_id, snapshot_channel_id,
          role_def_id, role_def2_id, role_test_id, admin_role_id))

@with_db
def get_guild_config(con: sqlite3.Connection, guild_id: int) -> Optional[dict]:
    row = con.execute("SELECT * FROM guild_config WHERE guild_id=?", (guild_id,)).fetchone()
    return dict(row) if row else None
