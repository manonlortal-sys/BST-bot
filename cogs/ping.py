from __future__ import annotations
import os
import time
import sqlite3
import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Optional, Tuple, List

import discord
from discord import app_commands
from discord.ext import commands

# ---------- ENV ----------
ALERT_CHANNEL_ID = int(os.getenv("ALERT_CHANNEL_ID", "0"))
LEADERBOARD_CHANNEL_ID = int(os.getenv("LEADERBOARD_CHANNEL_ID", "0"))
ARCHIVE_CHANNEL_ID = int(os.getenv("ARCHIVE_CHANNEL_ID", "0"))
ROLE_DEF_ID = int(os.getenv("ROLE_DEF_ID", "0"))
ROLE_DEF2_ID = int(os.getenv("ROLE_DEF2_ID", "0"))
ROLE_TEST_ID = int(os.getenv("ROLE_TEST_ID", "0"))
ADMIN_ROLE_ID = 1280396795046006836

# ---------- Constantes ----------
EMOJI_VICTORY = "🏆"
EMOJI_DEFEAT = "❌"
EMOJI_INCOMP = "😡"
EMOJI_JOIN = "👍"

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
            creator_id INTEGER,
            leaderboard_id INTEGER DEFAULT 1
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
            current_id INTEGER DEFAULT 1,
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
def get_leaderboard_post(con: sqlite3.Connection, guild_id: int, type_: str) -> Optional[Tuple[int,int,int]]:
    cur = con.cursor()
    cur.execute("SELECT channel_id, message_id, current_id FROM leaderboard_posts WHERE guild_id=? AND type=?", (guild_id, type_))
    row = cur.fetchone()
    if not row: return None
    return (row["channel_id"], row["message_id"], row["current_id"])

@with_db
def set_leaderboard_post(con: sqlite3.Connection, guild_id: int, channel_id: int, message_id: int, type_: str, current_id: int = 1):
    cur = con.cursor()
    cur.execute("""
        INSERT INTO leaderboard_posts(guild_id, channel_id, message_id, type, current_id)
        VALUES (?,?,?,?,?)
        ON CONFLICT(guild_id, type) DO UPDATE SET channel_id=excluded.channel_id, message_id=excluded.message_id, current_id=excluded.current_id
    """, (guild_id, channel_id, message_id, type_, current_id))

@with_db
def get_messages_for_leaderboard(con: sqlite3.Connection, guild_id: int, leaderboard_id: int):
    cur = con.cursor()
    cur.execute("SELECT * FROM messages WHERE guild_id=? AND leaderboard_id=?", (guild_id, leaderboard_id))
    return cur.fetchall()

@with_db
def increment_leaderboard_id(con: sqlite3.Connection, guild_id: int, type_: str) -> int:
    cur = con.cursor()
    cur.execute("SELECT current_id FROM leaderboard_posts WHERE guild_id=? AND type=?", (guild_id, type_))
    row = cur.fetchone()
    new_id = 1 if not row else row["current_id"] + 1
    cur.execute("UPDATE leaderboard_posts SET current_id=? WHERE guild_id=? AND type=?", (new_id, guild_id, type_))
    return new_id

@with_db
def upsert_message(con: sqlite3.Connection, message: discord.Message, creator_id: Optional[int] = None, leaderboard_id: int = 1):
    cur = con.cursor()
    cur.execute("""
        INSERT INTO messages(message_id, guild_id, channel_id, created_ts, outcome, incomplete, last_ts, creator_id, leaderboard_id)
        VALUES (?,?,?,?,NULL,0,?,?,?)
        ON CONFLICT(message_id) DO NOTHING
    """, (message.id, message.guild.id, message.channel.id,
          int(message.created_at.replace(tzinfo=timezone.utc).timestamp()), utcnow_i(), creator_id, leaderboard_id))

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

# ---------- Cog principal ----------
class PingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        create_db()

    # ---------- Commandes reset leaderboard ----------
    @app_commands.command(name="reset_defense", description="Réinitialiser le leaderboard Défense")
    async def reset_defense(self, interaction: discord.Interaction):
        if not any(r.id == ADMIN_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("Seuls les admins peuvent utiliser cette commande.", ephemeral=True)
            return

        # Récupérer le leaderboard actuel
        post = get_leaderboard_post(interaction.guild.id, "defense")
        if not post:
            await interaction.response.send_message("Pas de leaderboard Défense existant.", ephemeral=True)
            return
        channel_id, message_id, current_id = post

        # Archiver
        archive_channel = interaction.guild.get_channel(ARCHIVE_CHANNEL_ID)
        if archive_channel:
            msg = await self.bot.get_channel(channel_id).fetch_message(message_id)
            await archive_channel.send(f"📊 Leaderboard Défense archivé ({datetime.now().strftime('%d/%m/%Y %H:%M')})", embed=msg.embeds[0])

        # Créer nouveau leaderboard à 0
        new_id = increment_leaderboard_id(interaction.guild.id, "defense")
        channel = self.bot.get_channel(LEADERBOARD_CHANNEL_ID)
        if channel:
            embed = discord.Embed(title="📊 Leaderboard Défense", description=f"Réinitialisé le {datetime.now().strftime('%d/%m/%Y %H:%M')}", color=discord.Color.blue())
            msg_new = await channel.send(embed=embed)
            set_leaderboard_post(interaction.guild.id, channel.id, msg_new.id, "defense", new_id)

        await interaction.response.send_message("📊 Leaderboard Défense réinitialisé et archivé.", ephemeral=True)

    @app_commands.command(name="reset_pingeur", description="Réinitialiser le leaderboard Pingeurs")
    async def reset_pingeur(self, interaction: discord.Interaction):
        if not any(r.id == ADMIN_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("Seuls les admins peuvent utiliser cette commande.", ephemeral=True)
            return

        # Récupérer le leaderboard actuel
        post = get_leaderboard_post(interaction.guild.id, "pingeur")
        if not post:
            await interaction.response.send_message("Pas de leaderboard Pingeurs existant.", ephemeral=True)
            return
        channel_id, message_id, current_id = post

        # Archiver
        archive_channel = interaction.guild.get_channel(ARCHIVE_CHANNEL_ID)
        if archive_channel:
            msg = await self.bot.get_channel(channel_id).fetch_message(message_id)
            await archive_channel.send(f"📊 Leaderboard Pingeurs archivé ({datetime.now().strftime('%d/%m/%Y %H:%M')})", embed=msg.embeds[0])

        # Créer nouveau leaderboard à 0
        new_id = increment_leaderboard_id(interaction.guild.id, "pingeur")
        channel = self.bot.get_channel(LEADERBOARD_CHANNEL_ID)
        if channel:
            embed = discord.Embed(title="📊 Leaderboard Pingeurs", description=f"Réinitialisé le {datetime.now().strftime('%d/%m/%Y %H:%M')}", color=discord.Color.gold())
            msg_new = await channel.send(embed=embed)
            set_leaderboard_post(interaction.guild.id, channel.id, msg_new.id, "pingeur", new_id)

        await interaction.response.send_message("📊 Leaderboard Pingeurs réinitialisé et archivé.", ephemeral=True)

# ---------- Setup ----------
async def setup(bot: commands.Bot):
    cog = PingCog(bot)
    await bot.add_cog(cog)

    # ID du serveur de test
    TEST_GUILD_ID = 1280234399610179634
    test_guild = discord.Object(id=TEST_GUILD_ID)

    # Ajouter les commandes au tree du serveur
    bot.tree.add_command(cog.reset_defense, guild=test_guild)
    bot.tree.add_command(cog.reset_pingeur, guild=test_guild)
    await bot.tree.sync(guild=test_guild)
