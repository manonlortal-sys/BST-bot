# =========================
#  Roulette à 2 joueurs – Discord (Render Web Service)
#  - Commission croupier 5% du pot (affichée dans le résultat)
#  - Leaderboard PAR SERVEUR (DB), mis à jour automatiquement
#  - Message épinglé dans un canal défini via /lb_set_channel
# =========================

import os
os.environ.setdefault("MPLBACKEND", "Agg")

import asyncio
import random
import threading
import sqlite3
from dataclasses import dataclass
from typing import Optional, Dict, List

import discord
from discord import app_commands
from discord.ext import commands
from flask import Flask
from dotenv import load_dotenv
import discord.utils

# ---------- Mini serveur HTTP pour Render ----------
app = Flask(__name__)

@app.route("/")
def home():
    return "Roulette bot actif"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_flask, daemon=True).start()

# ---------- Config ----------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise SystemExit("DISCORD_TOKEN manquant")

SPIN_GIF_URL = os.getenv("SPIN_GIF_URL", "https://media.tenor.com/e3QG3W1u3lAAAAAC/roulette-casino.gif")
THUMB_URL    = os.getenv("THUMB_URL", "")

# Croupier
CROUPIER_ROLE_ID   = int(os.getenv("CROUPIER_ROLE_ID", "0")) or None
CROUPIER_ROLE_NAME = os.getenv("CROUPIER_ROLE_NAME", "CROUPIER")

# Commission
COMMISSION_RATE = float(os.getenv("CROUPIER_COMMISSION_RATE", "0.05"))  # 5%

# Leaderboard épinglé
LEADERBOARD_CHANNEL_ID = int(os.getenv("LEADERBOARD_CHANNEL_ID", "0")) or None

# DB
DB_PATH = os.getenv("DB_PATH", "roulette_stats.db")

# Couleurs
COLOR_RED   = 0xE74C3C
COLOR_BLACK = 0x2C3E50
COLOR_GREEN = 0x2ECC71
COLOR_GOLD  = 0xF1C40F

# Nombres rouges (roulette EU)
RED_NUMBERS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}

def fmt_kamas(n: int) -> str:
    return f"{int(n):,}".replace(",", " ")

print("SPIN_GIF_URL =", SPIN_GIF_URL)
print("DB_PATH =", DB_PATH)

intents = discord.Intents.default()
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- DB utils ----------
_db_lock = threading.Lock()

def db_init():
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        try:
            # Stats par SERVEUR (guild)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_stats(
                    guild_id  INTEGER NOT NULL,
                    user_id   INTEGER NOT NULL,
                    total_bet INTEGER NOT NULL DEFAULT 0,
                    net       INTEGER NOT NULL DEFAULT 0,
                    wins      INTEGER NOT NULL DEFAULT 0,
                    losses    INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            # Commission cumulée (si un jour tu veux l'afficher, on la stocke)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS commission_stats(
                    guild_id INTEGER PRIMARY KEY,
                    total_commission INTEGER NOT NULL DEFAULT 0
                )
            """)
            # Où poster/éditer le leaderboard (message épinglé)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS settings(
                    guild_id INTEGER PRIMARY KEY,
                    leaderboard_channel_id INTEGER,
                    leaderboard_message_id INTEGER
                )
            """)
            conn.commit()
        finally:
            conn.close()

def _upsert_bet(guild_id: int, user_id: int, bet: int):
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute("""
                INSERT INTO user_stats(guild_id, user_id, total_bet, net, wins, losses)
                VALUES (?, ?, ?, 0, 0, 0)
                ON CONFLICT(guild_id, user_id) DO UPDATE
                SET total_bet = total_bet + excluded.total_bet
            """, (guild_id, user_id, bet))
            conn.commit()
        finally:
            conn.close()

def _upsert_net_and_wl(guild_id: int, winner_id: int, loser_id: int, net_gain: int, net_loss: int):
    # net_gain = (payout_to_winner - bet), net_loss = -bet
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute("""
                INSERT INTO user_stats(guild_id, user_id, total_bet, net, wins, losses)
                VALUES (?, ?, 0, ?, 1, 0)
                ON CONFLICT(guild_id, user_id) DO UPDATE
                SET net = net + excluded.net,
                    wins = wins + 1
            """, (guild_id, winner_id, net_gain))
            conn.execute("""
                INSERT INTO user_stats(guild_id, user_id, total_bet, net, wins, losses)
                VALUES (?, ?, 0, ?, 0, 1)
                ON CONFLICT(guild_id, user_id) DO UPDATE
                SET net = net + excluded.net,
                    losses = losses + 1
            """, (guild_id, loser_id, net_loss))
            conn.commit()
        finally:
            conn.close()

def _add_commission(guild_id: int, amount: int):
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute("""
                INSERT INTO commission_stats(guild_id, total_commission)
                VALUES (?, ?)
                ON CONFLICT(guild_id) DO UPDATE
                SET total_commission = total_commission + excluded.total_commission
            """, (guild_id, amount))
            conn.commit()
        finally:
            conn.close()

def _get_leaderboard(guild_id: int, limit: int = 10):
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        try:
            cur = conn.execute("""
                SELECT user_id, total_bet, net, wins, losses
                FROM user_stats
                WHERE guild_id = ?
                ORDER BY total_bet DESC, user_id ASC
                LIMIT ?
            """, (guild_id, limit))
            rows = cur.fetchall()
        finally:
            conn.close()
    return rows

def _get_total_bet_all(guild_id: int):
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        try:
            cur = conn.execute("""
                SELECT COALESCE(SUM(total_bet), 0) FROM user_stats WHERE guild_id = ?
            """, (guild_id,))
            total, = cur.fetchone()
        finally:
            conn.close()
    return int(total or 0)

def _get_settings(guild_id: int):
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        try:
            cur = conn.execute(
                "SELECT leaderboard_channel_id, leaderboard_message_id FROM settings WHERE guild_id=?",
                (guild_id,),
            )
            row = cur.fetchone()
        finally:
            conn.close()
    return row if row else (None, None)

def _set_leaderboard_channel(guild_id: int, channel_id: int):
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute("""
                INSERT INTO settings(guild_id, leaderboard_channel_id, leaderboard_message_id)
                VALUES (?, ?, NULL)
                ON CONFLICT(guild_id) DO UPDATE
                SET leaderboard_channel_id=excluded.leaderboard_channel_id
            """, (guild_id, channel_id))
            conn.commit()
        finally:
            conn.close()

def _set_leaderboard_message(guild_id: int, message_id: int):
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute("""
                INSERT INTO settings(guild_id, leaderboard_channel_id, leaderboard_message_id)
                VALUES (?, NULL, ?)
                ON CONFLICT(guild_id) DO UPDATE
                SET leaderboard_message_id=excluded.leaderboard_message_id
            """, (guild_id, message_id))
            conn.commit()
        finally:
            conn.close()

# ---------- Modèle & utils Roulette ----------
@dataclass
class RouletteGame:
    channel_id: int
    starter_id: int
    bet: int = 0
    duel_type: Optional[str] = None           # "couleur" | "parité" | "intervalle"
    starter_choice: Optional[str] = None      # camp choisi par le créateur
    joiner_id: Optional[int] = None
    choice_joiner: Optional[str] = None       # camp auto (opposé)
    lobby_msg_id: Optional[int] = None
    spin_msg_id: Optional[int] = None
    lobby_task: Optional[asyncio.Task] = None
    wait_msg_id: Optional[int] = None
    wait_anim_task: Optional[asyncio.Task] = None

DUEL_LABELS: Dict[str, List[tuple[str, str]]] = {
    "couleur":    [("🔴 Rouge", "rouge"), ("⚫ Noir", "noir")],
    "parité":     [("🟦 Pair", "pair"), ("🟪 Impair", "impair")],
    "intervalle": [("⬇️ 1-18", "1-18"), ("⬆️ 19-36", "19-36")],
}

def duel_human_name(mode: str) -> str:
    return {
        "couleur":    "rouge/noir",
        "parité":     "pair/impair",
        "intervalle": "1-18/19-36",
    }.get(mode, mode or "?")

def spin_wheel():
    n = random.randint(0, 36)
    if n == 0:
        return n, "vert"
    return n, ("rouge" if n in RED_NUMBERS else "noir")

def color_for_embed(color: str) -> int:
    return COLOR_GREEN if color == "vert" else (COLOR_RED if color == "rouge" else COLOR_BLACK)

def result_label(mode: str, n: int) -> Optional[str]:
    if mode == "couleur":
        if n == 0:
            return None
        return "rouge" if n in RED_NUMBERS else "noir"
    if mode == "parité":
        return "pair" if n % 2 == 0 else "impair"  # 0 = pair (choix fun)
    if mode == "intervalle":
        if 1 <= n <= 18:
            return "1-18"
        if 19 <= n <= 36:
            return "19-36"
        return None
    return None

def opposite_choice(mode: str, choice: str) -> str:
    mapping = {
        ("couleur", "rouge"): "noir",
        ("couleur", "noir"): "rouge",
        ("parité", "pair"): "impair",
        ("parité", "impair"): "pair",
        ("intervalle", "1-18"): "19-36",
        ("intervalle", "19-36"): "1-18",
    }
    return mapping.get((mode, choice), "?")

active_games: Dict[int, List[RouletteGame]] = {}

def resolve_croupier_mention(guild: discord.Guild) -> tuple[str, discord.AllowedMentions]:
    allowed = discord.AllowedMentions(roles=True, users=False, everyone=False, replied_user=False)
    role_mention = None
    if CROUPIER_ROLE_ID:
        r = guild.get_role(CROUPIER_ROLE_ID)
        if r:
            role_mention = r.mention
    if not role_mention and CROUPIER_ROLE_NAME:
        r = discord.utils.get(guild.roles, name=CROUPIER_ROLE_NAME)
        if r:
            role_mention = r.mention
    if not role_mention:
        role_mention = f"@{CROUPIER_ROLE_NAME}"
    return role_mention, allowed

# ---------- Leaderboard rendering ----------
def _format_leaderboard_rows(guild_id: int, limit: int = 10):
    rows = _get_leaderboard(guild_id, limit)
    total_all = _get_total_bet_all(guild_id)
    return rows, total_all

def _leaderboard_embed(guild: discord.Guild, rows, total_all: int) -> discord.Embed:
    lines = []
    for i, (uid, total_bet, net, wins, losses) in enumerate(rows, start=1):
        sign = "＋" if net > 0 else ("－" if net < 0 else "±")
        lines.append(f"**{i}.** <@{uid}> — **{fmt_kamas(total_bet)}** kamas | {sign} {fmt_kamas(abs(net))} | {wins}W-{losses}L")
    if not lines:
        lines = ["Personne n’a encore joué ✨"]

    embed = discord.Embed(
        title="🏆 Leaderboard Roulette (serveur)",
        description="\n".join(lines),
        color=COLOR_GOLD
    )
    embed.add_field(name="💰 Total misé (tous joueurs)", value=f"**{fmt_kamas(total_all)}** kamas", inline=False)
    embed.set_footer(text="Mise à jour auto")
    return embed

async def update_leaderboard_message(guild: discord.Guild):
    db_channel_id, db_message_id = _get_settings(guild.id)
    channel_id = db_channel_id or LEADERBOARD_CHANNEL_ID
    if not channel_id:
        return  # non configuré

    channel = guild.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        return

    rows, total_all = await asyncio.to_thread(_format_leaderboard_rows, guild.id, 10)
    embed = _leaderboard_embed(guild, rows, total_all)

    if db_message_id:
        try:
            msg = await channel.fetch_message(db_message_id)
            await msg.edit(embed=embed, content=None)
            return
        except Exception:
            pass  # message supprimé → on recrée

    msg = await channel.send(embed=embed)
    try:
        await msg.pin()
    except Exception:
        pass
    await asyncio.to_thread(_set_leaderboard_message, guild.id, msg.id)

# ---------- Vues (UI) ----------
class DuelSelectionView(discord.ui.View):
    """Étape 1: le créateur choisit le type de duel (3 boutons)."""
    def __init__(self, game: RouletteGame, *, timeout: float = 300.0):
        super().__init__(timeout=timeout)
        self.game = game

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.game.starter_id:
            await interaction.response.send_message("⛔ Seul le créateur peut choisir le type de duel.", ephemeral=True)
            return False
        return True

    async def on_button(self, interaction: discord.Interaction, duel_type: str):
        self.game.duel_type = duel_type
        labels = " / ".join(lbl for lbl, _ in DUEL_LABELS.get(duel_type, []))
        embed = discord.Embed(
            title="🎲 Roulette – Choix du camp",
            description=(
                f"Créateur : <@{self.game.starter_id}>\n"
                f"🎮 Duel : **{duel_human_name(duel_type)}** ({labels})\n"
                f"💵 Mise : **{fmt_kamas(self.game.bet)}** kamas\n\n"
                "➡️ Choisis ton **camp** ci-dessous."
            ),
            color=COLOR_GOLD
        )
        if THUMB_URL:
            embed.set_thumbnail(url=THUMB_URL)
        await interaction.response.edit_message(embed=embed, view=CampSelectionView(self.game))

    @discord.ui.button(label="🔴⚫ rouge/noir", style=discord.ButtonStyle.primary, row=0)
    async def _b_couleur(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.on_button(interaction, "couleur")

    @discord.ui.button(label="🟦🟪 pair/impair", style=discord.ButtonStyle.secondary, row=0)
    async def _b_parite(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.on_button(interaction, "parité")

    @discord.ui.button(label="⬇️⬆️ 1-18/19-36", style=discord.ButtonStyle.success, row=0)
    async def _b_intervalle(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.on_button(interaction, "intervalle")

class CampSelectionView(discord.ui.View):
    """Étape 2: le créateur choisit son camp (2 boutons selon le duel)."""
    def __init__(self, game: RouletteGame, *, timeout: float = 300.0):
        super().__init__(timeout=timeout)
        self.game = game
        labels = DUEL_LABELS.get(game.duel_type or "", [])
        if len(labels) != 2:
            labels = [("Option A", "A"), ("Option B", "B")]

        b1 = discord.ui.Button(label=labels[0][0], style=discord.ButtonStyle.primary)
        async def cb1(inter: discord.Interaction):
            await self._resolve(inter, labels[0][1])
        b1.callback = cb1
        self.add_item(b1)

        b2 = discord.ui.Button(label=labels[1][0], style=discord.ButtonStyle.secondary)
        async def cb2(inter: discord.Interaction):
            await self._resolve(inter, labels[1][1])
        b2.callback = cb2
        self.add_item(b2)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.game.starter_id:
            await interaction.response.send_message("⛔ Seul le créateur peut choisir son camp.", ephemeral=True)
            return False
        return True

    async def _resolve(self, interaction: discord.Interaction, starter_choice: str):
        self.game.starter_choice = starter_choice
        opp = opposite_choice(self.game.duel_type or "", starter_choice)

        base_desc = (
            f"👤 Créateur : <@{self.game.starter_id}>\n"
            f"🎮 Duel : **{duel_human_name(self.game.duel_type or '')}**\n"
            f"🧭 Camp créateur : **{starter_choice}** (l'autre joueur sera **{opp}**)\n"
            f"💵 Mise : **{fmt_kamas(self.game.bet)}** kamas\n\n"
            "➡️ **Tape `/roulette` dans ce salon pour rejoindre la partie.**\n"
            "🕐 En attente d'un second joueur"
        )
        embed = discord.Embed(title="🎲 Lobby ouvert", description=base_desc + "...", color=COLOR_GOLD)
        if THUMB_URL:
            embed.set_thumbnail(url=THUMB_URL)

        await interaction.response.edit_message(embed=embed, view=None)
        msg = interaction.message
        self.game.lobby_msg_id = msg.id
        self.game.wait_msg_id = msg.id

        async def animate_wait():
            sequence = ["", ".", "..", "...", "..", "."]
            idx = 0
            try:
                while self.game.joiner_id is None:
                    trail = sequence[idx]
                    idx = (idx + 1) % len(sequence)
                    embed.description = (
                        f"👤 Créateur : <@{self.game.starter_id}>\n"
                        f"🎮 Duel : **{duel_human_name(self.game.duel_type or '')}**\n"
                        f"🧭 Camp créateur : **{starter_choice}** (l'autre joueur sera **{opp}**)\n"
                        f"💵 Mise : **{fmt_kamas(self.game.bet)}** kamas\n\n"
                        "➡️ **Tape `/roulette` dans ce salon pour rejoindre la partie.**\n"
                        f"🕐 En attente d'un second joueur{trail}"
                    )
                    await msg.edit(embed=embed)
                    await asyncio.sleep(1.2)
            except asyncio.CancelledError:
                pass

        self.game.wait_anim_task = bot.loop.create_task(animate_wait())

        async def lobby_timeout():
            await asyncio.sleep(300)
            if self.game.joiner_id is None:
                if self.game.wait_anim_task and not self.game.wait_anim_task.done():
                    self.game.wait_anim_task.cancel()
                await interaction.channel.send(f"⏳ Lobby expiré (créé par <@{self.game.starter_id}>).")
                try:
                    active_games[self.game.channel_id].remove(self.game)
                    if not active_games[self.game.channel_id]:
                        active_games.pop(self.game.channel_id, None)
                except Exception:
                    pass

        self.game.lobby_task = bot.loop.create_task(lobby_timeout())

class CroupierView(discord.ui.View):
    """Validation des mises par le rôle CROUPIER, puis lancement du spin."""
    def __init__(self, game: RouletteGame, *, timeout: float = 300.0):
        super().__init__(timeout=timeout)
        self.game = game

    async def _is_croupier(self, interaction: discord.Interaction) -> bool:
        member: discord.Member = interaction.user  # type: ignore
        if CROUPIER_ROLE_ID and any(r.id == CROUPIER_ROLE_ID for r in member.roles):
            return True
        if any(r.name.upper() == CROUPIER_ROLE_NAME.upper() for r in member.roles):
            return True
        await interaction.response.send_message("⛔ Réservé au rôle **CROUPIER**.", ephemeral=True)
        return False

    @discord.ui.button(label="✅ Mises récupérées", style=discord.ButtonStyle.success, emoji="💰")
    async def btn_valider(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._is_croupier(interaction):
            return
        await launch_spin(interaction, self.game)

    @discord.ui.button(label="❌ Annuler", style=discord.ButtonStyle.danger)
    async def btn_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._is_croupier(interaction):
            return
        try:
            active_games[self.game.channel_id].remove(self.game)
            if not active_games[self.game.channel_id]:
                active_games.pop(self.game.channel_id, None)
        except Exception:
            pass
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="🛑 Partie annulée par le CROUPIER",
                description=f"Créateur : <@{self.game.starter_id}> — Mise : {fmt_kamas(self.game.bet)} kamas",
                color=COLOR_RED,
            ),
            view=None
        )

# ---------- Spin + enregistrement des stats ----------
async def launch_spin(interaction: discord.Interaction, game: RouletteGame):
    # Stop animation si elle tourne encore
    if game.wait_anim_task and not game.wait_anim_task.done():
        game.wait_anim_task.cancel()

    guild_id = interaction.guild.id

    # Enregistrer les mises (total_bet) pour les deux joueurs (NEUTRE inclus)
    await asyncio.to_thread(_upsert_bet, guild_id, game.starter_id, game.bet)
    await asyncio.to_thread(_upsert_bet, guild_id, game.joiner_id, game.bet)

    base = (
        f"🎮 Duel : **{duel_human_name(game.duel_type or '')}**\n"
        f"👥 <@{game.starter_id}> ({game.starter_choice}) vs <@{game.joiner_id}> ({game.choice_joiner})\n"
        f"💵 Mise : **{fmt_kamas(game.bet)}** kamas (par joueur)\n"
    )
    spin = discord.Embed(title="🎰 SPIN EN COURS !", description=base + "⌛ La roue tourne... **5**", color=COLOR_GOLD)
    if THUMB_URL: spin.set_thumbnail(url=THUMB_URL)
    if SPIN_GIF_URL: spin.set_image(url=SPIN_GIF_URL)

    await interaction.response.edit_message(embed=spin, view=None)
    msg = interaction.message

    for t in [4,3,2,1]:
        await asyncio.sleep(1)
        try:
            spin.description = base + f"⌛ La roue tourne... **{t}**"
            await msg.edit(embed=spin)
        except:
            break
    await asyncio.sleep(1)

    # Évite 0 pour "couleur" en 3 essais max (sinon neutre)
    attempts = 0
    while True:
        attempts += 1
        n, col = spin_wheel()
        res = result_label(game.duel_type or "", n)
        if res is not None or attempts >= 3:
            break

    pot_total = game.bet * 2
    commission = int(round(pot_total * COMMISSION_RATE))
    payout_to_winner = pot_total - commission

    # Décide du gagnant selon le camp choisi par le créateur
    if res == (game.starter_choice or ""):
        winner, loser = game.starter_id, game.joiner_id
    elif res == (game.choice_joiner or ""):
        winner, loser = game.joiner_id, game.starter_id
    else:
        winner = loser = None

    # MAJ stats : si gagnant/perdant -> net
    # net gagnant = (payout - sa mise) = (2*bet - commission - bet) = bet - commission
    # net perdant = - bet
    if winner is not None and loser is not None:
       net_gain = payout_to_winner            # <- gagnant encaisse (2×mise - commission)
net_loss = -game.bet                   # <- perdant perd sa mise
await asyncio.to_thread(_upsert_net_and_wl, guild_id, winner, loser, net_gain, net_loss)

        await asyncio.to_thread(_add_commission, guild_id, commission)

    # Titre/emoji
    color_for_title = col if game.duel_type == "couleur" else ("vert" if n == 0 else ("rouge" if n in RED_NUMBERS else "noir"))
    color_emoji = "🔴" if color_for_title == "rouge" else ("⚫" if color_for_title == "noir" else "🟢" if n == 0 else "")
    title = f"🏁 Résultat : {n} {color_emoji}"

    # Description finale (commission affichée uniquement ici)
    if winner:
        desc = (
            f"🎮 Duel : **{duel_human_name(game.duel_type or '')}**\n"
            f"💰 Pot total : **{fmt_kamas(pot_total)}** kamas\n"
            f"💼 Commission CROUPIER ({int(COMMISSION_RATE*100)}%) : **{fmt_kamas(commission)}** kamas\n\n"
            f"🏆 Gagnant : <@{winner}>  **+{fmt_kamas(payout_to_winner)}** kamas\n"
            f"😔 Perdant : <@{loser}>   **-{fmt_kamas(game.bet)}** kamas"
        )
        color = color_for_embed(color_for_title)
    else:
        desc = (
            f"🎮 Duel : **{duel_human_name(game.duel_type or '')}**\n"
            f"⚖️ Résultat neutre — **mises rendues**."
        )
        color = COLOR_GOLD

    result = discord.Embed(title=title, description=desc, color=color)
    if THUMB_URL: result.set_thumbnail(url=THUMB_URL)
    try:
        await msg.edit(embed=result, view=None)
    except:
        await interaction.channel.send(embed=result)

    # Nettoyage
    try:
        active_games[game.channel_id].remove(game)
        if not active_games[game.channel_id]:
            active_games.pop(game.channel_id, None)
    except Exception:
        pass

    # MAJ leaderboard
    try:
        await update_leaderboard_message(interaction.guild)
    except Exception as e:
        print("Leaderboard update error:", e)

# ---------- Slash /roulette ----------
@bot.tree.command(name="roulette", description="Créer/Rejoindre une roulette (mise en kamas)")
@app_commands.describe(mise="Montant à miser (créateur uniquement)")
async def roulette_cmd(interaction: discord.Interaction, mise: Optional[int] = None):
    # ACK immédiat
    try:
        await interaction.response.send_message("⌛ Préparation…", ephemeral=True)
    except discord.InteractionResponded:
        pass

    channel_id = interaction.channel_id
    user_id = interaction.user.id

    # 1) Rejoindre un lobby prêt
    open_ready = [
        g for g in active_games.get(channel_id, [])
        if g.joiner_id is None and g.duel_type is not None and g.starter_choice is not None and g.starter_id != user_id
    ]
    if open_ready:
        game = open_ready[0]
        game.joiner_id = user_id
        game.choice_joiner = opposite_choice(game.duel_type or "", game.starter_choice or "")
        # stop anim & timeout
        if game.wait_anim_task and not game.wait_anim_task.done():
            game.wait_anim_task.cancel()
        if game.lobby_task and not game.lobby_task.done():
            game.lobby_task.cancel()
        # geler le message d’attente
        try:
            ch = interaction.channel
            if game.wait_msg_id:
                m = await ch.fetch_message(game.wait_msg_id)
                frozen = discord.Embed(
                    title="👥 Joueur rejoint",
                    description=(
                        f"🎮 Duel : **{duel_human_name(game.duel_type or '')}**\n"
                        f"👤 Créateur : <@{game.starter_id}> ({game.starter_choice})\n"
                        f"🧑‍🤝‍🧑 Adversaire : <@{user_id}> ({game.choice_joiner})\n"
                        f"💵 Mise : **{fmt_kamas(game.bet)}** kamas"
                    ),
                    color=COLOR_GOLD
                )
                if THUMB_URL:
                    frozen.set_thumbnail(url=THUMB_URL)
                await m.edit(embed=frozen, view=None)
        except Exception:
            pass

        mention_text, allowed = resolve_croupier_mention(interaction.guild)
        desc = (
            f"🎮 Duel : **{duel_human_name(game.duel_type or '')}**\n"
            f"👥 <@{game.starter_id}> → **{game.starter_choice}**  vs  <@{game.joiner_id}> → **{game.choice_joiner}**\n"
            f"💵 Mise : **{fmt_kamas(game.bet)}** kamas (par joueur)\n"
        )
        embed = discord.Embed(title="🎩 Appel CROUPIER", description=desc, color=COLOR_GOLD)
        if THUMB_URL:
            embed.set_thumbnail(url=THUMB_URL)

        await interaction.followup.send(
            content=mention_text,
            embed=embed,
            view=CroupierView(game),
            allowed_mentions=allowed
        )
        return

    # 2) Lobby existe mais créateur n’a pas fini config
    open_unset = [
        g for g in active_games.get(channel_id, [])
        if g.joiner_id is None and g.starter_id != user_id and (g.duel_type is None or g.starter_choice is None)
    ]
    if open_unset:
        return await interaction.followup.send("⏳ Le créateur configure la partie (duel/camp)… réessaie dans quelques instants.")

    # 3) Créer un lobby (créateur)
    if mise is None or mise <= 0:
        return await interaction.followup.send("Indique une **mise positive** pour créer la partie (ex: /roulette mise:100).")

    game = RouletteGame(channel_id=channel_id, starter_id=user_id, bet=mise)
    active_games.setdefault(channel_id, []).append(game)

    embed = discord.Embed(
        title="🎲 Roulette – Choisis le type de duel",
        description=(
            f"Créateur : <@{user_id}>\n"
            f"💵 Mise : **{fmt_kamas(mise)}** kamas par joueur\n\n"
            "Choisis : **rouge/noir**, **pair/impair**, ou **1-18/19-36**.\n"
            "(Tu as 5 min pour choisir, sinon la partie s'annule)"
        ),
        color=COLOR_GOLD
    )
    if THUMB_URL:
        embed.set_thumbnail(url=THUMB_URL)

    sent = await interaction.followup.send(embed=embed, view=DuelSelectionView(game))
    game.lobby_msg_id = sent.id

    async def duel_timeout():
        await asyncio.sleep(300)
        if (game.duel_type is None or game.starter_choice is None) and game.joiner_id is None:
            channel = interaction.channel
            await channel.send(f"⏳ Temps écoulé — configuration incomplète par <@{user_id}>. Partie annulée.")
            try:
                active_games[channel_id].remove(game)
                if not active_games[channel_id]:
                    active_games.pop(channel_id, None)
            except Exception:
                pass

    bot.loop.create_task(duel_timeout())

# ---------- Slash Leaderboard ----------
@bot.tree.command(name="lb_set_channel", description="(Admin) Définir le canal du leaderboard auto (serveur)")
@app_commands.describe(channel="Canal texte où afficher/épinger le leaderboard")
async def lb_set_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("⛔ Réservé aux administrateurs.", ephemeral=True)
    await interaction.response.defer(ephemeral=True, thinking=False)
    await asyncio.to_thread(_set_leaderboard_channel, interaction.guild.id, channel.id)
    await interaction.followup.send(f"✅ Canal du leaderboard défini sur {channel.mention}.")
    await update_leaderboard_message(interaction.guild)

@bot.tree.command(name="leaderboard", description="Afficher le leaderboard du serveur (depuis la base)")
@app_commands.describe(top="Nombre de joueurs à afficher (par défaut 10)")
async def leaderboard_cmd(interaction: discord.Interaction, top: Optional[int] = 10):
    if top is None or top <= 0:
        top = 10
    rows, total_all = await asyncio.to_thread(_format_leaderboard_rows, interaction.guild.id, min(top, 25))
    embed = _leaderboard_embed(interaction.guild, rows, total_all)
    await interaction.response.send_message(embed=embed)

# ---------- Démarrage ----------
@bot.event
async def on_ready():
    db_init()
    try:
        await bot.tree.sync()
    except Exception as e:
        print("Sync error:", e)
    print(f"Connecté en tant que {bot.user} (ID: {bot.user.id})")

if __name__ == "__main__":
    bot.run(TOKEN)
