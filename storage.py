import sqlite3
import time
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
def add_participant(con: sqlite3.Connection, message_id: int, user_id: int, added_by: Optional[int] = None, source: str = "reaction") -> bool:
    try:
        con.execute("""
            INSERT INTO participants(message_id, user_id, added_by, source, ts)
            VALUES (?,?,?,?,?)
        """, (message_id, user_id, added_by, source, utcnow_i()))
        return True
    except sqlite3.IntegrityError:
        return False

@with_db
def remove_participant(con: sqlite3.Connection, message_id: int, user_id: int) -> bool:
    cur = con.cursor()
    cur.execute("DELETE FROM participants WHERE message_id=? AND user_id=?", (message_id, user_id))
    return cur.rowcount > 0

@with_db
def get_participant_entry(con: sqlite3.Connection, message_id: int, user_id: int) -> Optional[Tuple[int, str, int]]:
    cur = con.cursor()
    cur.execute("SELECT added_by, source, ts FROM participants WHERE message_id=? AND user_id=?", (message_id, user_id))
    row = cur.fetchone()
    if not row:
        return None
    return (row["added_by"], row["source"], row["ts"])

@with_db
def get_participants_detailed(con: sqlite3.Connection, message_id: int) -> List[Tuple[int, Optional[int], int]]:
    cur = con.cursor()
    cur.execute("SELECT user_id, added_by, ts FROM participants WHERE message_id=? ORDER BY ts ASC", (message_id,))
    return [(row["user_id"], row["added_by"], row["ts"]) for row in cur.fetchall()]

@with_db
def get_first_defender(con: sqlite3.Connection, message_id: int) -> Optional[int]:
    cur = con.cursor()
    cur.execute("SELECT user_id FROM participants WHERE message_id=? ORDER BY ts ASC LIMIT 1", (message_id,))
    row = cur.fetchone()
    return row["user_id"] if row else None

# ---------- Leaderboard ----------
@with_db
def incr_leaderboard(con: sqlite3.Connection, guild_id: int, type_: str, user_id: int):
    con.execute("""
        INSERT INTO leaderboard_totals(guild_id, type, user_id, count)
        VALUES (?,?,?,1)
        ON CONFLICT(guild_id, type, user_id) DO UPDATE SET count=count+1
    """, (guild_id, type_, user_id))

@with_db
def decr_leaderboard(con: sqlite3.Connection, guild_id: int, type_: str, user_id: int):
    con.execute("""
        UPDATE leaderboard_totals
        SET count = count - 1
        WHERE guild_id=? AND type=? AND user_id=?
    """, (guild_id, type_, user_id))
    con.execute("""
        DELETE FROM leaderboard_totals
        WHERE guild_id=? AND type=? AND user_id=? AND count<=0
    """, (guild_id, type_, user_id))

@with_db
def get_leaderboard_post(con: sqlite3.Connection, guild_id: int, type_: str):
    cur = con.cursor()
    cur.execute("SELECT channel_id, message_id FROM leaderboard_posts WHERE guild_id=? AND type=?", (guild_id, type_))
    row = cur.fetchone()
    return (row["channel_id"], row["message_id"]) if row else None

@with_db
def set_leaderboard_post(con: sqlite3.Connection, guild_id: int, channel_id: int, message_id: int, type_: str):
    con.execute("""
        INSERT INTO leaderboard_posts(guild_id, channel_id, message_id, type)
        VALUES (?,?,?,?)
        ON CONFLICT(guild_id, type) DO UPDATE SET channel_id=excluded.channel_id, message_id=excluded.message_id
    """, (guild_id, channel_id, message_id, type_))

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
    w,l,inc,tot = cur.fetchone()
    return (w or 0, l or 0, inc or 0, tot or 0)

@with_db
def get_player_stats(con: sqlite3.Connection, guild_id: int, user_id: int) -> Tuple[int,int,int,int]:
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
