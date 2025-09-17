# ==============================================
#  Bot Discord — Roulette 1v1 + Leaderboard
#  (Sans ChatGPT, Sans Slots) — prêt pour Render
#  - Web server Flask léger pour Web Service Render
#  - /roulette <mise> : duel 1v1 avec croupier & commission 5%
#  - /leaderboard : classement serveur (total misé, net, W/L)
#  - !sync (admin) : maj instantanée des slash commands sur le serveur
# ==============================================

import os
import asyncio
import threading
import secrets
from dataclasses import dataclass
from typing import Optional, Dict, List

import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

# ------------------ Flask keep-alive (Render Web Service) ------------------
from flask import Flask
app = Flask(__name__)

@app.get("/")
def home():
    return "Bot en ligne"

def run_flask():
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_flask, daemon=True).start()

# ------------------ ENV / CONFIG ------------------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN") or ""
GUILD_IDS = [int(x) for x in os.getenv("GUILD_IDS", "").split(",") if x.strip().isdigit()]
ROLE_CROUPIER_ID = int(os.getenv("ROLE_CROUPIER_ID", "0") or 0)
SPIN_GIF_URL = os.getenv("SPIN_GIF_URL", "")

# Roulette
ROULETTE_JOIN_TIMEOUT = 300   # 5 min pour qu'un joueur rejoigne
CROUPIER_TIMEOUT = 180        # 3 min pour valider
SPIN_COUNTDOWN = 5            # compte à rebours 5..1
CROUPIER_COMMISSION = 0.05    # 5%
RED_NUMBERS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}

# ------------------ Intents & Bot ------------------
intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = True  # utile pour !sync
bot = commands.Bot(command_prefix="!", intents=intents)

# ------------------ DB (aiosqlite) ------------------
import aiosqlite
DB_PATH = os.getenv("DB_PATH", "casino.db")

async def db_init():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS lb_users(
              guild_id  INTEGER NOT NULL,
              user_id   INTEGER NOT NULL,
              total_bet INTEGER NOT NULL DEFAULT 0,
              net       INTEGER NOT NULL DEFAULT 0,
              wins      INTEGER NOT NULL DEFAULT 0,
              losses    INTEGER NOT NULL DEFAULT 0,
              PRIMARY KEY (guild_id, user_id)
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
        await db.commit()

def fmt_kamas(n: int) -> str:
    try:
        return f"{int(n):,}".replace(",", " ")
    except Exception:
        return str(n)

async def lb_add_bet(guild_id: int, user_id: int, amount: int):
    amount = max(0, int(amount))
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO lb_users(guild_id, user_id, total_bet) VALUES(?,?,?)\n             ON CONFLICT(guild_id,user_id) DO UPDATE SET total_bet=lb_users.total_bet+excluded.total_bet",
            (guild_id, user_id, amount)
        )
        await db.commit()

async def lb_add_net(guild_id: int, user_id: int, delta: int, win: Optional[bool] = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO lb_users(guild_id, user_id, net) VALUES(?,?,?)\n             ON CONFLICT(guild_id,user_id) DO UPDATE SET net=lb_users.net+excluded.net",
            (guild_id, user_id, int(delta))
        )
        if win is True:
            await db.execute("UPDATE lb_users SET wins=wins+1 WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        elif win is False:
            await db.execute("UPDATE lb_users SET losses=losses+1 WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        await db.commit()

async def lb_add_commission(guild_id: int, amount: int):
    amount = max(0, int(amount))
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO lb_commission(guild_id, amount) VALUES(?,?)\n             ON CONFLICT(guild_id) DO UPDATE SET amount=lb_commission.amount+excluded.amount",
            (guild_id, amount)
        )
        await db.commit()

async def lb_get_rows(guild_id: int) -> List[tuple[int,int,int,int,int]]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id, total_bet, net, wins, losses FROM lb_users WHERE guild_id=? ORDER BY total_bet DESC LIMIT 20",
            (guild_id,)
        )
        rows = await cur.fetchall()
    return rows

# ------------------ Sync rapide ------------------
@bot.event
async def on_ready():
    await db_init()
    try:
        if GUILD_IDS:
            for gid in GUILD_IDS:
                await bot.tree.sync(guild=discord.Object(id=gid))
    except Exception as e:
        print("Sync error:", e)
    print(f"Connecté en tant que {bot.user}")

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
    state: str = "init"               # init -> choose_duel -> choose_side -> waiting_player -> wait_croupier -> spinning -> done

active_games: Dict[int, List[RouletteGame]] = {}

def add_game(g: RouletteGame):
    active_games.setdefault(g.channel_id, []).append(g)

def remove_game(g: RouletteGame):
    L = active_games.get(g.channel_id, [])
    if g in L:
        L.remove(g)
    if not L:
        active_games.pop(g.channel_id, None)

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

# ---------- Embeds ----------

def e_start(game: RouletteGame) -> discord.Embed:
    desc = (
        f"Créateur : <@{game.starter_id}>\n"
        f"💵 Mise : **{fmt_kamas(game.stake)}** kamas chacun\n\n"
        "Choisis le **type de duel** :"
    )
    return discord.Embed(title="🎲 Roulette — création", description=desc, color=0xF1C40F)

def e_choose_side(game: RouletteGame) -> discord.Embed:
    a, b = ("Rouge", "Noir") if game.duel_type == "couleur" else ("Pair", "Impair") if game.duel_type == "parite" else ("1-18", "19-36")
    desc = (
        f"Duel : **{game.duel_type}**\n"
        f"Choisis ton camp : **{a}** ou **{b}**"
    )
    return discord.Embed(title="🎯 Choix du camp", description=desc, color=0x3498DB)

def e_wait_player(game: RouletteGame, suffix: str = "") -> discord.Embed:
    desc = (
        f"Créateur : <@{game.starter_id}>  •  Mise **{fmt_kamas(game.stake)}** kamas\n"
        "➡️ **Clique Rejoindre** pour accepter le défi."
        + suffix
    )
    return discord.Embed(title="🕒 En attente d'un second joueur", description=desc, color=0x95A5A6)

def e_wait_croupier(game: RouletteGame) -> discord.Embed:
    desc = (
        f"👥 <@{game.starter_id}> vs <@{game.joiner_id}>\n"
        f"⚔️ Duel : **{game.duel_type}** — choix créateur **{game.starter_choice}**\n"
        f"💵 Mise : **{fmt_kamas(game.stake)}** kamas chacun\n\n"
        "Un croupier doit appuyer sur **Valider les mises** pour lancer la roulette."
    )
    return discord.Embed(title="📣 En attente du CROUPIER", description=desc, color=0xE67E22)

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

    async def _set(self, inter: discord.Interaction, kind: str):
        self.game.duel_type = kind
        self.game.state = "choose_side"
        for c in self.children:
            c.disabled = True
        try:
            await inter.response.edit_message(embed=e_choose_side(self.game), view=SideSelectView(self.game))
        except discord.InteractionResponded:
            msg = await inter.original_response()
            await msg.edit(embed=e_choose_side(self.game), view=SideSelectView(self.game))

class SideSelectView(discord.ui.View):
    def __init__(self, game: RouletteGame):
        super().__init__(timeout=180)
        self.game = game

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.user.id != self.game.starter_id:
            await inter.response.send_message("Seul le créateur choisit son camp.", ephemeral=True)
            return False
        return True

    def _labels(self):
        if self.game.duel_type == "couleur":
            return ("🔴 Rouge", "⚫ Noir")
        if self.game.duel_type == "parite":
            return ("Pair", "Impair")
        return ("1-18", "19-36")

    @discord.ui.button(label="Option A", style=discord.ButtonStyle.success)
    async def b_a(self, inter: discord.Interaction, _):
        await self._pick(inter, 0)

    @discord.ui.button(label="Option B", style=discord.ButtonStyle.secondary)
    async def b_b(self, inter: discord.Interaction, _):
        await self._pick(inter, 1)

    async def on_timeout(self):
        remove_game(self.game)

    async def _pick(self, inter: discord.Interaction, idx: int):
        a, b = self._labels()
        choice = (a if idx == 0 else b)
        # normaliser pour la comparaison
        choice_norm = choice.split()[0].lower().replace("🔴", "rouge").replace("⚫", "noir")
        self.game.starter_choice = choice_norm
        self.game.state = "waiting_player"
        view = JoinView(self.game)
        try:
            await inter.response.edit_message(embed=e_wait_player(self.game), view=view)
        except discord.InteractionResponded:
            msg = await inter.original_response()
            await msg.edit(embed=e_wait_player(self.game), view=view)
        # Animation "…" pendant l'attente
        msg = await inter.original_response()
        for i in range(1, 12):
            await asyncio.sleep(0.7)
            if self.game.state != "waiting_player":
                break
            dots = "." * ((i % 3) + 1)
            try:
                await msg.edit(embed=e_wait_player(self.game, suffix=f"\n\nEn attente d'un second joueur{dots}"), view=view)
            except Exception:
                break
        # Timer d'annulation si personne ne rejoint
        async def _timeout_join():
            await asyncio.sleep(ROULETTE_JOIN_TIMEOUT)
            if self.game.state == "waiting_player" and self.game.joiner_id is None:
                await inter.channel.send(f"⏳ Temps écoulé, partie annulée (créée par <@{self.game.starter_id}>).")
                remove_game(self.game)
        bot.loop.create_task(_timeout_join())

class JoinView(discord.ui.View):
    def __init__(self, game: RouletteGame):
        super().__init__(timeout=ROULETTE_JOIN_TIMEOUT)
        self.game = game

    @discord.ui.button(label="Rejoindre", style=discord.ButtonStyle.primary, emoji="🧍")
    async def b_join(self, inter: discord.Interaction, _):
        if inter.user.id == self.game.starter_id:
            return await inter.response.send_message("Tu es déjà le créateur.", ephemeral=True)
        if self.game.joiner_id is not None:
            return await inter.response.send_message("Un joueur a déjà rejoint.", ephemeral=True)
        self.game.joiner_id = inter.user.id
        self.game.state = "wait_croupier"
        # Ping croupier en DEHORS de l'embed pour un vrai ping
        role_ping = f"<@&{ROLE_CROUPIER_ID}>" if ROLE_CROUPIER_ID else "CROUPIER"
        await inter.channel.send(f"{role_ping} — merci de **valider les mises** pour démarrer la roulette.")
        # Afficher l'embed et la vue croupier
        view = CroupierView(self.game)
        try:
            await inter.response.edit_message(embed=e_wait_croupier(self.game), view=view)
        except discord.InteractionResponded:
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
        # Lancer le spin
        self.game.state = "spinning"
        # Afficher GIF + compte à rebours via followup (plus robuste)
        base = (
            f"👥 <@{self.game.starter_id}> vs <@{self.game.joiner_id}>\n"
            f"⚔️ Duel : **{self.game.duel_type}** — choix créateur **{self.game.starter_choice}**\n"
            f"💵 Mise : **{fmt_kamas(self.game.stake)}** kamas chacun\n"
        )
        embed = discord.Embed(title="🎡 Roulette — c'est parti !", description=base + f"⌛ La roue tourne… **{SPIN_COUNTDOWN}**", color=0xF1C40F)
        if SPIN_GIF_URL:
            embed.set_image(url=SPIN_GIF_URL)
        msg = await inter.response.send_message(embed=embed)
        sent = await inter.original_response()
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

        # Définition victoire selon duel
        def wins(choice: str) -> bool:
            c = choice
            if self.game.duel_type == "couleur":
                return c in {"rouge", "noir"} and (col == c)
            if self.game.duel_type == "parite":
                return c in {"pair", "impair"} and (par == c)
            if self.game.duel_type == "plage":
                return c in {"1-18", "19-36"} and (rng == c)
            return False

        # Cas spécial zéro : push (mises rendues)
        if n == 0:
            title = f"🏁 Résultat : 0 🟢"
            desc = base + "\n**Zéro** — égalité, mises rendues."
            res = discord.Embed(title=title, description=desc, color=0x2ECC71)
            await sent.edit(embed=res, view=None)
            self.game.state = "done"
            remove_game(self.game)
            return

        creator_wins = wins(self.game.starter_choice or "")
        winner_id = self.game.starter_id if creator_wins else self.game.joiner_id
        loser_id = self.game.joiner_id if creator_wins else self.game.starter_id

        # Payout & commission (leaderboard n'inclut PAS la commission)
        pot = self.game.stake * 2
        commission = int(round(pot * CROUPIER_COMMISSION))
        payout = pot - commission

        # Leaderboard : total_bet + net (net = +stake pour gagnant, -stake pour perdant)
        await lb_add_bet(inter.guild.id, self.game.starter_id, self.game.stake)
        await lb_add_bet(inter.guild.id, self.game.joiner_id, self.game.stake)
        await lb_add_net(inter.guild.id, winner_id, +self.game.stake, win=True)
        await lb_add_net(inter.guild.id, loser_id,  -self.game.stake, win=False)
        await lb_add_commission(inter.guild.id, commission)

        # Résultat
        color_emoji = "🔴" if col == "rouge" else ("⚫" if col == "noir" else "🟢")
        title = f"🏁 Résultat : {n} {color_emoji}"
        desc = (
            base +
            f"💵 Pot : {fmt_kamas(pot)}k — 🧮 Commission croupier {int(CROUPIER_COMMISSION*100)}% = {fmt_kamas(commission)}k\n" +
            f"🏆 Gagnant : <@{winner_id}> **+{fmt_kamas(payout)}k**  |  😿 Perdant : <@{loser_id}> **-{fmt_kamas(self.game.stake)}k**"
        )
        col_for_embed = 0x2ECC71 if col == "vert" else (0xE74C3C if col == "rouge" else 0x2C3E50)
        res = discord.Embed(title=title, description=desc, color=col_for_embed)
        await sent.edit(embed=res, view=None)
        self.game.state = "done"
        remove_game(self.game)

# ------------------ Slash commands ------------------
@bot.tree.command(name="roulette", description="Créer une roulette 1v1 (croupier requis)")
@app_commands.describe(mise="Mise unitaire (kamas) pour chaque joueur")
async def roulette_cmd(inter: discord.Interaction, mise: int):
    if mise <= 0:
        return await inter.response.send_message("La mise doit être un entier positif.", ephemeral=True)
    game = RouletteGame(channel_id=inter.channel_id, starter_id=inter.user.id, stake=mise)
    add_game(game)
    await inter.response.send_message(embed=e_start(game), view=DuelSelectView(game))

@bot.tree.command(name="leaderboard", description="Classement du serveur (mises & net)")
async def leaderboard_cmd(inter: discord.Interaction):
    await inter.response.defer(thinking=True)
    rows = await lb_get_rows(inter.guild.id)
    if not rows:
        return await inter.followup.send("Aucune donnée pour l'instant.")
    lines = []
    for i, (uid, total, net, w, l) in enumerate(rows, start=1):
        lines.append(f"**{i}.** <@{uid}> — misé `{fmt_kamas(total)}k` • net `{fmt_kamas(net)}k` • W/L {w}/{l}")
    embed = discord.Embed(title="🏆 Leaderboard serveur", description="\n".join(lines), color=0x9B59B6)
    await inter.followup.send(embed=embed)

# ------------------ Main ------------------
if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN manquant")
    bot.run(TOKEN)
