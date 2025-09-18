# cogs/ping.py
# Panneau de ping (Def / Def2) + suivi des réactions + leaderboard auto des "pingeurs"
# + Leaderboard DEFENSES (Top 20 cumul + cumul global + 7j glissants + répartition horaire)
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
PING_LEADERBOARD_CHANNEL_ID = int(os.getenv("PING_LEADERBOARD_CHANNEL_ID", "0"))  # salon du/ des leaderboard(s)
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

    # Liste des défenseurs (👍) - pour l'alerte en cours
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
    """Retourne le rôle Def/Def2 soit par ID (ENV), soit par nom exact."""
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
        # Pingeurs
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ping_stats(
                guild_id INTEGER NOT NULL,
                user_id  INTEGER NOT NULL,
                count    INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            );
        """)
        # Meta (message IDs, etc.)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS meta(
                guild_id INTEGER NOT NULL,
                key      TEXT NOT NULL,
                value    TEXT,
                PRIMARY KEY (guild_id, key)
            );
        """)
        # Défenses - événements (une par alerte)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS defense_events(
                guild_id         INTEGER NOT NULL,
                base_message_id  INTEGER NOT NULL PRIMARY KEY,
                embed_message_id INTEGER NOT NULL,
                created_ts       INTEGER NOT NULL,
                side             TEXT NOT NULL,                  -- 'Def' | 'Def2'
                result           TEXT NOT NULL DEFAULT 'unknown',-- 'win'|'loss'|'unknown'
                incomplete       INTEGER NOT NULL DEFAULT 0,     -- 0/1
                time_bucket      TEXT NOT NULL                   -- 'matin'|'journee'|'soir'|'nuit'
            );
        """)
        # Défenses - participants (👍)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS defense_participants(
                guild_id        INTEGER NOT NULL,
                base_message_id INTEGER NOT NULL,
                user_id         INTEGER NOT NULL,
                ts_joined       INTEGER NOT NULL,
                PRIMARY KEY (guild_id, base_message_id, user_id)
            );
        """)
    conn.close()


# --- Ping leaderboard helpers -------------------------------------------------
def _db_inc_ping(guild_id: int, user_id: int):
    conn = _db_connect()
    with conn:
        conn.execute("""
            INSERT INTO ping_stats(guild_id, user_id, count)
            VALUES(?,?,1)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET count = count + 1;
        """, (guild_id, user_id))
    conn.close()


def _db_get_top_pingers(guild_id: int, limit: int = 15) -> List[tuple]:
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


# --- Defense leaderboard storage & queries ------------------------------------
def _bucket_from_ts(ts_utc: int) -> str:
    dt = datetime.datetime.fromtimestamp(ts_utc, tz=ZoneInfo("UTC")).astimezone(TZ)
    h = dt.hour
    if 6 <= h < 10:
        return "matin"
    if 10 <= h < 18:
        return "journee"
    if 18 <= h < 24:
        return "soir"
    return "nuit"


def _db_insert_defense_event(guild_id: int, base_message_id: int, embed_message_id: int, created_ts: int, side: str):
    conn = _db_connect()
    with conn:
        conn.execute("""
            INSERT OR IGNORE INTO defense_events(guild_id, base_message_id, embed_message_id, created_ts, side, result, incomplete, time_bucket)
            VALUES(?,?,?,?,?,'unknown',0,?);
        """, (guild_id, base_message_id, embed_message_id, created_ts, side, _bucket_from_ts(created_ts)))
    conn.close()


def _db_set_result(guild_id: int, base_message_id: int, result: str):
    conn = _db_connect()
    with conn:
        conn.execute("""
            UPDATE defense_events SET result = ? WHERE guild_id = ? AND base_message_id = ?;
        """, (result, guild_id, base_message_id))
    conn.close()


def _db_set_incomplete(guild_id: int, base_message_id: int, incomplete: int):
    conn = _db_connect()
    with conn:
        conn.execute("""
            UPDATE defense_events SET incomplete = ? WHERE guild_id = ? AND base_message_id = ?;
        """, (incomplete, guild_id, base_message_id))
    conn.close()


def _db_add_participant(guild_id: int, base_message_id: int, user_id: int, ts: int):
    conn = _db_connect()
    with conn:
        conn.execute("""
            INSERT OR IGNORE INTO defense_participants(guild_id, base_message_id, user_id, ts_joined)
            VALUES(?,?,?,?);
        """, (guild_id, base_message_id, user_id, ts))
    conn.close()


def _db_remove_participant(guild_id: int, base_message_id: int, user_id: int):
    conn = _db_connect()
    with conn:
        conn.execute("""
            DELETE FROM defense_participants WHERE guild_id = ? AND base_message_id = ? AND user_id = ?;
        """, (guild_id, base_message_id, user_id))
    conn.close()


def _db_get_defense_cumul(guild_id: int) -> Tuple[int, int, int, int]:
    """return total, wins, incompletes, losses (all-time)"""
    conn = _db_connect()
    cur = conn.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN result='win'  THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN incomplete=1 THEN 1 ELSE 0 END) AS incompletes,
            SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) AS losses
        FROM defense_events
        WHERE guild_id = ?;
    """, (guild_id,))
    row = cur.fetchone()
    conn.close()
    total, wins, inc, losses = row or (0, 0, 0, 0)
    return int(total or 0), int(wins or 0), int(inc or 0), int(losses or 0)


def _db_get_defense_7d(guild_id: int, since_ts: int) -> Tuple[int, int, int, int]:
    """return total7, wins7, incompletes7, losses7 (7d sliding)"""
    conn = _db_connect()
    cur = conn.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN result='win'  THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN incomplete=1 THEN 1 ELSE 0 END) AS incompletes,
            SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) AS losses
        FROM defense_events
        WHERE guild_id = ? AND created_ts >= ?;
    """, (guild_id, since_ts))
    row = cur.fetchone()
    conn.close()
    total, wins, inc, losses = row or (0, 0, 0, 0)
    return int(total or 0), int(wins or 0), int(inc or 0), int(losses or 0)


def _db_get_top_defenders_cumul(guild_id: int, limit: int = 20) -> List[tuple]:
    """Top participants (all-time) by number of defenses participated (👍)."""
    conn = _db_connect()
    cur = conn.execute("""
        SELECT dp.user_id, COUNT(*) AS cnt
        FROM defense_participants dp
        JOIN defense_events de ON de.guild_id = dp.guild_id AND de.base_message_id = dp.base_message_id
        WHERE dp.guild_id = ?
        GROUP BY dp.user_id
        ORDER BY cnt DESC, dp.user_id ASC
        LIMIT ?;
    """, (guild_id, limit))
    rows = cur.fetchall()
    conn.close()
    return rows


def _db_get_bucket_7d(guild_id: int, since_ts: int) -> Dict[str, int]:
    conn = _db_connect()
    cur = conn.execute("""
        SELECT time_bucket, COUNT(*) FROM defense_events
        WHERE guild_id = ? AND created_ts >= ?
        GROUP BY time_bucket;
    """, (guild_id, since_ts))
    rows = cur.fetchall()
    conn.close()
    d = { "matin": 0, "journee": 0, "soir": 0, "nuit": 0 }
    for tb, c in rows:
        if tb in d:
            d[tb] = int(c or 0)
    return d


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

        # Mémoriser l'état
        state.embed_message_id = embed_msg.id
        alert_states[base_msg.id] = state

        # Persister l'événement défense
        now_ts = int(datetime.datetime.now(tz=datetime.timezone.utc).timestamp())
        await asyncio.to_thread(_db_insert_defense_event, guild.id, base_msg.id, embed_msg.id, now_ts, side)

        # Incrémenter le compteur de pings (leaderboard pingeurs)
        await asyncio.to_thread(_db_inc_ping, guild.id, interaction.user.id)

        # Rafraîchir/afficher les leaderboard auto (pingeurs + défenses)
        await refresh_ping_leaderboard(guild)
        await refresh_defense_leaderboard(guild)


# =========================
#  Leaderboard auto – PINGEURS
# =========================
def _build_lb_pingers_embed(guild: discord.Guild, rows: List[tuple]) -> discord.Embed:
    e = discord.Embed(
        title="🏁 Leaderboard Pingeurs",
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
    text = "\n".join(lines[:25])
    e.add_field(name="Classement", value=text or "—", inline=False)
    e.set_footer(text="Actualisé automatiquement")
    return e


async def refresh_ping_leaderboard(guild: discord.Guild):
    if PING_LEADERBOARD_CHANNEL_ID == 0:
        return
    ch = guild.get_channel(PING_LEADERBOARD_CHANNEL_ID)
    if not isinstance(ch, (discord.TextChannel, discord.Thread)):
        return

    rows = await asyncio.to_thread(_db_get_top_pingers, guild.id, 15)
    embed = _build_lb_pingers_embed(guild, rows)

    msg_id_str = await asyncio.to_thread(_db_get_meta, guild.id, "ping_lb_message_id")
    msg_obj: Optional[discord.Message] = None
    if msg_id_str:
        try:
            msg_obj = await ch.fetch_message(int(msg_id_str))
        except discord.NotFound:
            msg_obj = None

    if msg_obj is None:
        sent = await ch.send(embed=embed)
        await asyncio.to_thread(_db_set_meta, guild.id, "ping_lb_message_id", str(sent.id))
    else:
        try:
            await msg_obj.edit(embed=embed)
        except discord.NotFound:
            sent = await ch.send(embed=embed)
            await asyncio.to_thread(_db_set_meta, guild.id, "ping_lb_message_id", str(sent.id))


# =========================
#  Leaderboard auto – DEFENSES
# =========================
def _build_lb_defenses_embed(
    guild: discord.Guild,
    top_cumul_rows: List[tuple],
    cumul: Tuple[int, int, int, int],
    last7: Tuple[int, int, int, int],
    buckets7: Dict[str, int],
) -> discord.Embed:
    total, wins, incs, losses = cumul
    total7, wins7, incs7, losses7 = last7

    e = discord.Embed(
        title="🛡️ Leaderboard Défenses",
        description="Statistiques en temps réel — mises à jour automatiques",
        color=ORANGE,
        timestamp=datetime.datetime.now(tz=TZ)
    )

    # Section 1 — Top Défenseurs (cumul) — Top 20
    if top_cumul_rows:
        lines = []
        for i, (uid, cnt) in enumerate(top_cumul_rows[:20], start=1):
            member = guild.get_member(uid)
            name = member.display_name if member else f"<@{uid}>"
            lines.append(f"**{i}.** {name} — {cnt} défense{'s' if cnt>1 else ''}")
        txt = "\n".join(lines)
    else:
        txt = "—"
    e.add_field(name="🧙 Top Défenseurs (cumul)", value=txt, inline=False)

    # Section 2 — Cumul (toutes périodes)
    e.add_field(
        name="📊 Cumul (toutes périodes)",
        value=(
            f"**Défenses totales** : **{total}**\n"
            f"**Victoires** : **{wins}** • **Incomplètes** : **{incs}** • **Défaites** : **{losses}**"
        ),
        inline=False
    )

    # Section 3 — 7 jours glissants
    if wins7 + losses7 > 0:
        win_rate = wins7 * 100.0 / (wins7 + losses7)
        loss_rate = losses7 * 100.0 / (wins7 + losses7)
        rates_line = f"**Taux de victoire (7j)** : **{win_rate:.1f}%** • **Taux de défaite (7j)** : **{loss_rate:.1f}%**"
    else:
        rates_line = "**Taux de victoire (7j)** : **—** • **Taux de défaite (7j)** : **—**"

    e.add_field(
        name="🗓️ 7 derniers jours (glissants)",
        value=(
            f"**Défenses totales (7j)** : **{total7}**\n"
            f"**Victoires (7j)** : **{wins7}** • **Incomplètes (7j)** : **{incs7}** • **Défaites (7j)** : **{losses7}**\n"
            f"{rates_line}"
        ),
        inline=False
    )

    # Section 4 — Répartition horaire (7j)
    b_matin   = int(buckets7.get("matin", 0))
    b_journee = int(buckets7.get("journee", 0))
    b_soir    = int(buckets7.get("soir", 0))
    b_nuit    = int(buckets7.get("nuit", 0))
    denom = max(total7, 1)  # éviter div/0 ; si total7=0 → 0% partout
    e.add_field(
        name="🕒 Répartition horaire (7j)",
        value=(
            f"**Matin (06–10)** : **{b_matin * 100 // denom}%**\n"
            f"**Journée (10–18)** : **{b_journee * 100 // denom}%**\n"
            f"**Soir (18–00)** : **{b_soir * 100 // denom}%**\n"
            f"**Nuit (00–06)** : **{b_nuit * 100 // denom}%**"
        ),
        inline=False
    )

    e.set_footer(text="Actualisé automatiquement")
    return e


async def refresh_defense_leaderboard(guild: discord.Guild):
    if PING_LEADERBOARD_CHANNEL_ID == 0:
        return
    ch = guild.get_channel(PING_LEADERBOARD_CHANNEL_ID)
    if not isinstance(ch, (discord.TextChannel, discord.Thread)):
        return

    now_ts = int(datetime.datetime.now(tz=datetime.timezone.utc).timestamp())
    since7 = now_ts - 7 * 24 * 3600

    top_cumul_rows = await asyncio.to_thread(_db_get_top_defenders_cumul, guild.id, 20)
    cumul = await asyncio.to_thread(_db_get_defense_cumul, guild.id)
    last7 = await asyncio.to_thread(_db_get_defense_7d, guild.id, since7)
    buckets7 = await asyncio.to_thread(_db_get_bucket_7d, guild.id, since7)
    embed = _build_lb_defenses_embed(guild, top_cumul_rows, cumul, last7, buckets7)

    msg_id_str = await asyncio.to_thread(_db_get_meta, guild.id, "defense_lb_message_id")
    msg_obj: Optional[discord.Message] = None
    if msg_id_str:
        try:
            msg_obj = await ch.fetch_message(int(msg_id_str))
        except discord.NotFound:
            msg_obj = None

    if msg_obj is None:
        sent = await ch.send(embed=embed)
        await asyncio.to_thread(_db_set_meta, guild.id, "defense_lb_message_id", str(sent.id))
    else:
        try:
            await msg_obj.edit(embed=embed)
        except discord.NotFound:
            sent = await ch.send(embed=embed)
            await asyncio.to_thread(_db_set_meta, guild.id, "defense_lb_message_id", str(sent.id))


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
        base_id_for_db = payload.message_id
        if state is None:
            for st in alert_states.values():
                if st.embed_message_id == payload.message_id:
                    state = st
                    base_id_for_db = st.base_message_id
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
                await asyncio.to_thread(_db_set_result, state.guild_id, base_id_for_db, "win")
            else:
                state.won = False
                # si on retire 🏆 et ❌ pas présent, on remet 'unknown'
                await asyncio.to_thread(_db_set_result, state.guild_id, base_id_for_db, "unknown" if not state.lost else "loss")
        elif emoji == "❌":
            if added:
                state.lost = True
                state.won = False
                await asyncio.to_thread(_db_set_result, state.guild_id, base_id_for_db, "loss")
            else:
                state.lost = False
                await asyncio.to_thread(_db_set_result, state.guild_id, base_id_for_db, "unknown" if not state.won else "win")
        elif emoji == "😡":
            state.incomplete = added
            await asyncio.to_thread(_db_set_incomplete, state.guild_id, base_id_for_db, 1 if added else 0)
        elif emoji == "👍":
            if added:
                state.participants.add(payload.user_id)
                now_ts = int(datetime.datetime.now(tz=datetime.timezone.utc).timestamp())
                await asyncio.to_thread(_db_add_participant, state.guild_id, base_id_for_db, payload.user_id, now_ts)
            else:
                state.participants.discard(payload.user_id)
                await asyncio.to_thread(_db_remove_participant, state.guild_id, base_id_for_db, payload.user_id)
        else:
            # autres emojis ignorés
            return

        # Reconstruire l'embed et éditer
        new_embed = build_embed(state, embed_msg.guild)
        try:
            await embed_msg.edit(embed=new_embed)
        except Exception:
            pass

        # Rafraîchir leaderboard DEFENSES à chaque changement
        if embed_msg.guild:
            await refresh_defense_leaderboard(embed_msg.guild)


# =========================
#  setup (cog)
# =========================
async def setup(bot: commands.Bot):
    # Init DB (synchrone, mais très rapide)
    await asyncio.to_thread(_db_init)
    await bot.add_cog(PingCog(bot))
    # Vue persistante pour les boutons
    bot.add_view(PingButtonsView())
