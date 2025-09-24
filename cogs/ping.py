from __future__ import annotations
import os
import time
import sqlite3
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
ROLE_ADMIN_ID = 1280396795046006836  # rôle admin fixe

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
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            created_ts INTEGER NOT NULL,
            outcome TEXT,
            incomplete INTEGER,
            last_ts INTEGER NOT NULL,
            creator_id INTEGER,
            leaderboard_id INTEGER NOT NULL DEFAULT 1
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS participants(
            message_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            leaderboard_id INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY(message_id, user_id, leaderboard_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS leaderboard_posts(
            guild_id INTEGER,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            leaderboard_id INTEGER NOT NULL,
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
def upsert_message(con: sqlite3.Connection, message: discord.Message, creator_id: Optional[int] = None, leaderboard_id: int = 1):
    cur = con.cursor()
    cur.execute("""
        INSERT INTO messages(message_id, guild_id, channel_id, created_ts, outcome, incomplete, last_ts, creator_id, leaderboard_id)
        VALUES (?,?,?,?,NULL,0,?,?,?)
        ON CONFLICT(message_id) DO NOTHING
    """, (message.id, message.guild.id, message.channel.id,
          int(message.created_at.replace(tzinfo=timezone.utc).timestamp()), utcnow_i(), creator_id, leaderboard_id))

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

@with_db
def add_participant(con: sqlite3.Connection, message_id: int, user_id: int, leaderboard_id: int):
    cur = con.cursor()
    cur.execute("""
        INSERT INTO participants(message_id, user_id, leaderboard_id) VALUES (?,?,?)
        ON CONFLICT(message_id, user_id, leaderboard_id) DO NOTHING
    """, (message_id, user_id, leaderboard_id))

@with_db
def remove_participant(con: sqlite3.Connection, message_id: int, user_id: int, leaderboard_id: int):
    cur = con.cursor()
    cur.execute("DELETE FROM participants WHERE message_id=? AND user_id=? AND leaderboard_id=?", (message_id, user_id, leaderboard_id))

@with_db
def get_leaderboard_post(con: sqlite3.Connection, guild_id: int, type_: str) -> Optional[Tuple[int,int,int]]:
    cur = con.cursor()
    cur.execute("SELECT channel_id, message_id, leaderboard_id FROM leaderboard_posts WHERE guild_id=? AND type=?", (guild_id, type_))
    row = cur.fetchone()
    if not row: return None
    return (row["channel_id"], row["message_id"], row["leaderboard_id"])

@with_db
def set_leaderboard_post(con: sqlite3.Connection, guild_id: int, channel_id: int, message_id: int, type_: str, leaderboard_id: int):
    cur = con.cursor()
    cur.execute("""
        INSERT INTO leaderboard_posts(guild_id, channel_id, message_id, type, leaderboard_id)
        VALUES (?,?,?,?,?)
        ON CONFLICT(guild_id, type) DO UPDATE SET channel_id=excluded.channel_id, message_id=excluded.message_id, leaderboard_id=excluded.leaderboard_id
    """, (guild_id, channel_id, message_id, type_, leaderboard_id))

@with_db
def agg_totals_all(con: sqlite3.Connection, guild_id: int, leaderboard_id: int) -> Tuple[int,int,int,int]:
    cur = con.cursor()
    cur.execute("""
        SELECT SUM(CASE WHEN outcome='win'  THEN 1 ELSE 0 END),
               SUM(CASE WHEN outcome='loss' THEN 1 ELSE 0 END),
               SUM(CASE WHEN incomplete=1  THEN 1 ELSE 0 END),
               COUNT(*)
        FROM messages
        WHERE guild_id=? AND leaderboard_id=?
    """, (guild_id, leaderboard_id))
    w,l,inc,tot = cur.fetchone()
    return (w or 0, l or 0, inc or 0, tot or 0)

@with_db
def top_defenders(con: sqlite3.Connection, guild_id: int, leaderboard_id: int, limit: int = 20) -> List[Tuple[int,int]]:
    cur = con.cursor()
    cur.execute("""
        SELECT p.user_id, COUNT(*) as cnt
        FROM participants p
        JOIN messages m ON m.message_id=p.message_id
        WHERE m.guild_id=? AND p.leaderboard_id=?
        GROUP BY p.user_id
        ORDER BY cnt DESC
        LIMIT ?
    """, (guild_id, leaderboard_id, limit))
    return [(row["user_id"], row["cnt"]) for row in cur.fetchall()]

@with_db
def top_pingeurs(con: sqlite3.Connection, guild_id: int, leaderboard_id: int, limit: int = 20) -> List[Tuple[int,int]]:
    cur = con.cursor()
    cur.execute("""
        SELECT creator_id, COUNT(*) as cnt
        FROM messages
        WHERE guild_id=? AND creator_id IS NOT NULL AND leaderboard_id=?
        GROUP BY creator_id
        ORDER BY cnt DESC
        LIMIT ?
    """, (guild_id, leaderboard_id, limit))
    return [(row["creator_id"], row["cnt"]) for row in cur.fetchall()]

@with_db
def get_next_leaderboard_id(con: sqlite3.Connection) -> int:
    cur = con.cursor()
    cur.execute("SELECT MAX(leaderboard_id) FROM leaderboard_posts")
    row = cur.fetchone()
    return (row[0] or 0) + 1

# ---------- Embed constructeur ----------
async def build_ping_embed(msg: discord.Message) -> discord.Embed:
    creator_id = get_message_creator(msg.id)
    creator_member = msg.guild.get_member(creator_id) if creator_id else None

    # Récupère les réactions
    reactions = {str(r.emoji): r for r in msg.reactions}
    win  = (EMOJI_VICTORY in reactions and reactions[EMOJI_VICTORY].count > 0)
    loss = (EMOJI_DEFEAT in reactions and reactions[EMOJI_DEFEAT].count > 0)
    incomplete = (EMOJI_INCOMP in reactions and reactions[EMOJI_INCOMP].count > 0)

    # Détermine l'état du combat
    if win and not loss:
        color = discord.Color.green()
        etat = f"{EMOJI_VICTORY} **Défense gagnée**"
        if incomplete:
            etat += f"\n{EMOJI_INCOMP} Défense incomplète"
    elif loss and not win:
        color = discord.Color.red()
        etat = f"{EMOJI_DEFEAT} **Défense perdue**"
        if incomplete:
            etat += f"\n{EMOJI_INCOMP} Défense incomplète"
    else:
        color = discord.Color.orange()
        etat = "⏳ **En cours / à confirmer**"
        if incomplete:
            etat += f"\n{EMOJI_INCOMP} Défense incomplète"

    # Défenseurs
    defenders_ids: List[int] = []
    if EMOJI_JOIN in reactions:
        async for u in reactions[EMOJI_JOIN].users():
            if not u.bot:
                defenders_ids.append(u.id)
                add_participant(msg.id, u.id, leaderboard_id=1)  # on pourrait passer leaderboard_id actif

    names: List[str] = []
    for uid in defenders_ids[:20]:
        m = msg.guild.get_member(uid)
        names.append(m.display_name if m else f"<@{uid}>")
    defenders_block = "• " + "\n• ".join(names) if names else "_Aucun défenseur pour le moment._"

    # Construction de l'embed
    embed = discord.Embed(
        title="🛡️ Alerte Percepteur",
        description="⚠️ **Connectez-vous pour prendre la défense !**",
        color=color,
    )
    embed.add_field(name="État du combat", value=etat, inline=False)
    embed.add_field(name="Défenseurs (👍)", value=defenders_block, inline=False)

    if creator_member:
        embed.add_field(name="⚡ Déclenché par", value=creator_member.display_name, inline=False)

    embed.set_footer(text="Ajoutez vos réactions : 🏆 gagné • ❌ perdu • 😡 incomplète • 👍 j'ai participé")
    return embed

# ---------- View boutons ----------
class PingButtonsView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Guilde 1", style=discord.ButtonStyle.primary)
    async def btn_def(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_click(interaction, side="Def")

    @discord.ui.button(label="Guilde 2", style=discord.ButtonStyle.danger)
    async def btn_def2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_click(interaction, side="Def2")

    @discord.ui.button(label="TEST (Admin)", style=discord.ButtonStyle.secondary)
    async def btn_test(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not any(r.permissions.administrator for r in interaction.user.roles):
            await interaction.response.send_message("Bouton réservé aux admins.", ephemeral=True)
            return
        await self._handle_click(interaction, side="Test")

    async def _handle_click(self, interaction: discord.Interaction, side: str):
        try:
            await interaction.response.defer(ephemeral=True, thinking=False)
        except Exception:
            pass

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

        role = guild.get_role(role_id) if role_id else None
        mention = role.mention if role else "Pas de rôle"
        msg = await alert_channel.send(f"{mention} ⚠️ Nouveau percepteur à défendre !")
        upsert_message(msg, creator_id=interaction.user.id, leaderboard_id=1)  # TODO: gérer leaderboard_id actif
        view = PingButtonsView(self.bot)
        embed = await build_ping_embed(msg)
        await msg.edit(embed=embed, view=view)

# ---------- Cog ----------
class PingPanel(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        create_db()

    @app_commands.command(name="pingpanel")
    async def pingpanel(self, interaction: discord.Interaction):
        """Génère le message de ping initial"""
        await interaction.response.defer(ephemeral=True)
        alert_channel = interaction.guild.get_channel(ALERT_CHANNEL_ID)
        if not isinstance(alert_channel, discord.TextChannel):
            await interaction.followup.send("Erreur : canal alert introuvable.", ephemeral=True)
            return

        view = PingButtonsView(self.bot)
        msg = await alert_channel.send("⚠️ Nouveau percepteur à défendre !", view=view)
        upsert_message(msg, creator_id=interaction.user.id, leaderboard_id=1)
        embed = await build_ping_embed(msg)
        await msg.edit(embed=embed)
        await interaction.followup.send("Message ping généré.", ephemeral=True)

    @app_commands.command(name="reset_defense")
    async def reset_defense(self, interaction: discord.Interaction):
        """Reset le leaderboard Défense"""
        if not any(r.id == ROLE_ADMIN_ID for r in interaction.user.roles):
            await interaction.response.send_message("Commande réservée aux Admins.", ephemeral=True)
            return

        await self._reset_leaderboard(interaction, type_="defense")

    @app_commands.command(name="reset_pingeur")
    async def reset_pingeur(self, interaction: discord.Interaction):
        """Reset le leaderboard Pingeur"""
        if not any(r.id == ROLE_ADMIN_ID for r in interaction.user.roles):
            await interaction.response.send_message("Commande réservée aux Admins.", ephemeral=True)
            return

        await self._reset_leaderboard(interaction, type_="pingeur")

    async def _reset_leaderboard(self, interaction: discord.Interaction, type_: str):
        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        # Récup leaderboard actuel
        cur.execute("SELECT channel_id, message_id, leaderboard_id FROM leaderboard_posts WHERE guild_id=? AND type=?", (interaction.guild.id, type_))
        row = cur.fetchone()
        if not row:
            await interaction.response.send_message(f"Pas de leaderboard {type_} actif.", ephemeral=True)
            con.close()
            return
        channel_id, message_id, old_id = row
        channel = interaction.guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("Canal du leaderboard introuvable.", ephemeral=True)
            con.close()
            return
        try:
            old_msg = await channel.fetch_message(message_id)
        except Exception:
            old_msg = None

        # Archiver ancien leaderboard
        archive_channel = interaction.guild.get_channel(ARCHIVE_CHANNEL_ID)
        if old_msg and isinstance(archive_channel, discord.TextChannel):
            ts = datetime.now(ZoneInfo("Europe/Paris")).strftime("%Y-%m-%d %H:%M")
            await archive_channel.send(f"📊 Leaderboard {type_} archivé ({ts}) :", embed=old_msg.embeds[0] if old_msg.embeds else None)

        # Nouveau leaderboard_id
        cur.execute("SELECT MAX(leaderboard_id) FROM leaderboard_posts")
        row2 = cur.fetchone()
        new_id = (row2[0] or 0) + 1

        # Créer nouveau message
        lb_channel = interaction.guild.get_channel(LEADERBOARD_CHANNEL_ID)
        if not isinstance(lb_channel, discord.TextChannel):
            await interaction.response.send_message("Canal pour nouveau leaderboard introuvable.", ephemeral=True)
            con.close()
            return

        ts = datetime.now(ZoneInfo("Europe/Paris")).strftime("%Y-%m-%d %H:%M")
        embed = discord.Embed(
            title=f"📊 Leaderboard {type_.capitalize()}",
            description=f"_Nouveau leaderboard créé le {ts}_",
            color=discord.Color.blurple()
        )
        new_msg = await lb_channel.send(embed=embed)
        cur.execute("""
            INSERT OR REPLACE INTO leaderboard_posts(guild_id, channel_id, message_id, type, leaderboard_id)
            VALUES (?,?,?,?,?)
        """, (interaction.guild.id, lb_channel.id, new_msg.id, type_, new_id))
        con.commit()
        con.close()
        await interaction.response.send_message(f"Leaderboard {type_} réinitialisé et archivé.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(PingPanel(bot))
