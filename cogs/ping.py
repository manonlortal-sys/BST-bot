from __future__ import annotations
import os
import time
import sqlite3
from datetime import datetime, timezone
from typing import Optional, Tuple, List
from zoneinfo import ZoneInfo

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
ADMIN_ROLE_ID = 1280396795046006836  # Rôle Admin fixe

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

@with_db
def get_leaderboard_post(con: sqlite3.Connection, guild_id: int, type_: str) -> Optional[Tuple[int,int]]:
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
def get_panel_message(con: sqlite3.Connection, guild_id: int) -> Optional[Tuple[int,int]]:
    cur = con.cursor()
    cur.execute("SELECT channel_id, message_id FROM panel_messages WHERE guild_id=?", (guild_id,))
    row = cur.fetchone()
    return (row["channel_id"], row["message_id"]) if row else None

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

# ---------- Embed constructeur ----------
async def build_ping_embed(msg: discord.Message) -> discord.Embed:
    creator_id = get_message_creator(msg.id)
    creator_member = msg.guild.get_member(creator_id) if creator_id else None
    reactions = {str(r.emoji): r for r in msg.reactions}
    win  = (EMOJI_VICTORY in reactions and reactions[EMOJI_VICTORY].count > 0)
    loss = (EMOJI_DEFEAT in reactions and reactions[EMOJI_DEFEAT].count > 0)
    incomplete = (EMOJI_INCOMP in reactions and reactions[EMOJI_INCOMP].count > 0)

    if win and not loss:
        color = discord.Color.green()
        etat = f"{EMOJI_VICTORY} **Défense gagnée**"
        if incomplete: etat += f"\n{EMOJI_INCOMP} Défense incomplète"
    elif loss and not win:
        color = discord.Color.red()
        etat = f"{EMOJI_DEFEAT} **Défense perdue**"
        if incomplete: etat += f"\n{EMOJI_INCOMP} Défense incomplète"
    else:
        color = discord.Color.orange()
        etat = "⏳ **En cours / à confirmer**"
        if incomplete: etat += f"\n{EMOJI_INCOMP} Défense incomplète"

    defenders_ids: List[int] = []
    if EMOJI_JOIN in reactions:
        try:
            async for u in reactions[EMOJI_JOIN].users():
                if not u.bot:
                    defenders_ids.append(u.id)
                    add_participant(msg.id, u.id)
        except Exception:
            # Si l'itération des users échoue pour une raison (permissions), on ignore
            pass

    names = [msg.guild.get_member(uid).display_name if msg.guild.get_member(uid) else f"<@{uid}>" for uid in defenders_ids[:20]]
    defenders_block = "• " + "\n• ".join(names) if names else "_Aucun défenseur pour le moment._"

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

    async def _handle_click(self, interaction: discord.Interaction, role_id: int):
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

        role_mention = f"<@&{role_id}>" if role_id else ""
        content = f"{role_mention} — **Percepteur attaqué !** Merci de vous connecter." if role_mention else "**Percepteur attaqué !** Merci de vous connecter."

        msg = await alert_channel.send(content)
        upsert_message(msg, creator_id=interaction.user.id)
        # Incrémente le total "pingeur" (leaderboard depuis reset)
        incr_leaderboard(interaction.guild.id, "pingeur", interaction.user.id)
        emb = await build_ping_embed(msg)
        try:
            await msg.edit(embed=emb)
        except Exception:
            pass
        await update_leaderboards(self.bot, guild)
        try:
            await interaction.followup.send("✅ Alerte envoyée.", ephemeral=True)
        except Exception:
            pass

    @discord.ui.button(label="Guilde 1", style=discord.ButtonStyle.primary)
    async def btn_def(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_click(interaction, ROLE_DEF_ID)

    @discord.ui.button(label="Guilde 2", style=discord.ButtonStyle.danger)
    async def btn_def2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_click(interaction, ROLE_DEF2_ID)

    @discord.ui.button(label="TEST (Admin)", style=discord.ButtonStyle.secondary)
    async def btn_test(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not any(r.id == ADMIN_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("Bouton réservé aux admins.", ephemeral=True)
            return
        await self._handle_click(interaction, ROLE_TEST_ID)

# ---------- Leaderboards ----------
async def update_leaderboards(bot: commands.Bot, guild: discord.Guild):
    channel = bot.get_channel(LEADERBOARD_CHANNEL_ID)
    if channel is None:
        return

    # ---------- Leaderboard Défense ----------
    def_post = get_leaderboard_post(guild.id, "defense")
    if def_post:
        try:
            msg_def = await channel.fetch_message(def_post[1])
        except discord.NotFound:
            msg_def = await channel.send("📊 **Leaderboard Défense**")
            set_leaderboard_post(guild.id, channel.id, msg_def.id, "defense")
    else:
        msg_def = await channel.send("📊 **Leaderboard Défense**")
        set_leaderboard_post(guild.id, channel.id, msg_def.id, "defense")

    top_def = get_leaderboard_totals(guild.id, "defense")
    top_block = "\n".join([f"• <@{uid}> : {cnt} défenses" for uid, cnt in top_def]) or "_Aucun défenseur encore_"

    # Ajouter quelques stats globales (optionnel) basées sur messages historiques
    total_w, total_l, total_inc, total_att = agg_totals_all(guild.id)
    ratio = f"{(total_w/total_att*100):.1f}%" if total_att else "0%"

    embed_def = discord.Embed(title="📊 Leaderboard Défense", color=discord.Color.blue())
    embed_def.add_field(name="Top défenseurs", value=top_block, inline=False)
    embed_def.add_field(
        name="Stats globales (historique)",
        value=f"Attaques : {total_att}\nVictoire : {total_w}\nDéfaites : {total_l}\nIncomplet : {total_inc}\nRatio victoire : {ratio}",
        inline=False
    )
    await msg_def.edit(embed=embed_def)

    # ---------- Leaderboard Pingeurs ----------
    ping_post = get_leaderboard_post(guild.id, "pingeur")
    if ping_post:
        try:
            msg_ping = await channel.fetch_message(ping_post[1])
        except discord.NotFound:
            msg_ping = await channel.send("📊 **Leaderboard Pingeurs**")
            set_leaderboard_post(guild.id, channel.id, msg_ping.id, "pingeur")
    else:
        msg_ping = await channel.send("📊 **Leaderboard Pingeurs**")
        set_leaderboard_post(guild.id, channel.id, msg_ping.id, "pingeur")

    top_ping = get_leaderboard_totals(guild.id, "pingeur")
    ping_block = "\n".join([f"• <@{uid}> : {cnt} pings" for uid, cnt in top_ping]) or "_Aucun pingeur encore_"
    embed_ping = discord.Embed(title="📊 Leaderboard Pingeurs", color=discord.Color.gold())
    embed_ping.add_field(name="Top pingeurs", value=ping_block, inline=False)
    await msg_ping.edit(embed=embed_ping)

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
        # envoyer le panneau et sauvegarder son message_id
        msg = await interaction.response.send_message(embed=embed, view=view, ephemeral=False)
        # note: discord.py retourne None pour response.send_message, so fetch original message via followup if needed
        try:
            # try to get the sent message via followup.fetch if available (some versions)
            # fallback: we saved nothing here and cog_load will handle re-attaching if you manually save the panel
            pass
        except Exception:
            pass
        # If you prefer to fetch the message object to record channel/message id for persistence,
        # you can send the message via channel.send directly instead of response.send_message.
        # To keep behavior consistent with prior code, set_panel_message is called externally when using channel.send.
        # set_panel_message(interaction.guild.id, msg.channel.id, msg.id)

    @app_commands.command(name="stats", description="Voir les stats d’un joueur")
    @app_commands.describe(member="Membre à inspecter (optionnel)")
    async def stats(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Impossible de récupérer le guild.", ephemeral=True)
            return
        defenses, pings, wins, losses = get_player_stats(guild.id, target.id)
        embed = discord.Embed(
            title=f"📊 Stats de {target.display_name}",
            color=discord.Color.purple()
        )
        embed.add_field(name="🛡️ Défenses prises", value=f"{defenses}", inline=False)
        embed.add_field(name="⚡ Pings faits", value=f"{pings}", inline=False)
        embed.add_field(name="🏆 Victoires", value=f"{wins}", inline=True)
        embed.add_field(name="❌ Défaites", value=f"{losses}", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=False)

    # ---------- Resets ----------
    @app_commands.command(name="reset_defense", description="Archiver et réinitialiser le leaderboard Défense")
    async def reset_defense(self, interaction: discord.Interaction):
        await self._reset_leaderboard(interaction, "defense", "📊 Leaderboard Défense")

    @app_commands.command(name="reset_pingeur", description="Archiver et réinitialiser le leaderboard Pingeurs")
    async def reset_pingeur(self, interaction: discord.Interaction):
        await self._reset_leaderboard(interaction, "pingeur", "📊 Leaderboard Pingeurs")

    async def _reset_leaderboard(self, interaction: discord.Interaction, type_: str, title: str):
        if not any(r.id == ADMIN_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("Commande réservée aux admins.", ephemeral=True)
            return

        channel = self.bot.get_channel(LEADERBOARD_CHANNEL_ID)
        archive_channel = self.bot.get_channel(ARCHIVE_CHANNEL_ID)
        if not channel or not archive_channel:
            await interaction.response.send_message("Canal introuvable.", ephemeral=True)
            return

        post = get_leaderboard_post(interaction.guild.id, type_)
        if post:
            try:
                msg = await channel.fetch_message(post[1])
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if msg.embeds:
                    archive_embed = msg.embeds[0]
                    archive_embed.set_footer(text=f"Archivé le {timestamp}")
                    await archive_channel.send(embed=archive_embed)
                else:
                    await archive_channel.send(f"{title} archivé — {timestamp}")
            except discord.NotFound:
                pass

        # Reset uniquement les totaux du leaderboard (on ne touche PAS à messages/participants)
        reset_leaderboard_totals(interaction.guild.id, type_)

        new_msg = await channel.send(f"{title}\n*(mis à jour le {datetime.now().strftime('%Y-%m-%d %H:%M:%S')})*")
        set_leaderboard_post(interaction.guild.id, channel.id, new_msg.id, type_)

        await interaction.response.send_message(f"{title} réinitialisé et archivé.", ephemeral=True)

    # ---------- Listeners ----------
    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User):
        if user.bot:
            return
        msg = reaction.message
        if msg.guild is None:
            return
        if str(reaction.emoji) in (EMOJI_VICTORY, EMOJI_DEFEAT, EMOJI_INCOMP, EMOJI_JOIN):
            if str(reaction.emoji) == EMOJI_JOIN:
                # incr only if not already participant for this message
                if not participant_exists(msg.id, user.id):
                    add_participant(msg.id, user.id)
                    incr_leaderboard(msg.guild.id, "defense", user.id)
            elif str(reaction.emoji) == EMOJI_VICTORY:
                set_outcome(msg.id, "win")
            elif str(reaction.emoji) == EMOJI_DEFEAT:
                set_outcome(msg.id, "loss")
            elif str(reaction.emoji) == EMOJI_INCOMP:
                set_incomplete(msg.id, True)
            emb = await build_ping_embed(msg)
            try:
                await msg.edit(embed=emb)
            except Exception:
                pass
            await update_leaderboards(self.bot, msg.guild)

    @commands.Cog.listener()
    async def on_reaction_remove(self, reaction: discord.Reaction, user: discord.User):
        if user.bot:
            return
        msg = reaction.message
        if msg.guild is None:
            return
        if str(reaction.emoji) in (EMOJI_VICTORY, EMOJI_DEFEAT, EMOJI_INCOMP, EMOJI_JOIN):
            if str(reaction.emoji) == EMOJI_JOIN:
                # decr only if participant existed
                if participant_exists(msg.id, user.id):
                    remove_participant(msg.id, user.id)
                    decr_leaderboard(msg.guild.id, "defense", user.id)
            elif str(reaction.emoji) == EMOJI_VICTORY:
                set_outcome(msg.id, None)
            elif str(reaction.emoji) == EMOJI_DEFEAT:
                set_outcome(msg.id, None)
            elif str(reaction.emoji) == EMOJI_INCOMP:
                set_incomplete(msg.id, False)
            emb = await build_ping_embed(msg)
            try:
                await msg.edit(embed=emb)
            except Exception:
                pass
            await update_leaderboards(self.bot, msg.guild)

    async def cog_load(self):
        # Ré-attacher le panel existant pour que les boutons fonctionnent après redéploiement
        print(f"{self.__class__.__name__} chargé")
        for guild in self.bot.guilds:
            panel_info = get_panel_message(guild.id)
            if panel_info:
                channel = self.bot.get_channel(panel_info[0])
                if channel:
                    try:
                        msg = await channel.fetch_message(panel_info[1])
                        await msg.edit(view=PingButtonsView(self.bot))
                    except discord.NotFound:
                        pass

# ---------- Setup ----------
async def setup(bot: commands.Bot):
    cog = PingCog(bot)
    await bot.add_cog(cog)

    TEST_GUILD_ID = 1280234399610179634
    test_guild = discord.Object(id=TEST_GUILD_ID)

    bot.tree.add_command(cog.pingpanel, guild=test_guild)
    bot.tree.add_command(cog.reset_defense, guild=test_guild)
    bot.tree.add_command(cog.reset_pingeur, guild=test_guild)
    bot.tree.add_command(cog.stats, guild=test_guild)
    await bot.tree.sync(guild=test_guild)
