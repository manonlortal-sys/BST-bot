import sqlite3
import time
from typing import Optional, Tuple, List
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

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

def _column_exists(con: sqlite3.Connection, table: str, column: str) -> bool:
    cur = con.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())

def create_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    # messages
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
    # participants (détaillé: qui a ajouté qui, source et timestamp)
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
    # leaderboard_posts (où sont les messages de LB)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS leaderboard_posts(
            guild_id INTEGER,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            PRIMARY KEY (guild_id, type)
        )
    """)
    # leaderboard_totals (compteurs cumulés)
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

    # ---- Migration: ajouter la colonne team dans messages si manquante ----
    try:
        if not _column_exists(con, "messages", "team"):
            cur.execute("ALTER TABLE messages ADD COLUMN team INTEGER")
            con.commit()
    except Exception:
        # si la colonne existe déjà ou autre, on ignore
        pass

    con.close()

# ---------- Messages ----------
@with_db
def upsert_message(
    con: sqlite3.Connection,
    message_id: int,
    guild_id: int,
    channel_id: int,
    created_ts: int,
    creator_id: Optional[int] = None,
    team: Optional[int] = None,
):
    cur = con.cursor()
    # On insère puis on met à jour team si besoin (au cas où l’événement initial n’avait pas la team)
    cur.execute("""
        INSERT INTO messages(message_id, guild_id, channel_id, created_ts, outcome, incomplete, last_ts, creator_id, team)
        VALUES (?,?,?,?,NULL,0,?,?,?)
        ON CONFLICT(message_id) DO NOTHING
    """, (message_id, guild_id, channel_id, created_ts, utcnow_i(), creator_id, team))
    if team is not None:
        cur.execute("UPDATE messages SET team=?, last_ts=? WHERE message_id=?", (team, utcnow_i(), message_id))

@with_db
def get_message_creator(con: sqlite3.Connection, message_id: int) -> Optional[int]:
    row = con.execute("SELECT creator_id FROM messages WHERE message_id=?", (message_id,)).fetchone()
    return row["creator_id"] if row else None

@with_db
def set_outcome(con: sqlite3.Connection, message_id: int, outcome: Optional[str]):
    con.execute("UPDATE messages SET outcome=?, last_ts=? WHERE message_id=?", (outcome, utcnow_i(), message_id))

@with_db
def set_incomplete(con: sqlite3.Connection, message_id: int, incomplete: bool):
    con.execute("UPDATE messages SET incomplete=?, last_ts=? WHERE message_id=?", (1 if incomplete else 0, utcnow_i(), message_id))

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
    row = con.execute("SELECT added_by, source, ts FROM participants WHERE message_id=? AND user_id=?", (message_id, user_id)).fetchone()
    return (row["added_by"], row["source"], row["ts"]) if row else None

@with_db
def get_participants_detailed(con: sqlite3.Connection, message_id: int) -> List[Tuple[int, Optional[int], int]]:
    rows = con.execute("SELECT user_id, added_by, ts FROM participants WHERE message_id=? ORDER BY ts ASC", (message_id,)).fetchall()
    return [(r["user_id"], r["added_by"], r["ts"]) for r in rows]

@with_db
def get_first_defender(con: sqlite3.Connection, message_id: int) -> Optional[int]:
    row = con.execute("SELECT user_id FROM participants WHERE message_id=? ORDER BY ts ASC LIMIT 1", (message_id,)).fetchone()
    return row["user_id"] if row else None

# ---------- Leaderboard totals ----------
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
    row = con.execute("SELECT channel_id, message_id FROM leaderboard_posts WHERE guild_id=? AND type=?", (guild_id, type_)).fetchone()
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
    rows = con.execute("""
        SELECT user_id, count FROM leaderboard_totals
        WHERE guild_id=? AND type=?
        ORDER BY count DESC
        LIMIT ?
    """, (guild_id, type_, limit)).fetchall()
    return [(r["user_id"], r["count"]) for r in rows]

@with_db
def agg_totals_all(con: sqlite3.Connection, guild_id: int) -> Tuple[int, int, int, int]:
    row = con.execute("""
        SELECT
            SUM(CASE WHEN outcome='win'  THEN 1 ELSE 0 END) AS w,
            SUM(CASE WHEN outcome='loss' THEN 1 ELSE 0 END) AS l,
            SUM(CASE WHEN incomplete=1  THEN 1 ELSE 0 END) AS inc,
            COUNT(*) AS tot
        FROM messages
        WHERE guild_id=?
    """, (guild_id,)).fetchone()
    w,l,inc,tot = row["w"] or 0, row["l"] or 0, row["inc"] or 0, row["tot"] or 0
    return (w, l, inc, tot)

@with_db
def agg_totals_by_team(con: sqlite3.Connection, guild_id: int, team: int) -> Tuple[int, int, int, int]:
    row = con.execute("""
        SELECT
            SUM(CASE WHEN outcome='win'  THEN 1 ELSE 0 END) AS w,
            SUM(CASE WHEN outcome='loss' THEN 1 ELSE 0 END) AS l,
            SUM(CASE WHEN incomplete=1  THEN 1 ELSE 0 END) AS inc,
            COUNT(*) AS tot
        FROM messages
        WHERE guild_id=? AND team=?
    """, (guild_id, team)).fetchone()
    if not row:
        return (0,0,0,0)
    return (row["w"] or 0, row["l"] or 0, row["inc"] or 0, row["tot"] or 0)

@with_db
def hourly_split_all(con: sqlite3.Connection, guild_id: int) -> tuple[int, int, int, int]:
    """
    Répartition ALL-TIME par tranches locales Europe/Paris:
    0: Matin (6–10), 1: Après-midi (10–18), 2: Soir (18–00), 3: Nuit (00–6)
    """
    rows = con.execute("SELECT created_ts FROM messages WHERE guild_id=?", (guild_id,)).fetchall()
    counts = [0, 0, 0, 0]
    for (ts,) in rows:
        dt_paris = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(ZoneInfo("Europe/Paris"))
        h = dt_paris.hour
        if 6 <= h < 10:
            counts[0] += 1
        elif 10 <= h < 18:
            counts[1] += 1
        elif 18 <= h < 24:
            counts[2] += 1
        else:
            counts[3] += 1
    return tuple(counts)

@with_db
def get_player_stats(con: sqlite3.Connection, guild_id: int, user_id: int) -> Tuple[int,int,int,int]:
    cur = con.cursor()
    # Défenses prises
    cur.execute("""
        SELECT COUNT(*) FROM participants p
        JOIN messages m ON m.message_id=p.message_id
        WHERE m.guild_id=? AND p.user_id=?
    """, (guild_id, user_id))
    defenses = cur.fetchone()[0] or 0
    # Pings faits
    cur.execute("SELECT COUNT(*) FROM messages WHERE guild_id=? AND creator_id=?", (guild_id, user_id))
    pings = cur.fetchone()[0] or 0
    # Victoires/défaites
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
