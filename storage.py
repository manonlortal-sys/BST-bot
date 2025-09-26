import os
import time
import sqlite3
from datetime import datetime, timezone
from typing import Optional, Tuple, List
from zoneinfo import ZoneInfo

# ---------- Constantes ----------
DB_PATH = os.getenv("DB_PATH", "defense_leaderboard.db")


def utcnow_i() -> int:
    return int(time.time())


# ---------- DB helpers ----------
def create_db():
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)

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
            PRIMARY KEY(message_id, user_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS leaderboard_posts(
            guild_id INTEGER,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            PRIMARY KEY (guild_id, type)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS panel_messages(
            guild_id INTEGER PRIMARY KEY,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS leaderboard_totals(
            guild_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(guild_id, type, user_id)
        )
    """)
    con.commit()
    con.close()


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


@with_db
def set_outcome(con: sqlite3.Connection, message_id: int, outcome: Optional[str]):
    cur = con.cursor()
    cur.execute("UPDATE messages SET outcome=?, last_ts=? WHERE message_id=?", (outcome, utcnow_i(), message_id))


@with_db
def set_incomplete(con: sqlite3.Connection, message_id: int, incomplete: bool):
    cur = con.cursor()
    cur.execute("UPDATE messages SET incomplete=?, last_ts=? WHERE message_id=?", (1 if incomplete else 0, utcnow_i(), message_id))


# ---------- Participants ----------
@with_db
def add_participant(con: sqlite3.Connection, message_id: int, user_id: int):
    cur = con.cursor()
    cur.execute("""
        INSERT INTO participants(message_id, user_id) VALUES (?,?)
        ON CONFLICT(message_id, user_id) DO NOTHING
    """, (message_id, user_id))


@with_db
def remove_participant(con: sqlite3.Connection, message_id: int, user_id: int):
    cur = con.cursor()
    cur.execute("DELETE FROM participants WHERE message_id=? AND user_id=?", (message_id, user_id))


@with_db
def participant_exists(con: sqlite3.Connection, message_id: int, user_id: int) -> bool:
    cur = con.cursor()
    cur.execute("SELECT 1 FROM participants WHERE message_id=? AND user_id=? LIMIT 1", (message_id, user_id))
    return cur.fetchone() is not None


# ---------- Panel & leaderboard posts ----------
@with_db
def get_leaderboard_post(con: sqlite3.Connection, guild_id: int, type_: str) -> Optional[Tuple[int, int]]:
    cur = con.cursor()
    cur.execute("SELECT channel_id, message_id FROM leaderboard_posts WHERE guild_id=? AND type=?", (guild_id, type_))
    row = cur.fetchone()
    return (row["channel_id"], row["message_id"]) if row else None


@with_db
def set_leaderboard_post(con: sqlite3.Connection, guild_id: int, channel_id: int, message_id: int, type_: str):
    cur = con.cursor()
    cur.execute("""
        INSERT INTO leaderboard_posts(guild_id, channel_id, message_id, type)
        VALUES (?,?,?,?)
        ON CONFLICT(guild_id, type) DO UPDATE SET channel_id=excluded.channel_id, message_id=excluded.message_id
    """, (guild_id, channel_id, message_id, type_))


@with_db
def set_panel_message(con: sqlite3.Connection, guild_id: int, channel_id: int, message_id: int):
    cur = con.cursor()
    cur.execute("""
        INSERT INTO panel_messages(guild_id, channel_id, message_id)
        VALUES (?,?,?)
        ON CONFLICT(guild_id) DO UPDATE SET channel_id=excluded.channel_id, message_id=excluded.message_id
    """, (guild_id, channel_id, message_id))


@with_db
def get_panel_message(con: sqlite3.Connection, guild_id: int) -> Optional[Tuple[int, int]]:
    cur = con.cursor()
    cur.execute("SELECT channel_id, message_id FROM panel_messages WHERE guild_id=?", (guild_id,))
    row = cur.fetchone()
    return (row["channel_id"], row["message_id"]) if row else None


# ---------- Stats & leaderboard ----------
@with_db
def agg_totals_all(con: sqlite3.Connection, guild_id: int) -> Tuple[int, int, int, int]:
    cur = con.cursor()
    cur.execute("""
        SELECT SUM(CASE WHEN outcome='win'  THEN 1 ELSE 0 END),
               SUM(CASE WHEN outcome='loss' THEN 1 ELSE 0 END),
               SUM(CASE WHEN incomplete=1  THEN 1 ELSE 0 END),
               COUNT(*)
        FROM messages
        WHERE guild_id=?
    """, (guild_id,))
    w, l, inc, tot = cur.fetchone()
    return (w or 0, l or 0, inc or 0, tot or 0)


@with_db
def top_defenders(con: sqlite3.Connection, guild_id: int, limit: int = 20) -> List[Tuple[int, int]]:
    cur = con.cursor()
    cur.execute("""
        SELECT p.user_id, COUNT(*) as cnt
        FROM participants p
        JOIN messages m ON m.message_id=p.message_id
        WHERE m.guild_id=?
        GROUP BY p.user_id
        ORDER BY cnt DESC
        LIMIT ?
    """, (guild_id, limit))
    return [(row["user_id"], row["cnt"]) for row in cur.fetchall()]


@with_db
def top_pingeurs(con: sqlite3.Connection, guild_id: int, limit: int = 20) -> List[Tuple[int, int]]:
    cur = con.cursor()
    cur.execute("""
        SELECT creator_id, COUNT(*) as cnt
        FROM messages
        WHERE guild_id=? AND creator_id IS NOT NULL
        GROUP BY creator_id
        ORDER BY cnt DESC
        LIMIT ?
    """, (guild_id, limit))
    return [(row["creator_id"], row["cnt"]) for row in cur.fetchall()]


@with_db
def hourly_split_7d(con: sqlite3.Connection, guild_id: int) -> list[int]:
    since = utcnow_i() - 7 * 24 * 3600
    cur = con.cursor()
    cur.execute("SELECT created_ts FROM messages WHERE guild_id=? AND created_ts>=?", (guild_id, since))
    rows = cur.fetchall()
    counts = [0, 0, 0, 0]
    for r in rows:
        ts = r["created_ts"]
        dt_paris = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(ZoneInfo("Europe/Paris"))
        h_local = dt_paris.hour
        if 6 <= h_local < 10: counts[0] += 1
        elif 10 <= h_local < 18: counts[1] += 1
        elif 18 <= h_local < 24: counts[2] += 1
        else: counts[3] += 1
    return counts


@with_db
def get_player_stats(con: sqlite3.Connection, guild_id: int, user_id: int) -> Tuple[int, int, int, int]:
    cur = con.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM participants p
        JOIN messages m ON m.message_id=p.message_id
        WHERE m.guild_id=? AND p.user_id=?
    """, (guild_id, user_id))
    defenses = cur.fetchone()[0] or 0

    cur.execute("SELECT COUNT(*) FROM messages WHERE guild_id=? AND creator_id=?", (guild_id, user_id))
    pings = cur.fetchone()[0] or 0

    cur.execute("""
        SELECT SUM(CASE WHEN m.outcome='win' THEN 1 ELSE 0 END),
               SUM(CASE WHEN m.outcome='loss' THEN 1 ELSE 0 END)
        FROM messages m
        JOIN participants p ON m.message_id=p.message_id
        WHERE m.guild_id=? AND p.user_id=?
    """, (guild_id, user_id))
    row = cur.fetchone()
    wins = row[0] or 0
    losses = row[1] or 0
    return defenses, pings, wins, losses


# ---------- Leaderboard totals ----------
@with_db
def incr_leaderboard(con: sqlite3.Connection, guild_id: int, type_: str, user_id: int):
    cur = con.cursor()
    cur.execute("""
        INSERT INTO leaderboard_totals(guild_id, type, user_id, count)
        VALUES (?,?,?,1)
        ON CONFLICT(guild_id, type, user_id) DO UPDATE SET count=count+1
    """, (guild_id, type_, user_id))


@with_db
def decr_leaderboard(con: sqlite3.Connection, guild_id: int, type_: str, user_id: int):
    cur = con.cursor()
    cur.execute("""
        UPDATE leaderboard_totals
        SET count = count - 1
        WHERE guild_id=? AND type=? AND user_id=?
    """, (guild_id, type_, user_id))
    cur.execute("DELETE FROM leaderboard_totals WHERE guild_id=? AND type=? AND user_id=? AND count<=0", (guild_id, type_, user_id))


@with_db
def reset_leaderboard_totals(con: sqlite3.Connection, guild_id: int, type_: str):
    cur = con.cursor()
    cur.execute("DELETE FROM leaderboard_totals WHERE guild_id=? AND type=?", (guild_id, type_))


@with_db
def get_leaderboard_totals(con: sqlite3.Connection, guild_id: int, type_: str, limit: int = 20):
    cur = con.cursor()
    cur.execute("""
        SELECT user_id, count FROM leaderboard_totals
        WHERE guild_id=? AND type=?
        ORDER BY count DESC
        LIMIT ?
    """, (guild_id, type_, limit))
    return [(row["user_id"], row["count"]) for row in cur.fetchall()]
