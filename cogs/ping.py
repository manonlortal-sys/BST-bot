from __future__ import annotations
import os
import time
import sqlite3
import asyncio
from datetime import datetime, timezone
from typing import Optional, Tuple, List, Dict

import discord
from discord import app_commands
from discord.ext import commands

# ---------- ENV ----------
ALERT_CHANNEL_ID = int(os.getenv("ALERT_CHANNEL_ID", "0"))
LEADERBOARD_CHANNEL_ID = int(os.getenv("LEADERBOARD_CHANNEL_ID", "0"))
ROLE_DEF_ID = int(os.getenv("ROLE_DEF_ID", "0"))
ROLE_DEF2_ID = int(os.getenv("ROLE_DEF2_ID", "0"))
ROLE_TEST_ID = int(os.getenv("ROLE_TEST_ID", "0"))

# ---------- Constantes ----------
EMOJI_VICTORY = "🏆"
EMOJI_DEFEAT = "❌"
EMOJI_INCOMP = "😡"
EMOJI_JOIN = "👍"

BUCKETS = [
    ("🌅 Matin (6–10)", 6, 10),
    ("🌞 Journée (10–18)", 10, 18),
    ("🌙 Soir (18–00)", 18, 24),
    ("🌌 Nuit (00–6)", 0, 6),
]

DB_PATH = "defense_leaderboard.db"

def utcnow_i() -> int:
    return int(time.time())

# ---------- DB helpers ----------
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
            creator_id INTEGER
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS participants(
            message_id INTEGER NOT NULL,
            user_id    INTEGER NOT NULL,
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
    con.commit()
    con.close()

def with_db(func):
    def wrapper(*args, **kwargs):
        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row
        try:
            res = func(con, *args, **kwargs)
            con.commit()
            return res
        finally:
            con.close()
    return wrapper

# ---------- DB functions ----------
@with_db
def upsert_message(con: sqlite3.Connection, message: discord.Message, creator_id: Optional[int] = None):
    cur = con.cursor()
    cur.execute("""
        INSERT INTO messages(message_id, guild_id, channel_id, created_ts, outcome, incomplete, last_ts, creator_id)
        VALUES (?,?,?,?,NULL,0,?,?)
        ON CONFLICT(message_id) DO NOTHING
    """, (message.id, message.guild.id, message.channel.id,
          int(message.created_at.replace(tzinfo=timezone.utc).timestamp()), utcnow_i(), creator_id))

@with_db
def set_outcome(con: sqlite3.Connection, message_id: int, outcome: Optional[str]):
    cur = con.cursor()
    cur.execute("UPDATE messages SET outcome=?, last_ts=? WHERE message_id=?", (outcome, utcnow_i(), message_id))

@with_db
def set_incomplete(con: sqlite3.Connection, message_id: int, incomplete: bool):
    cur = con.cursor()
    cur.execute("UPDATE messages SET incomplete=?, last_ts=? WHERE message_id=?", (1 if incomplete else 0, utcnow_i(), message_id))

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
def get_leaderboard_post(con: sqlite3.Connection, guild_id: int, type_: str) -> Optional[Tuple[int,int]]:
    cur = con.cursor()
    cur.execute("SELECT channel_id, message_id FROM leaderboard_posts WHERE guild_id=? AND type=?", (guild_id, type_))
    row = cur.fetchone()
    if not row: return None
    return (row["channel_id"], row["message_id"])

@with_db
def set_leaderboard_post(con: sqlite3.Connection, guild_id: int, channel_id: int, message_id: int, type_: str):
    cur = con.cursor()
    cur.execute("""
        INSERT INTO leaderboard_posts(guild_id, channel_id, message_id, type)
        VALUES (?,?,?,?)
        ON CONFLICT(guild_id, type) DO UPDATE SET channel_id=excluded.channel_id, message_id=excluded.message_id
    """, (guild_id, channel_id, message_id, type_))

@with_db
def agg_totals_all(con: sqlite3.Connection, guild_id: int) -> Tuple[int,int,int,int]:
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
def top_defenders(con: sqlite3.Connection, guild_id: int, limit: int = 20) -> List[Tuple[int,int]]:
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
def top_pingeurs(con: sqlite3.Connection, guild_id: int, limit: int = 20) -> List[Tuple[int,int]]:
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
def hourly_split_7d(con: sqlite3.Connection, guild_id: int) -> List[int]:
    since = utcnow_i() - 7*24*3600
    cur = con.cursor()
    cur.execute("SELECT created_ts FROM messages WHERE guild_id=? AND created_ts>=?", (guild_id, since))
    rows = cur.fetchall()
    counts = [0,0,0,0]
    for r in rows:
        h = datetime.fromtimestamp(r["created_ts"], tz=timezone.utc).hour
        if 6 <= h < 10: counts[0]+=1
        elif 10 <= h < 18: counts[1]+=1
        elif 18 <= h < 24: counts[2]+=1
        else: counts[3]+=1
    return counts

@with_db
def get_creator_id(con: sqlite3.Connection, message_id: int) -> Optional[int]:
    cur = con.cursor()
    cur.execute("SELECT creator_id FROM messages WHERE message_id=?", (message_id,))
    row = cur.fetchone()
    return row["creator_id"] if row else None

# ---------- Embed constructeur ----------
async def build_ping_embed(msg: discord.Message, creator: Optional[discord.Member] = None) -> discord.Embed:
    reactions = {str(r.emoji): r for r in msg.reactions}
    win  = (EMOJI_VICTORY in reactions and reactions[EMOJI_VICTORY].count > 0)
    loss = (EMOJI_DEFEAT in reactions and reactions[EMOJI_DEFEAT].count > 0)

    if win and not loss:
        color = discord.Color.green()
        etat = f"{EMOJI_VICTORY} **Défense gagnée**"
    elif loss and not win:
        color = discord.Color.red()
        etat = f"{EMOJI_DEFEAT} **Défense perdue**"
    else:
        color = discord.Color.orange()
        etat = "⏳ **En cours / à confirmer**"

    defenders_ids: List[int] = []
    if EMOJI_JOIN in reactions:
        async for u in reactions[EMOJI_JOIN].users():
            if not u.bot:
                defenders_ids.append(u.id)

    guild = msg.guild
    names: List[str] = []
    for uid in defenders_ids[:20]:
        m = guild.get_member(uid) if guild else None
        names.append(m.display_name if m else f"<@{uid}>")
    defenders_block = "• " + "\n• ".join(names) if names else "_Aucun défenseur pour le moment._"

    embed = discord.Embed(
        title="🛡️ Alerte Percepteur",
        description="⚠️ **Connectez-vous pour prendre la défense !**",
        color=color,
    )
    embed.add_field(name="État du combat", value=etat, inline=False)
    embed.add_field(name="Défenseurs (👍)", value=defenders_block, inline=False)

    if creator:
        embed.add_field(name="⚡ Déclenché par", value=creator.display_name, inline=False)

    embed.set_footer(text="Ajoutez vos réactions : 🏆 gagné • ❌ perdu • 😡 incomplète • 👍 j'ai participé")
    return embed

# ---------- View boutons ----------
class PingButtonsView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Guilde 1 (Def)", style=discord.ButtonStyle.primary)
    async def btn_def(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_click(interaction, side="Def")

    @discord.ui.button(label="Guilde 2 (Def2)", style=discord.ButtonStyle.danger)
    async def btn_def2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_click(interaction, side="Def2")

    @discord.ui.button(label="TEST (Admin)", style=discord.ButtonStyle.secondary)
    async def btn_test(self, interaction: discord.Interaction, button: discord.ui.Button):
        admin_roles = [r for r in interaction.user.roles if r.permissions.administrator]
        if not admin_roles:
            await interaction.response.send_message("Bouton réservé aux admins.", ephemeral=True)
            return
        await self._handle_click(interaction, side="Test")

    async def _handle_click(self, interaction: discord.Interaction, side: str):
        await interaction.response.defer(ephemeral=True, thinking=False)

        guild = interaction.guild
        if guild is None or ALERT_CHANNEL_ID == 0:
            return

        alert_channel = guild.get_channel(ALERT_CHANNEL_ID)
        if not isinstance(alert_channel, discord.TextChannel):
            return

        role_id = 0
        if side == "Def":
            role_id = ROLE_DEF_ID
        elif side == "Def2":
            role_id = ROLE_DEF2_ID
        elif side == "Test":
            role_id = ROLE_TEST_ID

        role_mention = f"<@&{role_id}>" if role_id != 0 else ""
        content = f"{role_mention} — **Percepteur attaqué !** Merci de vous connecter." if role_mention else "**Percepteur attaqué !** Merci de vous connecter."

        msg = await alert_channel.send(
            content,
            allowed_mentions=discord.AllowedMentions(roles=True)
        )

        emb = await build_ping_embed(msg, creator=interaction.user)
        await msg.edit(embed=emb)

        upsert_message(msg, creator_id=interaction.user.id)

# ---------- Cog principal ----------
class PingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        create_db()

    @app_commands.command(name="pingpanel", description="Publier le panneau de ping des percepteurs (défenses)")
    async def pingpanel(self, interaction: discord.Interaction):
        view = PingButtonsView(self.bot)
        embed = discord.Embed(
            title="🛡️ Panneau de défense",
            description="Cliquez sur les boutons ci-dessous pour déclencher une alerte.",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

# ---------- Setup ----------
async def setup(bot: commands.Bot):
    await bot.add_cog(PingCog(bot))
