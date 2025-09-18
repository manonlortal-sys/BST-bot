# cogs/ping.py
# Panneau de ping (Def / Def2) + suivi des réactions + leaderboard auto des "pingeurs"
import os
import sqlite3
import datetime
from zoneinfo import ZoneInfo
from typing import Dict, Set, Optional, Tuple, List

import discord
from discord import app_commands
from discord.ext import commands
import asyncio

# =========================
#  ENV VARS (Render → Environment)
# =========================
CHANNEL_BUTTONS_ID = int(os.getenv("CHANNEL_BUTTONS_ID", "0"))        # salon où le panneau est publié
CHANNEL_DEFENSE_ID = int(os.getenv("CHANNEL_DEFENSE_ID", "0"))        # salon où l’alerte est envoyée
PING_LEADERBOARD_CHANNEL_ID = int(os.getenv("PING_LEADERBOARD_CHANNEL_ID", "0"))  # salon du leaderboard auto
ROLE_DEF_ID = int(os.getenv("ROLE_DEF_ID", "0"))                      # rôle @Def (ID) – facultatif
ROLE_DEF2_ID = int(os.getenv("ROLE_DEF2_ID", "0"))                    # rôle @Def2 (ID) – facultatif
DB_PATH = os.getenv("PING_DB_PATH", "ping_data.db")                   # chemin de la base SQLite

TZ = ZoneInfo("Europe/Paris")
ORANGE = discord.Color.orange()
GREEN = discord.Color.green()
RED = discord.Color.red()

# Autoriser les pings de rôles uniquement (sécurité)
ALLOWED_MENTIONS_ROLES = discord.AllowedMentions(roles=True, users=False, everyone=False)


# =========================
#  État d'une alerte (en mémoire)
# =========================
class AlertState:
    def __init__(
        self,
        guild_id: int,
        channel_id: int,
        base_message_id: int,
        embed_message_id: int,
        side: str,                    # "Def" | "Def2"
        clicked_by_id: int
    ):
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.base_message_id = base_message_id      # message texte avec la mention du rôle
        self.embed_message_id = embed_message_id    # message embed à éditer
        self.side = side
        self.clicked_by_id = clicked_by_id
        self.won: bool = False
        self.lost: bool = False
        self.incomplete: bool = False               # orthogonal à won/lost
        self.participants: Set[int] = set()         # utilisateurs ayant mis 👍


# base_message_id -> state
alert_states: Dict[int, AlertState] = {}


# =========================
#  Helpers – Embeds & rôles
# =========================
def _title_for_side(side: str) -> str:
    return "⚠️ Alerte Percepteur – Guilde 1" if side == "Def" else "⚠️ Alerte Percepteur – Guilde 2"


def _status_and_color(state: AlertState) -> Tuple[str, discord.Color]:
    # Texte d'état + couleur, avec "incomplète" orthogonal
    suffix = " (incomplète)" if state.incomplete and (state.won or state.lost) else ""
    if state.won:
        return f"🏆 **Défense gagnée{suffix}**", GREEN
    if state.lost:
        return f"❌ **Défense perdue{suffix}**", RED
    if state.incomplete:
        return "😡 **Défense incomplète**", ORANGE
    return "⏳ Défense en cours (réagissez pour mettre à jour)", ORANGE


def build_embed(state: AlertState, guild: Optional[discord.Guild]) -> discord.Embed:
    status_line, color = _status_and_color(state)

    e = discord.Embed(
        title=_title_for_side(state.side),
        description="🔔 **Connectez-vous pour prendre la défense**\n\n" + status_line,
        color=color,
        timestamp=datetime.datetime.now(tz=TZ)
    )

    # Indication du déclencheur (dans l'embed seulement)
    e.add_field(name="🧑‍✈️ Déclenché par", value=f"<@{state.clicked_by_id}>", inline=True)

    # Liste des défenseurs (👍)
    if state.participants:
        names = []
        if guild:
            for uid in list(state.participants)[:25]:
                m = guild.get_member(uid)
                names.append(m.display_name if m else f"<@{uid}>")
        else:
            for uid in list(state.participants)[:25]:
                names.append(f"<@{uid}>")
        e.add_field(name="🛡️ Défenseurs (👍)", value=", ".join(names), inline=False)
    else:
        e.add_field(name="🛡️ Défenseurs (👍)", value="—", inline=False)

    e.set_footer(text="Ajoutez : 🏆 (gagnée), ❌ (perdue), 😡 (incomplète), 👍 (participation)")
    return e


def _resolve_role(guild: discord.Guild, side: str) -> Optional[discord.Role]:
    """Retourne le rôle Def/Def2 soit par ID (ENV), soit par nom."""
    if side == "Def":
        if ROLE_DEF_ID:
            r = guild.get_role(ROLE_DEF_ID)
            if r:
                return r
        return discord.utils.get(guild.roles, name="Def")
    else:
        if ROLE_DEF2_ID:
            r = guild.get_role(ROLE_DEF2_ID)
            if r:
                return r
        return discord.utils.get(guild.roles, name="Def2")


# =========================
#  SQLite utils (thread-safe via asyncio.to_thread)
# =========================
def _db_connect():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def _db_init():
    conn = _db_connect()
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ping_stats(
                guild_id INTEGER NOT NULL,
                user_id  INTEGER NOT NULL,
                count    INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS meta(
                guild_id INTEGER NOT NULL,
                key      TEXT NOT NULL,
                value    TEXT,
                PRIMARY KEY (guild_id, key)
            );
        """)
    conn.close()


def _db_inc_ping(guild_id: int, user_id: int):
    conn = _db_connect()
    with conn:
        conn.execute("""
            INSERT INTO ping_stats(guild_id, user_id, count)
            VALUES(?,?,1)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET count = count + 1;
        """, (guild_id, user_id))
    conn.close()


def _db_get_top(guild_id: int, limit: int = 15) -> List[tuple]:
    conn = _db_connect()
    cur = conn.execute("""
        SELECT user_id, count FROM ping_stats
        WHERE guild_id = ?
        ORDER BY count DESC, user_id ASC
        LIMIT ?;
    """, (guild_id, limit))
    rows = cur.fetchall()
    conn.close()
    return rows


def _db_get_meta(guild_id: int, key: str) -> Optional[str]:
    conn = _db_connect()
    cur = conn.execute("SELECT value FROM meta WHERE guild_id = ? AND key = ?;", (guild_id, key))
    row = cur.fetchone()
    conn.close()
    return None if row is None else str(row[0])


def _db_set_meta(guild_id: int, key: str, value: str):
    conn = _db_connect()
    with conn:
        conn.execute("""
            INSERT INTO meta(guild_id, key, value)
            VALUES(?,?,?)
            ON CONFLICT(guild_id, key) DO UPDATE SET value=excluded.value;
        """, (guild_id, key, value))
    conn.close()


# =========================
#  Vue avec boutons (persistante)
# =========================
class PingButtonsView(discord.ui.View):
    """
    Panneau avec 2 boutons : Guilde 1 (@Def) / Guilde 2 (@Def2).
    Vue PERSISTANTE : enregistrez-la au démarrage avec bot.add_view(PingButtonsView()).
    """
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Guilde 1 (Def)", style=discord.ButtonStyle.primary, custom_id="ping_def")
    async def btn_def(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_click(interaction, side="Def")

    @discord.ui.button(label="Guilde 2 (Def2)", style=discord.ButtonStyle.danger, custom_id="ping_def2")
    async def btn_def2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_click(interaction, side="Def2")

    async def _handle_click(self, interaction: discord.Interaction, side: str):
        # Réponse immédiate (évite 10062)
        await interaction.response.send_message("📣 Envoi de l’alerte…", ephemeral=True)

        guild = interaction.guild
        if not isinstance(guild, discord.Guild):
            return

        # Canal cible pour l'alerte
        target_ch = guild.get_channel(CHANNEL_DEFENSE_ID) if CHANNEL_DEFENSE_ID else None
        if not isinstance(target_ch, (discord.TextChannel, discord.Thread)):
            await interaction.followup.send("⚠️ Salon d’alerte introuvable ou non configuré.", ephemeral=True)
            return

        # Rôle Def / Def2
        role = _resolve_role(guild, side)
        if not isinstance(role, discord.Role):
            await interaction.followup.send(f"⚠️ Rôle `{side}` introuvable.", ephemeral=True)
            return

        guild_label = "Guilde 1" if side == "Def" else "Guilde 2"

        # Message texte (ping rôle)
        base_text = f"{role.mention} — **Percepteur attaqué** ({guild_label}) !"
        base_msg = await target_ch.send(content=base_text, allowed_mentions=ALLOWED_MENTIONS_ROLES)

        # Embed initial (reply au ping pour liaison visuelle)
        state = AlertState(
            guild_id=guild.id,
            channel_id=base_msg.channel.id,
            base_message_id=base_msg.id,
            embed_message_id=0,
            side=side,
            clicked_by_id=interaction.user.id,
        )
        embed = build_embed(state, guild)
        embed_msg = await target_ch.send(embed=embed, reference=base_msg, mention_author=False)

        # Mémoriser l'état (pour le suivi des réactions)
        state.embed_message_id = embed_msg.id
        alert_states[base_msg.id] = state

        # Incrémenter le compteur de pings (leaderboard)
        await asyncio.to_thread(_db_inc_ping, guild.id, interaction.user.id)
        # Rafraîchir/afficher le leaderboard auto
        await refresh_ping_leaderboard(guild)


# =========================
#  Leaderboard auto – helpers
# =========================
def _build_lb_embed(guild: discord.Guild, rows: List[tuple]) -> discord.Embed:
    e = discord.Embed(
        title="🏁 Leaderboard",
        description="Classement des pings (cumul serveur)",
        color=discord.Color.blurple(),
        timestamp=datetime.datetime.now(tz=TZ)
    )
    if not rows:
        e.add_field(name="Aucun ping", value="Personne n'a encore cliqué les boutons.", inline=False)
        return e

    lines = []
    for i, (uid, cnt) in enumerate(rows, start=1):
        member = guild.get_member(uid)
        name = member.display_name if member else f"<@{uid}>"
        lines.append(f"**{i}.** {name} — {cnt} ping{'s' if cnt>1 else ''}")
    # Discord limite ~1024 chars par field ; on limite proprement
    text = "\n".join(lines[:25])
    e.add_field(name="Classement", value=text or "—", inline=False)
    e.set_footer(text="Actualisé automatiquement")
    return e


async def refresh_ping_leaderboard(guild: discord.Guild):
    """Crée/édite un message unique 'Leaderboard' dans PING_LEADERBOARD_CHANNEL_ID pour ce serveur."""
    if PING_LEADERBOARD_CHANNEL_ID == 0:
        return
    ch = guild.get_channel(PING_LEADERBOARD_CHANNEL_ID)
    if not isinstance(ch, (discord.TextChannel, discord.Thread)):
        return

    rows = await asyncio.to_thread(_db_get_top, guild.id, 15)
    embed = _build_lb_embed(guild, rows)

    # On regarde si on a déjà un message enregistré
    msg_id_str = await asyncio.to_thread(_db_get_meta, guild.id, "ping_lb_message_id")
    msg_obj: Optional[discord.Message] = None
    if msg_id_str:
        try:
            msg_obj = await ch.fetch_message(int(msg_id_str))
        except discord.NotFound:
            msg_obj = None

    if msg_obj is None:
        # Créer nouveau message et mémoriser son id
        sent = await ch.send(embed=embed)
        await asyncio.to_thread(_db_set_meta, guild.id, "ping_lb_message_id", str(sent.id))
    else:
        try:
            await msg_obj.edit(embed=embed)
        except discord.NotFound:
            sent = await ch.send(embed=embed)
            await asyncio.to_thread(_db_set_meta, guild.id, "ping_lb_message_id", str(sent.id))


# =========================
#  Cog
# =========================
class PingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # Publie le panneau de boutons dans CHANNEL_BUTTONS_ID (ou dans le salon actuel si non défini)
    @app_commands.command(name="pingpanel", description="Publier le panneau de ping (@Def / @Def2).")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def pingpanel(self, interaction: discord.Interaction):
        # Réponse immédiate (évite 10062)
        await interaction.response.send_message("📌 Publication du panneau…", ephemeral=True)

        guild = interaction.guild
        if not isinstance(guild, discord.Guild):
            return

        panel_ch = guild.get_channel(CHANNEL_BUTTONS_ID) if CHANNEL_BUTTONS_ID else interaction.channel
        if not isinstance(panel_ch, (discord.TextChannel, discord.Thread)):
            await interaction.followup.send("⚠️ Salon panneau introuvable ou non textuel.", ephemeral=True)
            return

        embed = discord.Embed(
            title="📢 Bot de Ping Percepteur",
            description=(
                "Cliquez sur la guilde qui se fait attaquer pour **alerter les joueurs**.\n"
                "Ne cliquez **qu'une seule fois**."
            ),
            color=ORANGE
        )
        await panel_ch.send(embed=embed, view=PingButtonsView())

    # Mets à jour l'embed d'alerte au fil des réactions (dans CHANNEL_DEFENSE_ID)
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        await self._handle_reaction_update(payload, added=True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        await self._handle_reaction_update(payload, added=False)

    async def _handle_reaction_update(self, payload: discord.RawReactionActionEvent, added: bool):
        # Ne traite que le salon cible
        if CHANNEL_DEFENSE_ID == 0 or payload.channel_id != CHANNEL_DEFENSE_ID:
            return

        # Retrouver l'état par base_message_id ou embed_message_id
        state = alert_states.get(payload.message_id)
        if state is None:
            for st in alert_states.values():
                if st.embed_message_id == payload.message_id:
                    state = st
                    break
        if state is None:
            return

        # Ignore les bots
        if self.bot.user and payload.user_id == self.bot.user.id:
            return

        emoji = str(payload.emoji)

        # Récupérer le message embed
        channel = self.bot.get_channel(state.channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return
        try:
            embed_msg = await channel.fetch_message(state.embed_message_id)
        except discord.NotFound:
            return

        # Mettre à jour les drapeaux (won/lost exclusifs ; incomplete orthogonal)
        if emoji == "🏆":
            if added:
                state.won = True
                state.lost = False
            else:
                state.won = False
        elif emoji == "❌":
            if added:
                state.lost = True
                state.won = False
            else:
                state.lost = False
        elif emoji == "😡":
            state.incomplete = added
        elif emoji == "👍":
            if added:
                state.participants.add(payload.user_id)
            else:
                state.participants.discard(payload.user_id)
        else:
            # autres emojis ignorés
            return

        # Reconstruire l'embed et éditer
        new_embed = build_embed(state, embed_msg.guild)
        try:
            await embed_msg.edit(embed=new_embed)
        except Exception:
            pass


# =========================
#  setup (cog)
# =========================
async def setup(bot: commands.Bot):
    # Init DB (synchrone, mais très rapide)
    await asyncio.to_thread(_db_init)
    await bot.add_cog(PingCog(bot))
