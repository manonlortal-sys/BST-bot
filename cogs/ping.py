# cogs/ping.py
# Panneau de ping percepteur + leaderboard défense auto (sans commande d’attache)
# ENV requis:
#   ALERT_CHANNEL_ID        -> salon où envoyer les alertes (int)
#   LEADERBOARD_CHANNEL_ID  -> salon du leaderboard (int)
#   ROLE_DEF_ID             -> rôle "Def" (int)
#   ROLE_DEF2_ID            -> rôle "Def2" (int)

from __future__ import annotations
import os
import time
import sqlite3
from datetime import datetime, timezone
from typing import Optional, Tuple, List, Dict

import discord
from discord import app_commands
from discord.ext import commands
import asyncio

# ---------- ENV ----------
ALERT_CHANNEL_ID = int(os.getenv("ALERT_CHANNEL_ID", "0"))
LEADERBOARD_CHANNEL_ID = int(os.getenv("LEADERBOARD_CHANNEL_ID", "0"))
ROLE_DEF_ID = int(os.getenv("ROLE_DEF_ID", "0"))
ROLE_DEF2_ID = int(os.getenv("ROLE_DEF2_ID", "0"))

# ---------- Constantes ----------
EMOJI_VICTORY = "🏆"
EMOJI_DEFEAT  = "❌"
EMOJI_INCOMP  = "😡"
EMOJI_JOIN    = "👍"

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
            outcome    TEXT,         -- 'win' | 'loss' | NULL
            incomplete INTEGER,      -- 0/1
            last_ts    INTEGER NOT NULL
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
            guild_id   INTEGER PRIMARY KEY,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL
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

@with_db
def upsert_message(con: sqlite3.Connection, message: discord.Message):
    cur = con.cursor()
    cur.execute("""
        INSERT INTO messages(message_id, guild_id, channel_id, created_ts, outcome, incomplete, last_ts)
        VALUES (?,?,?,?,NULL,0,?)
        ON CONFLICT(message_id) DO NOTHING
    """, (message.id, message.guild.id, message.channel.id, int(message.created_at.replace(tzinfo=timezone.utc).timestamp()), utcnow_i()))

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
def get_leaderboard_post(con: sqlite3.Connection, guild_id: int) -> Optional[Tuple[int,int]]:
    cur = con.cursor()
    cur.execute("SELECT channel_id, message_id FROM leaderboard_posts WHERE guild_id=?", (guild_id,))
    row = cur.fetchone()
    if not row: return None
    return (row["channel_id"], row["message_id"])

@with_db
def set_leaderboard_post(con: sqlite3.Connection, guild_id: int, channel_id: int, message_id: int):
    cur = con.cursor()
    cur.execute("""
        INSERT INTO leaderboard_posts(guild_id, channel_id, message_id)
        VALUES (?,?,?)
        ON CONFLICT(guild_id) DO UPDATE SET channel_id=excluded.channel_id, message_id=excluded.message_id
    """, (guild_id, channel_id, message_id))

@with_db
def agg_totals_all(con: sqlite3.Connection, guild_id: int) -> Tuple[int,int,int,int]:
    cur = con.cursor()
    cur.execute("""
        SELECT
          SUM(CASE WHEN outcome='win'  THEN 1 ELSE 0 END),
          SUM(CASE WHEN outcome='loss' THEN 1 ELSE 0 END),
          SUM(CASE WHEN incomplete=1  THEN 1 ELSE 0 END),
          COUNT(*)
        FROM messages WHERE guild_id=?
    """, (guild_id,))
    w,l,inc,tot = cur.fetchone()
    return (w or 0, l or 0, inc or 0, tot or 0)

@with_db
def agg_totals_7d(con: sqlite3.Connection, guild_id: int) -> Tuple[int,int,int,int]:
    since = utcnow_i() - 7*24*3600
    cur = con.cursor()
    cur.execute("""
        SELECT
          SUM(CASE WHEN outcome='win'  THEN 1 ELSE 0 END),
          SUM(CASE WHEN outcome='loss' THEN 1 ELSE 0 END),
          SUM(CASE WHEN incomplete=1  THEN 1 ELSE 0 END),
          COUNT(*)
        FROM messages WHERE guild_id=? AND created_ts>=?
    """, (guild_id, since))
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

# ---------- Embed constructeur ----------
async def build_ping_embed(msg: discord.Message) -> discord.Embed:
    reactions = {str(r.emoji): r for r in msg.reactions}

    win  = (EMOJI_VICTORY in reactions and reactions[EMOJI_VICTORY].count > 0)
    loss = (EMOJI_DEFEAT  in reactions and reactions[EMOJI_DEFEAT].count  > 0)

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

    async def _handle_click(self, interaction: discord.Interaction, side: str):
        try:
            await interaction.response.defer(ephemeral=True, thinking=False)
        except Exception:
            pass  # si déjà acquitté

        guild = interaction.guild
        if guild is None:
            return

        if ALERT_CHANNEL_ID == 0:
            return await interaction.followup.send("❌ ALERT_CHANNEL_ID non configuré.", ephemeral=True)

        alert_channel = guild.get_channel(ALERT_CHANNEL_ID)
        if not isinstance(alert_channel, discord.TextChannel):
            return await interaction.followup.send("❌ Salon d’alertes introuvable.", ephemeral=True)

        role_id = ROLE_DEF_ID if side == "Def" else ROLE_DEF2_ID
        if role_id == 0:
            return await interaction.followup.send(f"❌ ROLE_{side.upper()}_ID non configuré.", ephemeral=True)

        role_mention = f"<@&{role_id}>"

        # Envoi du message d’alerte (ping HORS embed)
        content = f"{role_mention} — **Percepteur attaqué !** Merci de vous connecter."
        msg = await alert_channel.send(content=content)

        # Ajouter l'embed propre
        emb = await build_ping_embed(msg)
        await msg.edit(embed=emb)

        # Initialiser en DB pour leaderboard
        upsert_message(msg)

        # Informer l’utilisateur
        await interaction.followup.send("✅ Alerte envoyée.", ephemeral=True)

# ---------- Cog principal ----------
class PingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        create_db()
        # debounce per guild
        self._pending_update: Dict[int, asyncio.Task] = {}

    # Slash pour publier le panneau
    @app_commands.command(name="pingpanel", description="Publier le panneau de ping des percepteurs (boutons Def/Def2).")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def pingpanel(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True, thinking=False)
        except Exception:
            pass
        view = PingButtonsView(self.bot)

        embed = discord.Embed(
            title="📣 Bot de Ping",
            description="Cliquez sur la guilde qui se fait attaquer pour **alerter les joueurs**.\n**Ne cliquez qu'une seule fois.**",
            color=discord.Color.orange(),
        )
        await interaction.channel.send(embed=embed, view=view)
        await interaction.followup.send("✅ Panneau publié.", ephemeral=True)

    # Listeners réactions -> MAJ embed + MAJ leaderboard
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        await self._handle_reaction(payload, added=True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        await self._handle_reaction(payload, added=False)

    async def _handle_reaction(self, payload: discord.RawReactionActionEvent, added: bool):
        if payload.guild_id is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        channel = guild.get_channel(payload.channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return

        try:
            msg = await channel.fetch_message(payload.message_id)
        except discord.NotFound:
            return

        # On ne met à jour que nos messages d’alerte (titre de l'embed)
        if not msg.embeds or (msg.embeds[0].title or "") != "🛡️ Alerte Percepteur":
            # Si pas encore d'embed (premier envoi), on ne bloque pas l’enregistrement DB
            pass

        # Enreg/MAJ DB
        upsert_message(msg)
        emoji = str(payload.emoji)

        if emoji == EMOJI_VICTORY:
            if added:
                set_outcome(msg.id, "win")
            else:
                # si on retire 🏆, recalculer via réactions restantes
                if not any(str(r.emoji) == EMOJI_VICTORY and r.count > 0 for r in msg.reactions):
                    if any(str(r.emoji) == EMOJI_DEFEAT and r.count > 0 for r in msg.reactions):
                        set_outcome(msg.id, "loss")
                    else:
                        set_outcome(msg.id, None)

        elif emoji == EMOJI_DEFEAT:
            if added:
                set_outcome(msg.id, "loss")
            else:
                if not any(str(r.emoji) == EMOJI_DEFEAT and r.count > 0 for r in msg.reactions):
                    if any(str(r.emoji) == EMOJI_VICTORY and r.count > 0 for r in msg.reactions):
                        set_outcome(msg.id, "win")
                    else:
                        set_outcome(msg.id, None)

        elif emoji == EMOJI_INCOMP:
            # bool si présent ou non; on reflète juste l’action
            set_incomplete(msg.id, added)

        elif emoji == EMOJI_JOIN:
            if added:
                add_participant(msg.id, payload.user_id)
            else:
                remove_participant(msg.id, payload.user_id)

        # Rafraîchir l'embed du message d’alerte
        try:
            new_embed = await build_ping_embed(msg)
            await msg.edit(embed=new_embed)
        except Exception as e:
            print("ping embed update error:", e)

        # MAJ leaderboard auto
        await self._schedule_update(guild)

    async def _schedule_update(self, guild: discord.Guild):
        if guild.id in self._pending_update and not self._pending_update[guild.id].done():
            return
        async def _delayed():
            await asyncio.sleep(1.0)
            try:
                await self._update_leaderboard(guild)
            except Exception as e:
                print("leaderboard update error:", e)
        self._pending_update[guild.id] = asyncio.create_task(_delayed())

    async def _update_leaderboard(self, guild: discord.Guild):
        if LEADERBOARD_CHANNEL_ID == 0:
            return  # pas configuré

        lb_channel = guild.get_channel(LEADERBOARD_CHANNEL_ID)
        if not isinstance(lb_channel, discord.TextChannel):
            return

        post = get_leaderboard_post(guild.id)
        msg = None
        if post:
            ch_id, msg_id = post
            if ch_id == lb_channel.id:
                try:
                    msg = await lb_channel.fetch_message(msg_id)
                except discord.NotFound:
                    msg = None

        # Récup agrégats
        w_all, l_all, inc_all, tot_all = agg_totals_all(guild.id)
        w_7d,  l_7d,  inc_7d,  tot_7d  = agg_totals_7d(guild.id)
        split = hourly_split_7d(guild.id)
        top = top_defenders(guild.id, 20)

        # Couleur
        if w_all > l_all:
            color = discord.Color.green()
        elif l_all > w_all:
            color = discord.Color.red()
        else:
            color = discord.Color.orange()

        lines = []
        medals = ["🥇","🥈","🥉"]
        for i, (uid, cnt) in enumerate(top, start=1):
            member = guild.get_member(uid)
            name = member.display_name if member else f"<@{uid}>"
            prefix = medals[i-1] if i <= 3 else f"{i:02d}."
            lines.append(f"{prefix} {name} — **{cnt}** déf.")
        top_block = "\n".join(lines) if lines else "_Aucun participant détecté._"

        global_block = (
            f"**Victoires** {EMOJI_VICTORY} : **{w_all}**\n"
            f"**Défaites** {EMOJI_DEFEAT} : **{l_all}**\n"
            f"**Incomplètes** {EMOJI_INCOMP} : **{inc_all}**\n"
            f"**Total** : **{tot_all}**"
        )
        block_7d = (
            f"**Victoires** {EMOJI_VICTORY} : **{w_7d}**\n"
            f"**Défaites** {EMOJI_DEFEAT} : **{l_7d}**\n"
            f"**Incomplètes** {EMOJI_INCOMP} : **{inc_7d}**\n"
            f"**Total** : **{tot_7d}**"
        )
        total_split = sum(split) or 1
        bucket_lines = []
        for (label, _, _), count in zip(BUCKETS, split):
            pct = int(round(count * 100 / total_split))
            bucket_lines.append(f"{label} → **{pct}%** ({count})")
        split_block = "\n".join(bucket_lines)

        embed = discord.Embed(
            title="🛡️ Leaderboard Défense",
            color=color,
        )
        embed.add_field(name="📊 Top défenseurs (participations)", value=top_block[:1024] or "\u200b", inline=False)
        embed.add_field(name="⚔️ Statistiques globales", value=global_block, inline=True)
        embed.add_field(name="⏳ 7 derniers jours", value=block_7d, inline=True)
        embed.add_field(name="🕒 Répartition horaire (7j)", value=split_block, inline=False)
        embed.set_footer(text="MàJ automatique — réactions : 🏆 ❌ 😡 👍")

        if msg is None:
            # Créer le post initial
            msg = await lb_channel.send(embed=embed)
            set_leaderboard_post(guild.id, lb_channel.id, msg.id)
        else:
            await msg.edit(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(PingCog(bot))
