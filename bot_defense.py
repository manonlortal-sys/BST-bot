import os
import asyncio
import random
import threading
import sqlite3
from datetime import datetime, timezone
from typing import Optional

import discord
from discord.ext import commands
from discord import app_commands
from flask import Flask
import aiosqlite

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
TOKEN = os.getenv("DISCORD_TOKEN", "")
ROLE_CROUPIER_ID = int(os.getenv("ROLE_CROUPIER_ID", "0") or 0)
LEADERBOARD_CHANNEL_ID = int(os.getenv("LEADERBOARD_CHANNEL_ID", "0") or 0)
SPIN_GIF_URL = os.getenv("SPIN_GIF_URL", "")
DB_PATH = os.getenv("DB_PATH", "casino.db")

# Timers
JOIN_TIMEOUT = 300          # 5 min pour qu’un joueur 2 rejoigne
CROUPIER_TIMEOUT = 300      # 5 min pour que le croupier valide

# Discord intents / bot
intents = discord.Intents.default()
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ------------------ DB INIT ------------------
SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS lb_users (
  guild_id     INTEGER NOT NULL,
  user_id      INTEGER NOT NULL,
  total_bet    INTEGER NOT NULL DEFAULT 0,
  net          INTEGER NOT NULL DEFAULT 0,
  wins         INTEGER NOT NULL DEFAULT 0,
  losses       INTEGER NOT NULL DEFAULT 0,
  best_gain    INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS lb_croupier_users (
  guild_id         INTEGER NOT NULL,
  user_id          INTEGER NOT NULL,
  commission_total INTEGER NOT NULL DEFAULT 0,
  tx_count         INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS sticky_messages (
  guild_id   INTEGER NOT NULL,
  kind       TEXT    NOT NULL,   -- 'players' | 'croupiers'
  channel_id INTEGER NOT NULL,
  message_id INTEGER NOT NULL,
  PRIMARY KEY (guild_id, kind)
);
"""

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        for stmt in SCHEMA_SQL.strip().split(";\n\n"):
            if stmt.strip():
                await db.execute(stmt)
        await db.commit()

asyncio.get_event_loop().run_until_complete(init_db())

# ------------------ Game state ------------------
RED_NUMBERS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
BLACK_NUMBERS = set(range(1, 37)) - RED_NUMBERS

class RouletteGame:
    def __init__(self, channel_id: int, starter_id: int, mise: int):
        self.channel_id = channel_id
        self.starter_id = starter_id
        self.joiner_id: Optional[int] = None

        self.duel_type: Optional[str] = None  # "couleur" | "parité" | "moitié"
        self.choice: Optional[str] = None     # 'rouge'/'noir' | 'pair'/'impair' | '1-18'/'19-36'
        self.joiner_choice: Optional[str] = None

        self.mise = mise
        self.state = "choose_duel"    # choose_duel -> choose_side -> wait_join -> wait_croupier -> spinning -> done
        self.validated = False
        self.created_msg_id: Optional[int] = None
        self.join_deadline = datetime.now(timezone.utc).timestamp() + JOIN_TIMEOUT

# 1 partie par salon (simple & robuste)
active_games: dict[int, RouletteGame] = {}  # channel_id -> game

# ------------------ Embeds helpers ------------------
def emb_choose_duel(g: RouletteGame) -> discord.Embed:
    return discord.Embed(
        title="🎰 Roulette – Choix du duel",
        description=(
            f"**Créateur :** <@{g.starter_id}>\n"
            f"**Mise :** {g.mise}k\n\n"
            "Choisis un type de duel ci-dessous :"
        ),
        color=0xE67E22
    )

def emb_choose_side(g: RouletteGame) -> discord.Embed:
    label = {
        "couleur": "🔴⚫ **Rouge/Noir**",
        "parité": "➗ **Pair/Impair**",
        "moitié": "↔️ **1-18 / 19-36**",
    }[g.duel_type]
    return discord.Embed(
        title="🎰 Roulette – Choisis ton camp",
        description=(
            f"**Duel :** {label}\n"
            f"**Mise :** {g.mise}k\n\n"
            "Clique sur l’un des deux boutons pour définir **ton camp**."
        ),
        color=0x3498DB
    )

def emb_wait_join(g: RouletteGame) -> discord.Embed:
    return discord.Embed(
        title="🎲 Partie ouverte",
        description=(
            f"**Créateur :** <@{g.starter_id}> — mise **{g.mise}k**\n"
            f"**Duel :** {g.duel_type} | **Camp du créateur :** {g.choice}\n\n"
            "➡️ Tape **`/roulette`** pour rejoindre et prendre l’autre camp !\n"
            f"⏳ Annulation auto dans **{JOIN_TIMEOUT//60} min** si personne ne rejoint."
        ),
        color=0xF1C40F
    )

def emb_wait_croupier(g: RouletteGame) -> discord.Embed:
    return discord.Embed(
        title="💰 Validation des mises requise",
        description=(
            f"**Créateur :** <@{g.starter_id}> ({g.choice})\n"
            f"**Adversaire :** <@{g.joiner_id}> ({g.joiner_choice})\n"
            f"**Mise :** {g.mise}k chacun — **Pot : {g.mise*2}k**\n"
            f"**Duel :** {g.duel_type}\n\n"
            "Un **croupier** doit valider pour lancer la roue."
        ),
        color=0xE74C3C
    )

def emb_spinning(g: RouletteGame) -> discord.Embed:
    e = discord.Embed(
        title="🎰 Roulette en cours...",
        description="⌛ La roue tourne...",
        color=0x95A5A6
    )
    if SPIN_GIF_URL:
        e.set_image(url=SPIN_GIF_URL)
    return e

def emb_result(g: RouletteGame, n: int, col: str, winner_id: Optional[int], commission: int) -> discord.Embed:
    lines = [f"🎯 **Résultat :** {n} ({col})"]
    if winner_id:
        gain = g.mise*2 - commission
        lines.append(f"🏆 **Gagnant :** <@{winner_id}> — **{gain}k**")
        lines.append(f"💸 **Commission croupier :** {commission}k")
        color = 0x2ECC71
    else:
        lines.append("❌ Aucun gagnant (0 ne paie aucun camp).")
        color = 0xC0392B
    return discord.Embed(title="🎲 Résultat de la roulette", description="\n".join(lines), color=color)

# ------------------ Views (UI) ------------------
class DuelSelectView(discord.ui.View):
    def __init__(self, game: RouletteGame):
        super().__init__(timeout=180)
        self.game = game

    async def _set(self, inter: discord.Interaction, duel_type: str):
        if inter.user.id != self.game.starter_id:
            await inter.response.send_message("Seul le créateur peut choisir le duel.", ephemeral=True)
            return
        self.game.duel_type = duel_type
        self.game.state = "choose_side"
        # switch vers choix de camp
        await inter.response.edit_message(embed=emb_choose_side(self.game), view=SideSelectView(self.game))

    @discord.ui.button(label="🔴⚫ Rouge/Noir", style=discord.ButtonStyle.danger)
    async def b_color(self, inter: discord.Interaction, _):
        await self._set(inter, "couleur")

    @discord.ui.button(label="➗ Pair/Impair", style=discord.ButtonStyle.primary)
    async def b_parity(self, inter: discord.Interaction, _):
        await self._set(inter, "parité")

    @discord.ui.button(label="↔️ 1-18 / 19-36", style=discord.ButtonStyle.success)
    async def b_half(self, inter: discord.Interaction, _):
        await self._set(inter, "moitié")

class SideSelectView(discord.ui.View):
    def __init__(self, game: RouletteGame):
        super().__init__(timeout=180)
        self.game = game
        # deux boutons dynamiques selon duel
        a_label, b_label = {
            "couleur": ("Rouge", "Noir"),
            "parité": ("Pair", "Impair"),
            "moitié": ("1-18", "19-36"),
        }[self.game.duel_type]
        self.a_label = a_label
        self.b_label = b_label

        self.add_item(discord.ui.Button(label=f"✅ {a_label}", style=discord.ButtonStyle.success, custom_id="side_a"))
        self.add_item(discord.ui.Button(label=f"✅ {b_label}", style=discord.ButtonStyle.secondary, custom_id="side_b"))

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.user.id != self.game.starter_id:
            await inter.response.send_message("Seul le créateur choisit son camp.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="(hidden)", style=discord.ButtonStyle.secondary)
    async def dummy(self, inter: discord.Interaction, _):
        pass  # placeholder never used (we add our own items above)

    async def on_timeout(self) -> None:
        # rien à faire ; si timeout, le créateur relance
        pass

    async def on_item_interaction(self, inter: discord.Interaction):
        # gère side_a / side_b
        cid = inter.data.get("custom_id")
        if cid == "side_a":
            self.game.choice = self.a_label.lower()
        elif cid == "side_b":
            self.game.choice = self.b_label.lower()
        else:
            return

        self.game.state = "wait_join"
        await inter.response.edit_message(embed=emb_wait_join(self.game), view=None)

    async def callback(self, inter: discord.Interaction):
        # fallback (discord.py gère via item.callback habituellement)
        await self.on_item_interaction(inter)

    async def interaction_check_item(self, inter: discord.Interaction, item: discord.ui.Item) -> bool:
        return await self.interaction_check(inter)

    async def on_error(self, error: Exception, item: discord.ui.Item, inter: discord.Interaction) -> None:
        try:
            await inter.response.send_message("Erreur lors du choix du camp.", ephemeral=True)
        except Exception:
            pass

    # override dispatch to catch custom_id buttons
    async def _scheduled_task(self, item: discord.ui.Item, inter: discord.Interaction):
        # hijack to handle our synthetic buttons
        await self.on_item_interaction(inter)

class ValidateView(discord.ui.View):
    def __init__(self, game: RouletteGame):
        super().__init__(timeout=CROUPIER_TIMEOUT)
        self.game = game

    @discord.ui.button(label="✅ Valider les mises", style=discord.ButtonStyle.success)
    async def validate(self, inter: discord.Interaction, _):
        # sécurités
        if self.game.state != "wait_croupier" or self.game.validated:
            await inter.response.send_message("Cette table n'est pas en attente de validation.", ephemeral=True)
            return
        # rôle croupier requis (si défini)
        if ROLE_CROUPIER_ID and not any(r.id == ROLE_CROUPIER_ID for r in inter.user.roles):
            await inter.response.send_message("Seul un **croupier** peut valider.", ephemeral=True)
            return

        self.game.validated = True
        self.game.state = "spinning"

        # on affiche le GIF de spin
        await inter.response.edit_message(embed=emb_spinning(self.game), view=None)

        # petite attente "immersive"
        await asyncio.sleep(4)

        # tirage
        n = random.randint(0, 36)
        col = "vert" if n == 0 else ("rouge" if n in RED_NUMBERS else "noir")

        def is_win(choice: Optional[str], duel: Optional[str]) -> bool:
            if not choice or not duel:
                return False
            if duel == "couleur":
                if n == 0:
                    return False
                return (choice == "rouge" and n in RED_NUMBERS) or (choice == "noir" and n in BLACK_NUMBERS)
            if duel == "parité":
                if n == 0:
                    return False
                return (choice == "pair" and n % 2 == 0) or (choice == "impair" and n % 2 == 1)
            if duel == "moitié":
                return (choice == "1-18" and 1 <= n <= 18) or (choice == "19-36" and 19 <= n <= 36)
            return False

        # gagnant / perdant
        winner_id = None
        loser_id = None
        if is_win(self.game.choice, self.game.duel_type):
            winner_id = self.game.starter_id
            loser_id = self.game.joiner_id
        elif is_win(self.game.joiner_choice, self.game.duel_type):
            winner_id = self.game.joiner_id
            loser_id = self.game.starter_id

        pot = self.game.mise * 2
        commission = int(pot * 0.05)
        result_embed = emb_result(self.game, n, col, winner_id, commission)
        await inter.message.edit(embed=result_embed)

        # maj stats SQL (joueurs + croupier cliquent)
        await update_stats_after_game(
            guild_id=inter.guild.id,
            starter_id=self.game.starter_id,
            joiner_id=self.game.joiner_id,
            winner_id=winner_id,
            loser_id=loser_id,
            mise=self.game.mise,
            commission=commission,
            croupier_id=inter.user.id,  # <<<<<<<<<< le croupier qui a validé
        )

        # MAJ des 2 leaderboards collants
        await update_both_leaderboards(inter.guild)

        # fin de partie
        active_games.pop(self.game.channel_id, None)

# ------------------ Stats & Leaderboards ------------------
async def update_stats_after_game(
    guild_id: int,
    starter_id: int,
    joiner_id: int,
    winner_id: Optional[int],
    loser_id: Optional[int],
    mise: int,
    commission: int,
    croupier_id: int,
):
    pot = mise * 2
    gain = pot - commission   # montant payé au gagnant

    async with aiosqlite.connect(DB_PATH) as db:
        # total bet + net + wins/losses + best_gain
        for uid in (starter_id, joiner_id):
            await db.execute(
                """INSERT INTO lb_users (guild_id, user_id, total_bet, net, wins, losses, best_gain)
                   VALUES (?, ?, ?, 0, 0, 0, 0)
                   ON CONFLICT(guild_id, user_id) DO NOTHING""",
                (guild_id, uid, mise)
            )
            await db.execute(
                "UPDATE lb_users SET total_bet = total_bet + ? WHERE guild_id=? AND user_id=?",
                (mise, guild_id, uid)
            )

        if winner_id and loser_id:
            # gagnant : net += (gain - mise)  (car il a misé sa mise, récupère gain total)
            await db.execute(
                "UPDATE lb_users SET net = net + ?, wins = wins + 1, best_gain = MAX(best_gain, ?) WHERE guild_id=? AND user_id=?",
                (gain - mise, gain, guild_id, winner_id)
            )
            # perdant : net -= mise
            await db.execute(
                "UPDATE lb_users SET net = net - ?, losses = losses + 1 WHERE guild_id=? AND user_id=?",
                (mise, guild_id, loser_id)
            )

        # croupier : commission_total +1
        await db.execute(
            """INSERT INTO lb_croupier_users (guild_id, user_id, commission_total, tx_count)
               VALUES (?, ?, ?, 1)
               ON CONFLICT(guild_id, user_id)
               DO UPDATE SET commission_total = commission_total + excluded.commission_total,
                             tx_count = tx_count + 1""",
            (guild_id, croupier_id, commission)
        )

        await db.commit()

def fmt_players_leaderboard_rows(rows):
    lines = []
    total = 0
    for idx, (uid, total_bet, net) in enumerate(rows, start=1):
        total += total_bet
        lines.append(f"**{idx}.** <@{uid}> — misé **{total_bet}k** · net **{net}k**")
    lines.append(f"\n**Total misé (serveur) : {total}k**")
    return "\n".join(lines)

def fmt_croupiers_leaderboard_rows(rows):
    lines = []
    total_comm = 0
    for idx, (uid, comm, cnt) in enumerate(rows, start=1):
        total_comm += comm
        lines.append(f"**{idx}.** <@{uid}> — commission **{comm}k** · tables **{cnt}**")
    lines.append(f"\n**Total commissions : {total_comm}k**")
    return "\n".join(lines)

async def get_or_create_sticky_message(guild: discord.Guild, kind: str) -> Optional[discord.Message]:
    """kind: 'players' | 'croupiers'"""
    if not LEADERBOARD_CHANNEL_ID:
        return None
    channel = guild.get_channel(LEADERBOARD_CHANNEL_ID)
    if channel is None:
        return None

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT message_id FROM sticky_messages WHERE guild_id=? AND kind=?",
            (guild.id, kind)
        )
        row = await cur.fetchone()

    if row:
        msg_id = int(row[0])
        try:
            msg = await channel.fetch_message(msg_id)
            return msg
        except discord.NotFound:
            pass  # on recréera juste après

    # créer nouveau message sticky
    title = "🏅 Leaderboard" if kind == "players" else "🏅 Leaderboard Croupiers"
    msg = await channel.send(embed=discord.Embed(title=title, description="(initialisation…)", color=0x8E44AD))

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO sticky_messages (guild_id, kind, channel_id, message_id)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(guild_id, kind) DO UPDATE SET channel_id=excluded.channel_id, message_id=excluded.message_id""",
            (guild.id, kind, channel.id, msg.id)
        )
        await db.commit()
    return msg

async def update_players_leaderboard(guild: discord.Guild):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id, total_bet, net FROM lb_users WHERE guild_id=? ORDER BY total_bet DESC, user_id ASC",
            (guild.id,)
        )
        rows = await cur.fetchall()

    desc = "Aucune donnée." if not rows else fmt_players_leaderboard_rows(rows)
    embed = discord.Embed(title="🏅 Leaderboard", description=desc, color=0x9B59B6)
    embed.set_footer(text=f"Dernière mise à jour : {datetime.now().strftime('%d/%m %H:%M')}")
    msg = await get_or_create_sticky_message(guild, "players")
    if msg:
        try:
            await msg.edit(embed=embed)
        except discord.Forbidden:
            pass

async def update_croupiers_leaderboard(guild: discord.Guild):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id, commission_total, tx_count FROM lb_croupier_users WHERE guild_id=? ORDER BY commission_total DESC, tx_count DESC, user_id ASC",
            (guild.id,)
        )
        rows = await cur.fetchall()

    desc = "Aucune donnée." if not rows else fmt_croupiers_leaderboard_rows(rows)
    embed = discord.Embed(title="🏅 Leaderboard Croupiers", description=desc, color=0x1ABC9C)
    embed.set_footer(text=f"Dernière mise à jour : {datetime.now().strftime('%d/%m %H:%M')}")
    msg = await get_or_create_sticky_message(guild, "croupiers")
    if msg:
        try:
            await msg.edit(embed=embed)
        except discord.Forbidden:
            pass

async def update_both_leaderboards(guild: discord.Guild):
    await update_players_leaderboard(guild)
    await update_croupiers_leaderboard(guild)

# ------------------ Commands ------------------
@bot.tree.command(name="roulette", description="Créer ou rejoindre une roulette (le créateur choisit le duel et son camp)")
@app_commands.describe(mise="Montant de la mise (en 'kamas', entier > 0)")
async def roulette_cmd(inter: discord.Interaction, mise: int = 1000):
    if mise <= 0:
        await inter.response.send_message("La mise doit être un entier positif.", ephemeral=True)
        return

    ch_id = inter.channel.id
    g = active_games.get(ch_id)

    # créer une partie si aucune
    if g is None:
        g = RouletteGame(channel_id=ch_id, starter_id=inter.user.id, mise=mise)
        active_games[ch_id] = g
        await inter.response.send_message(embed=emb_choose_duel(g), view=DuelSelectView(g))
        return

    # sinon tenter de rejoindre
    if g.state != "wait_join" or g.joiner_id is not None:
        await inter.response.send_message("Aucune partie disponible à rejoindre dans ce salon.", ephemeral=True)
        return
    if inter.user.id == g.starter_id:
        await inter.response.send_message("Tu es déjà le créateur de cette partie.", ephemeral=True)
        return

    # attribuer le camp opposé
    opposite = {
        "rouge": "noir", "noir": "rouge",
        "pair": "impair", "impair": "pair",
        "1-18": "19-36", "19-36": "1-18",
    }.get(g.choice, None)
    if not opposite:
        await inter.response.send_message("Partie invalide (camp du créateur manquant).", ephemeral=True)
        return

    g.joiner_id = inter.user.id
    g.joiner_choice = opposite
    g.state = "wait_croupier"

    # ping croupier **en dehors** de l'embed pour notifier
    if ROLE_CROUPIER_ID:
        await inter.channel.send(f"<@&{ROLE_CROUPIER_ID}> — merci de **valider les mises** pour lancer la roulette.")

    await inter.response.send_message(embed=emb_wait_croupier(g), view=ValidateView(g))

@bot.tree.command(name="leaderboard", description="Afficher le leaderboard joueurs (et rafraîchir le sticky message)")
async def leaderboard_cmd(inter: discord.Interaction):
    await inter.response.defer(thinking=False)
    await update_players_leaderboard(inter.guild)
    # renvoyer aussi en direct
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id, total_bet, net FROM lb_users WHERE guild_id=? ORDER BY total_bet DESC, user_id ASC",
            (inter.guild.id,)
        )
        rows = await cur.fetchall()
    desc = "Aucune donnée." if not rows else fmt_players_leaderboard_rows(rows)
    await inter.followup.send(embed=discord.Embed(title="🏅 Leaderboard", description=desc, color=0x9B59B6))

@bot.tree.command(name="croupierboard", description="Afficher le leaderboard croupiers (et rafraîchir le sticky message)")
async def croupierboard_cmd(inter: discord.Interaction):
    await inter.response.defer(thinking=False)
    await update_croupiers_leaderboard(inter.guild)
    # renvoyer aussi en direct
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id, commission_total, tx_count FROM lb_croupier_users WHERE guild_id=? ORDER BY commission_total DESC, tx_count DESC, user_id ASC",
            (inter.guild.id,)
        )
        rows = await cur.fetchall()
    desc = "Aucune donnée." if not rows else fmt_croupiers_leaderboard_rows(rows)
    await inter.followup.send(embed=discord.Embed(title="🏅 Leaderboard Croupiers", description=desc, color=0x1ABC9C))

# ------------------ Bot lifecycle ------------------
@bot.event
async def on_ready():
    print(f"Connecté en tant que {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"Slash commands sync: {len(synced)}")
    except Exception as e:
        print("Sync error:", e)
    # Init/refresh sticky boards (facultatif au boot)
    if LEADERBOARD_CHANNEL_ID:
        for guild in bot.guilds:
            await update_both_leaderboards(guild)

# ------------------ Run ------------------
if not TOKEN:
    raise SystemExit("DISCORD_TOKEN manquant dans les variables d'environnement.")
bot.run(TOKEN)
