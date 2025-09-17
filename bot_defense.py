# ==============================================
#  Bot Discord — Roulette 1v1 + Leaderboard hebdo
#  (Sans ChatGPT, sans slots) — prêt pour Render
#  - /roulette <mise> : duel 1v1 avec croupier & commission 5%
#  - /leaderboard : classement serveur (titre "Leaderboard")
#  - /profil : stats détaillées par joueur
#  - !sync (admin)
#  - Envoi auto du leaderboard chaque vendredi 18:00 (Europe/Paris)
# ==============================================

import os
import asyncio
import threading
import secrets
import random
from dataclasses import dataclass
from typing import Optional, Dict, List, Tuple
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands
from discord import app_commands

import aiosqlite
from flask import Flask

# ------------------ Flask keep-alive (Render Web Service) ------------------
app = Flask(__name__)

@app.get("/")
def home():
    return "Bot en ligne"

def run_flask():
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_flask, daemon=True).start()

# ------------------ ENV / CONFIG ------------------
TOKEN = os.getenv("DISCORD_TOKEN") or ""
GUILD_IDS = [int(x) for x in os.getenv("GUILD_IDS", "").split(",") if x.strip().isdigit()]
ROLE_CROUPIER_ID = int(os.getenv("ROLE_CROUPIER_ID", "0") or 0)
SPIN_GIF_URL = os.getenv("SPIN_GIF_URL", "")  # URL directe d'un GIF/image public
LEADERBOARD_CHANNEL_ID = int(os.getenv("LEADERBOARD_CHANNEL_ID", "0") or 0)
DB_PATH = os.getenv("DB_PATH", "casino.db")

# Roulette
ROULETTE_JOIN_TIMEOUT = 300   # 5 min pour qu'un joueur rejoigne
CROUPIER_TIMEOUT = 180        # 3 min pour valider
SPIN_COUNTDOWN = 3            # compte à rebours 3..1
CROUPIER_COMMISSION = 0.05    # 5%
RED_NUMBERS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
TZ = ZoneInfo("Europe/Paris")

# Phrases & déco
VICTORY_LINES = [
    "🎉 Jackpot de folie !",
    "🔥 Ça tourne à ton avantage !",
    "💫 Chance insolente !",
    "🏆 La maison s'incline !",
    "✨ Spin légendaire !",
]
EMOJI_RAIN = ["🎊","🎉","💥","✨","🎇","🎆","🍀","🤑","🔔","⭐","7️⃣"]

# ------------------ Intents & Bot ------------------
intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = True  # pour !sync si besoin
bot = commands.Bot(command_prefix="!", intents=intents)

# ------------------ DB (aiosqlite) ------------------
async def db_init():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA synchronous=NORMAL;")
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS lb_users(
              guild_id     INTEGER NOT NULL,
              user_id      INTEGER NOT NULL,
              total_bet    INTEGER NOT NULL DEFAULT 0,
              net          INTEGER NOT NULL DEFAULT 0,
              wins         INTEGER NOT NULL DEFAULT 0,
              losses       INTEGER NOT NULL DEFAULT 0,
              biggest_win  INTEGER NOT NULL DEFAULT 0,
              max_streak   INTEGER NOT NULL DEFAULT 0,
              PRIMARY KEY (guild_id, user_id)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS lb_tx(
              id         INTEGER PRIMARY KEY AUTOINCREMENT,
              guild_id   INTEGER NOT NULL,
              channel_id INTEGER NOT NULL,
              ts         INTEGER NOT NULL,
              game_id    TEXT,
              user_id    INTEGER NOT NULL,
              bet        INTEGER NOT NULL,
              net        INTEGER NOT NULL,  -- +mise si win, -mise si lose (commission exclue)
              won        INTEGER NOT NULL   -- 1 win, 0 lose
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS lb_commission(
              guild_id INTEGER PRIMARY KEY,
              amount   INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        await db.execute("CREATE INDEX IF NOT EXISTS idx_lbtx_g_ts ON lb_tx(guild_id, ts)")
        await db.commit()

# ---------- Helpers DB ----------
def fmt_kamas(n: int) -> str:
    try:
        return f"{int(n):,}".replace(",", " ")
    except Exception:
        return str(n)

async def lb_add_bet(guild_id: int, user_id: int, amount: int):
    amount = max(0, int(amount))
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO lb_users(guild_id, user_id, total_bet)
            VALUES(?,?,?)
            ON CONFLICT(guild_id,user_id)
            DO UPDATE SET total_bet = lb_users.total_bet + excluded.total_bet
            """,
            (guild_id, user_id, amount)
        )
        await db.commit()

async def lb_add_net(guild_id: int, user_id: int, delta: int, win: Optional[bool] = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO lb_users(guild_id, user_id, net)
            VALUES(?,?,?)
            ON CONFLICT(guild_id,user_id)
            DO UPDATE SET net = lb_users.net + excluded.net
            """,
            (guild_id, user_id, int(delta))
        )
        if win is True:
            await db.execute("UPDATE lb_users SET wins=wins+1 WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        elif win is False:
            await db.execute("UPDATE lb_users SET losses=losses+1 WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        await db.commit()

async def lb_update_biggest_and_streak(guild_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT net, won FROM lb_tx WHERE guild_id=? AND user_id=? ORDER BY ts ASC",
            (guild_id, user_id)
        )
        rows = await cur.fetchall()
        biggest = 0
        max_streak = 0
        cur_streak = 0
        for net, won in rows:
            if net > 0:
                biggest = max(biggest, net)
            if won:
                cur_streak += 1
                max_streak = max(max_streak, cur_streak)
            else:
                cur_streak = 0
        await db.execute(
            "UPDATE lb_users SET biggest_win=?, max_streak=? WHERE guild_id=? AND user_id=?",
            (biggest, max_streak, guild_id, user_id)
        )
        await db.commit()

async def lb_add_commission(guild_id: int, amount: int):
    amount = max(0, int(amount))
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO lb_commission(guild_id, amount)
            VALUES(?,?)
            ON CONFLICT(guild_id)
            DO UPDATE SET amount = lb_commission.amount + excluded.amount
            """,
            (guild_id, amount)
        )
        await db.commit()

async def lb_get_rows(guild_id: int) -> List[Tuple[int,int,int]]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id, total_bet, net FROM lb_users WHERE guild_id=? ORDER BY total_bet DESC LIMIT 20",
            (guild_id,)
        )
        return await cur.fetchall()

async def lb_weekly_rows(guild_id: int, ts_from: int, ts_to: int) -> List[Tuple[int,int,int]]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT user_id,
                   SUM(bet) AS total_bet,
                   SUM(net) AS net
            FROM lb_tx
            WHERE guild_id=? AND ts BETWEEN ? AND ?
            GROUP BY user_id
            ORDER BY total_bet DESC
            LIMIT 20
            """,
            (guild_id, ts_from, ts_to)
        )
        return await cur.fetchall()

async def lb_profile(guild_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT total_bet, net, wins, losses, biggest_win, max_streak FROM lb_users WHERE guild_id=? AND user_id=?",
            (guild_id, user_id)
        )
        row = await cur.fetchone()
        totals = row if row is not None else (0, 0, 0, 0, 0, 0)

        cur = await db.execute(
            """
            SELECT COALESCE(SUM(CASE WHEN net>0 THEN net ELSE 0 END),0),
                   COALESCE(SUM(CASE WHEN net<0 THEN -net ELSE 0 END),0)
            FROM lb_tx WHERE guild_id=? AND user_id=?
            """,
            (guild_id, user_id)
        )
        gp = await cur.fetchone()
        gains = gp[0] or 0
        losses = gp[1] or 0
        return totals, gains, losses

# ------------------ Sync & on_ready ------------------
@bot.event
async def on_ready():
    await db_init()
    try:
        if GUILD_IDS:
            for gid in GUILD_IDS:
                await bot.tree.sync(guild=discord.Object(id=gid))
        else:
            pass
    except Exception as e:
        print("Sync error:", e)
    print(f"Connecté en tant que {bot.user}")
    bot.loop.create_task(weekly_leaderboard_task())

@bot.command(name="sync")
@commands.has_permissions(administrator=True)
async def sync_cmd(ctx: commands.Context):
    synced = await ctx.bot.tree.sync(guild=ctx.guild)
    await ctx.reply(f"✅ Sync OK — {len(synced)} commandes pour ce serveur.")

# ------------------ Roulette core ------------------
@dataclass
class RouletteGame:
    channel_id: int
    starter_id: int
    stake: int
    duel_type: Optional[str] = None    # "couleur" | "parite" | "plage"
    starter_choice: Optional[str] = None
    joiner_id: Optional[int] = None
    state: str = "init"                # init -> choose_duel -> choose_side -> waiting_player -> wait_croupier -> spinning -> done
    validated: bool = False            # ✅ empêche double validation croupier

active_games: Dict[int, List[RouletteGame]] = {}

COLOR_GOLD = 0xF1C40F
COLOR_BLUE = 0x3498DB
COLOR_GREY = 0x95A5A6
COLOR_GREEN = 0x2ECC71
COLOR_RED = 0xE74C3C
COLOR_BLACK = 0x2C3E50

def r_color(n: int) -> str:
    if n == 0:
        return "vert"
    return "rouge" if n in RED_NUMBERS else "noir"

def r_parity(n: int) -> str:
    if n == 0:
        return "zero"
    return "pair" if (n % 2 == 0) else "impair"

def r_range(n: int) -> str:
    if n == 0:
        return "zero"
    return "1-18" if 1 <= n <= 18 else "19-36"

def e_start(game: RouletteGame) -> discord.Embed:
    desc = (
        f"👑 Créateur : <@{game.starter_id}>\n"
        f"💵 Mise : **{fmt_kamas(game.stake)}** kamas chacun\n\n"
        "**Choisis le type de duel :**\n"
        "🔴⚫ **Rouge/Noir** — pari couleur\n"
        "#️⃣ **Pair/Impair** — pari parité\n"
        "↕️ **1-18 / 19-36** — pari plage\n"
    )
    embed = discord.Embed(title="🎲 Roulette — Création de table", description=desc, color=COLOR_GOLD)
    embed.set_footer(text="Sélectionne un mode ci-dessous. ℹ️ pour l'aide.")
    return embed

def e_choose_side(game: RouletteGame) -> discord.Embed:
    a, b = ("🔴 Rouge", "⚫ Noir") if game.duel_type == "couleur" else ("#️⃣ Pair", "#️⃣ Impair") if game.duel_type == "parite" else ("↕️ 1-18", "↕️ 19-36")
    desc = (
        f"🎛️ Duel : **{game.duel_type}**\n"
        f"👉 Choisis ton camp : **{a}** ou **{b}**\n\n"
        "ℹ️ Pari even money (1:1), 5% de commission sur le pot final."
    )
    embed = discord.Embed(title="🎯 Choix du camp", description=desc, color=COLOR_BLUE)
    embed.set_footer(text="Ton choix déterminera le côté opposé pour l'adversaire.")
    return embed

def e_wait_player(game: RouletteGame, suffix: str = "") -> discord.Embed:
    desc = (
        f"👑 Créateur : <@{game.starter_id}>  •  💵 Mise **{fmt_kamas(game.stake)}** kamas\n"
        "➡️ Tape /roulette ou clique Rejoindre pour accepter le défi."
        + suffix
    )
    embed = discord.Embed(title="🕒 En attente d'un second joueur", description=desc, color=COLOR_GREY)
    embed.set_footer(text="Le lobby expirera automatiquement si personne ne rejoint.")
    return embed

def e_wait_croupier(game: RouletteGame) -> discord.Embed:
    desc = (
        f"👥 <@{game.starter_id}> vs <@{game.joiner_id}>\n"
        f"⚔️ Duel : **{game.duel_type}** — choix créateur **{game.starter_choice}**\n"
        f"💵 Mise : **{fmt_kamas(game.stake)}** kamas chacun\n\n"
        "Un croupier doit appuyer sur Valider les mises pour lancer la roulette."
    )
    embed = discord.Embed(title="📣 En attente du CROUPIER", description=desc, color=COLOR_RED)
    embed.set_footer(text="Seul le rôle CROUPIER peut valider.")
    return embed

# ---------- Views ----------
class DuelSelectView(discord.ui.View):
    def __init__(self, game: RouletteGame):
        super().__init__(timeout=180)
        self.game = game

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.user.id != self.game.starter_id:
            await inter.response.send_message("Seul le créateur choisit le type de duel.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🔴⚫ Rouge/Noir", style=discord.ButtonStyle.danger)
    async def b_color(self, inter: discord.Interaction, _):
        await self._set(inter, "couleur")

    @discord.ui.button(label="#️⃣ Pair/Impair", style=discord.ButtonStyle.primary)
    async def b_parity(self, inter: discord.Interaction, _):
        await self._set(inter, "parite")

    @discord.ui.button(label="↕️ 1-18 / 19-36", style=discord.ButtonStyle.secondary)
    async def b_range(self, inter: discord.Interaction, _):
        await self._set(inter, "plage")

    @discord.ui.button(label="ℹ️ Aide", style=discord.ButtonStyle.success)
    async def b_help(self, inter: discord.Interaction, _):
        help_txt = (
            "**Rouge/Noir** → cote 1:1\n"
            "**Pair/Impair** → cote 1:1\n"
            "**1-18 / 19-36** → cote 1:1\n"
            "Le zéro annule et rend les mises."
        )
        await inter.response.send_message(help_txt, ephemeral=True)

    async def _set(self, inter: discord.Interaction, kind: str):
        await inter.response.defer_update()
        self.game.duel_type = kind
        self.game.state = "choose_side"
        for c in self.children:
            c.disabled = True
        msg = await inter.original_response()
        await msg.edit(embed=e_choose_side(self.game), view=SideSelectView(self.game))

class SideSelectView(discord.ui.View):
    def __init__(self, game: RouletteGame):
        super().__init__(timeout=180)
        self.game = game
        a, b = self._labels()
        self.children[0].label = a
        self.children[1].label = b

    def _labels(self):
        if self.game.duel_type == "couleur":
            return ("🔴 Rouge", "⚫ Noir")
        if self.game.duel_type == "parite":
            return ("#️⃣ Pair", "#️⃣ Impair")
        return ("↙️ 1-18", "↗️ 19-36")

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.user.id != self.game.starter_id:
            await inter.response.send_message("Seul le créateur choisit son camp.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Option A", style=discord.ButtonStyle.success)
    async def b_a(self, inter: discord.Interaction, _):
        await self._pick(inter, 0)

    @discord.ui.button(label="Option B", style=discord.ButtonStyle.secondary)
    async def b_b(self, inter: discord.Interaction, _):
        await self._pick(inter, 1)

    async def on_timeout(self):
        ch_games = active_games.get(self.game.channel_id, [])
        if self.game in ch_games:
            ch_games.remove(self.game)

    async def _pick(self, inter: discord.Interaction, idx: int):
        await inter.response.defer_update()
        a, b = self._labels()
        label = a if idx == 0 else b
        norm = (
            label.replace("🔴 ", "").replace("⚫ ", "").replace("#️⃣ ", "")
                 .replace("↙️ ", "").replace("↗️ ", "").strip().lower()
        )
        self.game.starter_choice = norm
        self.game.state = "waiting_player"
        view = JoinView(self.game)
        msg = await inter.original_response()
        await msg.edit(embed=e_wait_player(self.game), view=view)

        # Animation "…" pendant l'attente (toutes les 2s)
        async def animate():
            for i in range(1, 60):
                await asyncio.sleep(2)
                if self.game.state != "waiting_player":
                    break
                dots = "." * ((i % 3) + 1)
                try:
                    await msg.edit(embed=e_wait_player(self.game, suffix=f"\n\nEn attente d'un second joueur{dots}"), view=view)
                except Exception:
                    break
        bot.loop.create_task(animate())

        # Timer d'annulation
        async def timeout_join():
            await asyncio.sleep(ROULETTE_JOIN_TIMEOUT)
            if self.game.state == "waiting_player" and self.game.joiner_id is None:
                await inter.channel.send(f"⏳ Temps écoulé, partie annulée (créée par <@{self.game.starter_id}>).")
                ch_games = active_games.get(self.game.channel_id, [])
                if self.game in ch_games:
                    ch_games.remove(self.game)
        bot.loop.create_task(timeout_join())

class JoinView(discord.ui.View):
    def __init__(self, game: RouletteGame):
        super().__init__(timeout=ROULETTE_JOIN_TIMEOUT)
        self.game = game

    @discord.ui.button(label="Rejoindre", style=discord.ButtonStyle.primary, emoji="🧍")
    async def b_join(self, inter: discord.Interaction, _):
        await inter.response.defer_update()
        if inter.user.id == self.game.starter_id:
            return
        if self.game.joiner_id is not None:
            return
        self.game.joiner_id = inter.user.id
        self.game.state = "wait_croupier"
        role_ping = f"<@&{ROLE_CROUPIER_ID}>" if ROLE_CROUPIER_ID else "CROUPIER"
        await inter.channel.send(f"{role_ping} — merci de valider les mises pour démarrer la roulette.")
        view = CroupierView(self.game)
        msg = await inter.original_response()
        await msg.edit(embed=e_wait_croupier(self.game), view=view)

class CroupierView(discord.ui.View):
    def __init__(self, game: RouletteGame):
        super().__init__(timeout=CROUPIER_TIMEOUT)
        self.game = game

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if ROLE_CROUPIER_ID:
            is_member = isinstance(inter.user, discord.Member)
            has_role = is_member and discord.utils.get(inter.user.roles, id=ROLE_CROUPIER_ID)
            if not has_role:
                await inter.response.send_message("Seul le rôle CROUPIER peut valider.", ephemeral=True)
                return False
        return True

    @discord.ui.button(label="Valider les mises", style=discord.ButtonStyle.success, emoji="✅")
    async def b_validate(self, inter: discord.Interaction, _):
        # ✅ Empêche toute double validation / spam
        if self.game.validated or self.game.state != "wait_croupier":
            await inter.response.send_message("Cette table est déjà validée ou terminée.", ephemeral=True)
            return

        # Verrouille l'état et désactive les boutons avant de spinner
        self.game.validated = True
        self.game.state = "spinning"
        for c in self.children:
            c.disabled = True
        try:
            await inter.response.defer_update()
            msg = await inter.original_response()
            await msg.edit(view=self)
        except Exception:
            pass

        await self._spin(inter)  # une seule fois

    @discord.ui.button(label="+60s", style=discord.ButtonStyle.secondary, emoji="⏱️")
    async def b_extend(self, inter: discord.Interaction, _):
        if self.game.validated or self.game.state != "wait_croupier":
            await inter.response.send_message("Cette action n'est plus possible.", ephemeral=True)
            return
        await inter.response.send_message("⏱️ Timer croupier étendu de 60s.", ephemeral=True)
        self.timeout = (self.timeout or 0) + 60

    @discord.ui.button(label="Annuler la table", style=discord.ButtonStyle.danger, emoji="🛑")
    async def b_cancel(self, inter: discord.Interaction, _):
        if self.game.validated or self.game.state != "wait_croupier":
            await inter.response.send_message("Cette table est déjà validée ou terminée.", ephemeral=True)
            return
        await inter.response.defer_update()
        ch_games = active_games.get(self.game.channel_id, [])
        if self.game in ch_games:
            ch_games.remove(self.game)
        msg = await inter.original_response()
        await msg.edit(content="🛑 Table annulée par le croupier.", embed=None, view=None)

    async def _spin(self, inter: discord.Interaction):
        # On répond dans les 3s via un followup
        base = (
            f"👥 <@{self.game.starter_id}> vs <@{self.game.joiner_id}>\n"
            f"⚔️ Duel : **{self.game.duel_type}** — choix créateur **{self.game.starter_choice}**\n"
            f"💵 Mise : **{fmt_kamas(self.game.stake)}** kamas chacun\n"
        )
        embed = discord.Embed(
            title="🎡 Roulette — c'est parti !",
            description=base + f"⌛ La roue tourne… **{SPIN_COUNTDOWN}**",
            color=COLOR_GOLD
        )
        if SPIN_GIF_URL:
            embed.set_image(url=SPIN_GIF_URL)

        await inter.followup.send(embed=embed)
        sent = await inter.original_response()

        # Compte à rebours
        for t in range(SPIN_COUNTDOWN - 1, 0, -1):
            await asyncio.sleep(1)
            embed.description = base + f"⌛ La roue tourne… **{t}**"
            try:
                await sent.edit(embed=embed)
            except Exception:
                break
        await asyncio.sleep(1)

        # Tirage
        n = secrets.randbelow(37)
        col = r_color(n)
        par = r_parity(n)
        rng = r_range(n)

        def wins(choice: str) -> bool:
            c = (choice or "").lower().strip()
            if self.game.duel_type == "couleur":
                return c in {"rouge", "noir"} and (col == c)
            if self.game.duel_type == "parite":
                return c in {"pair", "impair"} and (par == c)
            if self.game.duel_type == "plage":
                return c in {"1-18", "19-36"} and (rng == c)
            return False

        # Zéro = push
        if n == 0:
            title = "🏁 Résultat : 0 🟢"
            desc = base + "\n**Zéro** — égalité, mises rendues."
            res = discord.Embed(title=title, description=desc, color=COLOR_GREEN)
            await sent.edit(embed=res, view=None)
            self.game.state = "done"
            ch_games = active_games.get(self.game.channel_id, [])
            if self.game in ch_games:
                ch_games.remove(self.game)
            return

        creator_wins = wins(self.game.starter_choice or "")
        winner_id = self.game.starter_id if creator_wins else self.game.joiner_id
        loser_id  = self.game.joiner_id if creator_wins else self.game.starter_id

        # Pot & commission
        pot = self.game.stake * 2
        commission = int(round(pot * CROUPIER_COMMISSION))
        payout = pot - commission  # montant annoncé côté embed
        # Historique net (hors commission) : +stake pour gagnant, -stake pour perdant
        now_ts = int(datetime.now(TZ).timestamp())
        game_id = f"{inter.channel_id}-{now_ts}-{n}"

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                INSERT INTO lb_tx(guild_id, channel_id, ts, game_id, user_id, bet, net, won)
                VALUES(?,?,?,?,?,?,?,?)
                """,
                (inter.guild.id, inter.channel_id, now_ts, game_id, winner_id, self.game.stake, +self.game.stake, 1)
            )
            await db.execute(
                """
                INSERT INTO lb_tx(guild_id, channel_id, ts, game_id, user_id, bet, net, won)
                VALUES(?,?,?,?,?,?,?,?)
                """,
                (inter.guild.id, inter.channel_id, now_ts, game_id, loser_id,  self.game.stake, -self.game.stake, 0)
            )
            await db.commit()

        await lb_add_bet(inter.guild.id, self.game.starter_id, self.game.stake)
        await lb_add_bet(inter.guild.id, self.game.joiner_id, self.game.stake)
        await lb_add_net(inter.guild.id, winner_id, +self.game.stake, win=True)
        await lb_add_net(inter.guild.id, loser_id,  -self.game.stake, win=False)
        await lb_update_biggest_and_streak(inter.guild.id, winner_id)
        await lb_update_biggest_and_streak(inter.guild.id, loser_id)
        await lb_add_commission(inter.guild.id, commission)

        color_emoji = "🔴" if col == "rouge" else ("⚫" if col == "noir" else "🟢")
        title = f"🏁 Résultat : {n} {color_emoji}"
        tagline = random.choice(VICTORY_LINES)
        desc = (
            base +
            f"{tagline}\n\n"
            f"💵 Pot : {fmt_kamas(pot)}k — 🧮 Commission croupier {int(CROUPIER_COMMISSION*100)}% = {fmt_kamas(commission)}k\n"
            f"🏆 Gagnant : <@{winner_id}> **+{fmt_kamas(payout)}k**  |  😿 Perdant : <@{loser_id}> **-{fmt_kamas(self.game.stake)}k**"
        )
        col_for_embed = 0x2ECC71 if col == "vert" else (0xE74C3C if col == "rouge" else 0x2C3E50)
        res = discord.Embed(title=title, description=desc, color=col_for_embed)
        await sent.edit(embed=res, view=None)

        # Pluie d'emojis (light)
        for _ in range(2):
            await asyncio.sleep(0.35)
            line = "".join(random.choice(EMOJI_RAIN) for _ in range(16))
            try:
                await inter.channel.send(line)
            except Exception:
                break

        # ✅ Fin de partie
        self.game.state = "done"
        ch_games = active_games.get(self.game.channel_id, [])
        if self.game in ch_games:
            ch_games.remove(self.game)

# ------------------ Slash commands ------------------
@bot.tree.command(name="roulette", description="Créer une roulette 1v1 (croupier requis)")
@app_commands.describe(mise="Mise unitaire (kamas) pour chaque joueur")
async def roulette_cmd(inter: discord.Interaction, mise: int):
    if mise <= 0:
        await inter.response.send_message("La mise doit être un entier positif.", ephemeral=True)
        return
    await inter.response.defer(thinking=True)
    game = RouletteGame(channel_id=inter.channel_id, starter_id=inter.user.id, stake=mise)
    active_games.setdefault(inter.channel_id, []).append(game)
    await inter.followup.send(embed=e_start(game), view=DuelSelectView(game))

@bot.tree.command(name="leaderboard", description="Classement du serveur (mises & net)")
async def leaderboard_cmd(inter: discord.Interaction):
    await inter.response.defer(thinking=True)
    rows = await lb_get_rows(inter.guild.id)
    if not rows:
        await inter.followup.send("Aucune donnée pour l'instant.")
        return
    lines = []
    for i, (uid, total, net) in enumerate(rows, start=1):
        lines.append(f"**{i}.** <@{uid}> — misé `{fmt_kamas(total)}k` • net `{fmt_kamas(net)}k`")
    embed = discord.Embed(title="🏆 Leaderboard", description="\n".join(lines), color=0x9B59B6)
    await inter.followup.send(embed=embed)

@bot.tree.command(name="profil", description="Voir ton profil casino")
@app_commands.describe(membre="(optionnel) Voir le profil de ce membre")
async def profil_cmd(inter: discord.Interaction, membre: Optional[discord.Member] = None):
    await inter.response.defer(thinking=True)
    user = membre or inter.user
    totals, gains, losses = await lb_profile(inter.guild.id, user.id)
    total_bet, net, wins, losses_count, biggest_win, max_streak = totals
    desc = (
        f"👤 Profil de {user.mention}\n"
        f"💰 Total misé : `{fmt_kamas(total_bet)}k`\n"
        f"🟢 Total gains : `{fmt_kamas(gains)}k`\n"
        f"🔴 Total pertes : `{fmt_kamas(losses)}k`\n"
        f"🏆 Victoires : `{wins}`   •   😿 Défaites : `{losses_count}`\n"
        f"💥 Plus gros gain : `{fmt_kamas(biggest_win)}k`\n"
        f"🔥 Série max : `{max_streak}`\n"
        f"📊 Net : `{fmt_kamas(net)}k`"
    )
    embed = discord.Embed(title="📇 Profil", description=desc, color=0x8E44AD)
    await inter.followup.send(embed=embed)

# ------------------ Hebdo autosend ------------------
TZ_PARIS = ZoneInfo("Europe/Paris")

def next_friday_18(now: datetime) -> datetime:
    days_ahead = (4 - now.weekday()) % 7  # lundi=0 … vendredi=4
    target = (now + timedelta(days=days_ahead)).replace(hour=18, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=7)
    return target

async def weekly_leaderboard_task():
    await bot.wait_until_ready()
    await db_init()
    while not bot.is_closed():
        now = datetime.now(TZ_PARIS)
        target = next_friday_18(now)
        await asyncio.sleep(max(1, int((target - now).total_seconds())))
        try:
            end = target
            start = (target - timedelta(days=7)).replace(hour=18, minute=1, second=0, microsecond=0)
            ts_from = int(start.timestamp())
            ts_to = int(end.timestamp())
            for guild in bot.guilds:
                # Choix du salon
                channel = None
                if LEADERBOARD_CHANNEL_ID:
                    channel = guild.get_channel(LEADERBOARD_CHANNEL_ID) or discord.utils.get(guild.text_channels, id=LEADERBOARD_CHANNEL_ID)
                if channel is None:
                    channel = next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)
                if channel is None:
                    continue

                rows = await lb_weekly_rows(guild.id, ts_from, ts_to)
                if not rows:
                    await channel.send("(Hebdo) Aucun pari enregistré cette semaine.")
                    continue
                lines = []
                for i, (uid, total, net) in enumerate(rows, start=1):
                    lines.append(f"**{i}.** <@{uid}> — misé `{fmt_kamas(total)}k` • net `{fmt_kamas(net)}k`")
                period = f"du {start.strftime('%d/%m %H:%M')} au {end.strftime('%d/%m %H:%M')}"
                embed = discord.Embed(title="🏆 Leaderboard (hebdo)", description="\n".join(lines), color=0x9B59B6)
                embed.set_footer(text=period)
                await channel.send(embed=embed)
        except Exception as e:
            print("Weekly LB error:", e)
        await asyncio.sleep(60)

# ------------------ Main ------------------
if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN manquant")
    bot.run(TOKEN)
