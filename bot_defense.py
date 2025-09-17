# =========================
#  Bot Défense + Roulette – Discord
#  (Render Web Service)
# =========================

# --- Réglages pour Render/Matplotlib (headless) ---
import os
os.environ.setdefault("MPLBACKEND", "Agg")

# --- Imports standard ---
import io
import threading
import random
import asyncio
from dataclasses import dataclass
from typing import Optional, Dict, List
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# --- Discord & Flask ---
import discord
from discord import app_commands
from discord.ext import commands
from flask import Flask

# --- Matplotlib (pour les graphs) ---
import matplotlib.pyplot as plt
from dotenv import load_dotenv

# =========================
#  Mini serveur HTTP (Web Service)
#  -> occupe le port $PORT exigé par Render
# =========================
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot Discord actif"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# Lance Flask en arrière-plan
threading.Thread(target=run_flask, daemon=True).start()

# =========================
#  Constantes / Intents
# =========================
CHANNEL_ID = 1327548733398843413  # <-- remplace si besoin
LOCAL_TZ = "Europe/Paris"

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Intents (préfixe -> besoin de message_content=True)
intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.reactions = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# --------- CONFIG visuelle pour Roulette ---------
SPIN_GIF_URL = os.getenv("SPIN_GIF_URL", "https://media.tenor.com/e3QG3W1u3lAAAAAC/roulette-casino.gif")
THUMB_URL = os.getenv("THUMB_URL", "")

COLOR_RED = 0xE74C3C
COLOR_BLACK = 0x2C3E50
COLOR_GREEN = 0x2ECC71
COLOR_GOLD = 0xF1C40F

RED_NUMBERS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}

# =========================
#  Roulette
# =========================
@dataclass
class RouletteGame:
    channel_id: int
    starter_id: int
    bet: int = 0
    joiner_id: Optional[int] = None
    duel_type: Optional[str] = None           # "couleur" | "parité" | "intervalle"
    choice_joiner: Optional[str] = None       # camp choisi par le joiner
    lobby_msg_id: Optional[int] = None
    spin_msg_id: Optional[int] = None

# mapping des libellés pour les boutons selon le duel
DUEL_LABELS: dict[str, list[tuple[str, str]]] = {
    "couleur":    [("🔴 Rouge", "rouge"), ("⚫ Noir", "noir")],
    "parité":     [("🟦 Pair", "pair"), ("🟪 Impair", "impair")],
    "intervalle": [("⬇️ 1–18", "1-18"), ("⬆️ 19–36", "19-36")],
}

def duel_human_name(mode: str) -> str:
    return {"couleur":"Couleur (Rouge/Noir)", "parité":"Pair/Impair", "intervalle":"1–18 / 19–36"}.get(mode, mode)

# calcule l'étiquette gagnante selon le mode
def result_label(mode: str, n: int) -> Optional[str]:
    if mode == "couleur":
        if n == 0:
            return None
        return "rouge" if n in RED_NUMBERS else "noir"
    if mode == "parité":
        return "pair" if n % 2 == 0 else "impair"  # 0 est pair
    if mode == "intervalle":
        if 1 <= n <= 18:
            return "1-18"
        if 19 <= n <= 36:
            return "19-36"
        return None
    return None

active_games: Dict[int, List[RouletteGame]] = {}

class DuelSelectionView(discord.ui.View):
    """Le créateur choisit le type de duel via 3 boutons."""
    def __init__(self, game: RouletteGame, *, timeout: float = 300.0):
        super().__init__(timeout=timeout)
        self.game = game
        # Boutons: Couleur, Pair/Impair, 1–18/19–36
        self.add_item(discord.ui.Button(label="Couleur (Rouge/Noir)", style=discord.ButtonStyle.primary, custom_id="duel_couleur"))
        self.add_item(discord.ui.Button(label="Pair / Impair", style=discord.ButtonStyle.secondary, custom_id="duel_parite"))
        self.add_item(discord.ui.Button(label="1–18 / 19–36", style=discord.ButtonStyle.success, custom_id="duel_intervalle"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.game.starter_id:
            await interaction.response.send_message("⛔ Seul le créateur peut choisir le type de duel.", ephemeral=True)
            return False
        return True

    async def on_button(self, interaction: discord.Interaction, duel_type: str):
        # Fixe le duel, désactive les boutons
        self.game.duel_type = duel_type
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

        labels = " / ".join(lbl for lbl, _ in DUEL_LABELS.get(duel_type, []))
        embed = discord.Embed(
            title="🎲 Roulette – Lobby ouvert",
            description=(
                f"Créateur : <@{self.game.starter_id}>
"
                f"🎮 Duel : **{duel_human_name(duel_type)}** ({labels})
"
                f"💵 Mise : **{self.game.bet}** kamas

"
                f"➡️ Un joueur a **5 minutes** pour rejoindre ici avec **/roulette**."
            ),
            color=COLOR_GOLD
        )
        if THUMB_URL: embed.set_thumbnail(url=THUMB_URL)
        await interaction.response.edit_message(embed=embed, view=self)

        # Démarre le timeout de lobby (5 min pour qu'un joueur rejoigne)
        channel = interaction.channel
        async def lobby_timeout():
            await asyncio.sleep(300)
            if self.game.joiner_id is None:
                await channel.send(f"⏳ Lobby expiré (créé par <@{self.game.starter_id}>).")
                try:
                    active_games[self.game.channel_id].remove(self.game)
                    if not active_games[self.game.channel_id]:
                        active_games.pop(self.game.channel_id, None)
                except Exception:
                    pass
        self.game.lobby_task = bot.loop.create_task(lobby_timeout())

    @discord.ui.button(label="Couleur (Rouge/Noir)", style=discord.ButtonStyle.primary, row=0)
    async def _b_couleur(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.on_button(interaction, "couleur")

    @discord.ui.button(label="Pair / Impair", style=discord.ButtonStyle.secondary, row=0)
    async def _b_parite(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.on_button(interaction, "parité")

    @discord.ui.button(label="1–18 / 19–36", style=discord.ButtonStyle.success, row=0)
    async def _b_intervalle(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.on_button(interaction, "intervalle")

def spin_wheel():
    n = random.randint(0, 36)
    if n == 0:
        return n, "vert"
    return n, ("rouge" if n in RED_NUMBERS else "noir")

def color_for_embed(color: str) -> int:
    return COLOR_GREEN if color == "vert" else (COLOR_RED if color == "rouge" else COLOR_BLACK)

def add_game(game: RouletteGame):
    active_games.setdefault(game.channel_id, []).append(game)

def remove_game(game: RouletteGame):
    lst = active_games.get(game.channel_id, [])
    if game in lst:
        lst.remove(game)
    if not lst:
        active_games.pop(game.channel_id, None)

class SideChoiceView(discord.ui.View):
    """Le 2e joueur choisit son camp selon le duel choisi par le créateur."""
    def __init__(self, game: RouletteGame, *, timeout: float = 120.0):
        super().__init__(timeout=timeout)
        self.game = game
        labels = DUEL_LABELS.get(game.duel_type or "", [])
        if len(labels) != 2:
            labels = [("Option A","A"), ("Option B","B")]
        # bouton 1
        b1 = discord.ui.Button(label=labels[0][0], style=discord.ButtonStyle.primary)
        async def cb1(inter: discord.Interaction):
            await self._resolve(inter, labels[0][1])
        b1.callback = cb1
        self.add_item(b1)
        # bouton 2
        b2 = discord.ui.Button(label=labels[1][0], style=discord.ButtonStyle.secondary)
        async def cb2(inter: discord.Interaction):
            await self._resolve(inter, labels[1][1])
        b2.callback = cb2
        self.add_item(b2)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.game.joiner_id:
            await interaction.response.send_message("⛔ Seul le second joueur peut choisir.", ephemeral=True)
            return False
        return True

    async def _resolve(self, interaction: discord.Interaction, choice_joiner: str):
        self.game.choice_joiner = choice_joiner
        # Déterminer le camp du créateur (opposé)
        starter_choice = {
            ("couleur","rouge"): "noir",
            ("couleur","noir"): "rouge",
            ("parité","pair"): "impair",
            ("parité","impair"): "pair",
            ("intervalle","1-18"): "19-36",
            ("intervalle","19-36"): "1-18",
        }.get((self.game.duel_type, choice_joiner), "?")

        # Ping CROUPIER pour valider les mises
        mention = f"<@&{CROUPIER_ROLE_ID}>" if CROUPIER_ROLE_ID else f"**{CROUPIER_ROLE_NAME}**"
        desc = (
            f"{mention} — merci de **valider les mises**.

"
            f"🎮 Duel : **{duel_human_name(self.game.duel_type)}**
"
            f"👥 <@{self.game.starter_id}> → **{starter_choice}**  vs  <@{self.game.joiner_id}> → **{self.game.choice_joiner}**
"
            f"💵 Mise : **{self.game.bet}** kamas (par joueur)
"
        )
        embed = discord.Embed(title="🎩 Appel CROUPIER", description=desc, color=COLOR_GOLD)
        if THUMB_URL: embed.set_thumbnail(url=THUMB_URL)
        await interaction.response.edit_message(embed=embed, view=CroupierView(self.game))

class CroupierView(discord.ui.View):
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
                description=f"Créateur : <@{self.game.starter_id}> — Mise : {self.game.bet} kamas",
                color=COLOR_RED,
            ),
            view=None
        )

async def launch_spin(interaction: discord.Interaction, game: RouletteGame):
    base = (
        f"🎮 Duel : **{duel_human_name(game.duel_type)}**
"
        f"👥 <@{game.starter_id}> vs <@{game.joiner_id}>
"
        f"💵 Mise : **{game.bet}** kamas
"
    )
    spin = discord.Embed(title="🎰 SPIN EN COURS !", description=base + "⌛ La roue tourne... **5**", color=COLOR_GOLD)
    if THUMB_URL: spin.set_thumbnail(url=THUMB_URL)
    if SPIN_GIF_URL: spin.set_image(url=SPIN_GIF_URL)

    await interaction.response.edit_message(embed=spin, view=None)
    msg = await interaction.original_response()
    game.spin_msg_id = msg.id
    channel = interaction.channel

    for t in [4,3,2,1]:
        await asyncio.sleep(1)
        try:
            m = await channel.fetch_message(game.spin_msg_id)
            spin.description = base + f"⌛ La roue tourne... **{t}**"
            await m.edit(embed=spin)
        except:
            break
    await asyncio.sleep(1)

    attempts = 0
    while True:
        attempts += 1
        n, _color = spin_wheel()
        res = result_label(game.duel_type, n)
        if res is not None or attempts >= 3:
            break

    # Décide gagnant
    # Déduit le camp du créateur (opposé du choix joiner)
    starter_choice = {
        ("couleur","rouge"): "noir",
        ("couleur","noir"): "rouge",
        ("parité","pair"): "impair",
        ("parité","impair"): "pair",
        ("intervalle","1-18"): "19-36",
        ("intervalle","19-36"): "1-18",
    }.get((game.duel_type, game.choice_joiner or ""), "?")

    if res == starter_choice:
        winner, loser = game.starter_id, game.joiner_id
    elif res == (game.choice_joiner or ""):
        winner, loser = game.joiner_id, game.starter_id
    else:
        winner = loser = None

    color_emoji = ""
    if game.duel_type == "couleur":
        color_emoji = "🔴" if res == "rouge" else ("⚫" if res == "noir" else "🟢" if n == 0 else "")

    title = f"🏁 Résultat : {n} {color_emoji}"
    if winner:
        desc = (
            f"🎮 Duel : **{duel_human_name(game.duel_type)}**
"
            f"🏆 Gagnant : <@{winner}>  (+{game.bet} kamas)
"
            f"💤 Perdant : <@{loser}>   (-{game.bet} kamas)"
        )
        color = color_for_embed("rouge" if res == "rouge" else "noir" if res == "noir" else "vert")
    else:
        desc = (
            f"🎮 Duel : **{duel_human_name(game.duel_type)}**
"
            f"⚖️ Aucun gagnant (résultat neutre)."
        )
        color = COLOR_GOLD

    result = discord.Embed(title=title, description=desc, color=color)
    if THUMB_URL: result.set_thumbnail(url=THUMB_URL)
    try:
        m = await channel.fetch_message(game.spin_msg_id)
        await m.edit(embed=result, view=None)
    except:
        await channel.send(embed=result)

    try:
        active_games[game.channel_id].remove(game)
        if not active_games[game.channel_id]:
            active_games.pop(game.channel_id, None)
    except Exception:
        pass

@bot.tree.command(name="roulette", description="Créer/Rejoindre une roulette (mise en kamas)")
@app_commands.describe(mise="Montant à miser (en kamas, seulement pour créer la partie)")
async def roulette_cmd(interaction: discord.Interaction, mise: Optional[int] = None):
    channel_id = interaction.channel_id
    user_id = interaction.user.id

    # 1) Rejoindre un lobby déjà prêt (duel déjà choisi)
    open_ready = [g for g in active_games.get(channel_id, []) if g.joiner_id is None and g.duel_type is not None and g.starter_id != user_id]
    if open_ready:
        game = open_ready[0]
        game.joiner_id = user_id
        # Annule le timeout de lobby si existant
        if hasattr(game, "lobby_task") and game.lobby_task and not game.lobby_task.done():
            game.lobby_task.cancel()
        labels = " / ".join(lbl for lbl, _ in DUEL_LABELS.get(game.duel_type, []))
        embed = discord.Embed(
            title="👥 Joueur rejoint !",
            description=(
                f"🎮 Duel : **{duel_human_name(game.duel_type)}** ({labels})
"
                f"💵 Mise : **{game.bet}** kamas

"
                f"<@{user_id}>, choisis ton camp :"
            ),
            color=COLOR_GOLD
        )
        if THUMB_URL: embed.set_thumbnail(url=THUMB_URL)
        await interaction.response.send_message(embed=embed, view=SideChoiceView(game))
        sent = await interaction.original_response()
        game.lobby_msg_id = sent.id
        return

    # 2) Un lobby existe mais le duel n'est pas encore choisi -> on prévient
    open_unset = [g for g in active_games.get(channel_id, []) if g.joiner_id is None and g.duel_type is None and g.starter_id != user_id]
    if open_unset:
        return await interaction.response.send_message("⏳ Le créateur est en train de choisir le **type de duel**… Réessaie dans quelques secondes.", ephemeral=True)

    # 3) Créer un lobby (créateur) — il DOIT fournir une mise > 0, le duel sera choisi via boutons
    if mise is None or mise <= 0:
        return await interaction.response.send_message("Indique une **mise positive** pour créer la partie (ex: /roulette mise:100).", ephemeral=True)

    game = RouletteGame(channel_id=channel_id, starter_id=user_id, bet=mise, duel_type=None)
    active_games.setdefault(channel_id, []).append(game)

    embed = discord.Embed(
        title="🎲 Roulette – Choisis le type de duel",
        description=(
            f"Créateur : <@{user_id}>
"
            f"💵 Mise : **{mise}** kamas par joueur

"
            f"Choisis ci-dessous : **Couleur**, **Pair/Impair**, ou **1–18 / 19–36**.
"
            f"(Tu as 5 min pour choisir, sinon la partie s'annule)"
        ),
        color=COLOR_GOLD
    )
    if THUMB_URL: embed.set_thumbnail(url=THUMB_URL)

    view = DuelSelectionView(game)
    await interaction.response.send_message(embed=embed, view=view)
    sent = await interaction.original_response()
    game.lobby_msg_id = sent.id

    async def duel_timeout():
        await asyncio.sleep(300)
        if game.duel_type is None and game.joiner_id is None:
            channel = interaction.channel
            await channel.send(f"⏳ Temps écoulé — duel non choisi par <@{user_id}>. Partie annulée.")
            # Retire le message si souhaité :
            # try:
            #     m = await channel.fetch_message(game.lobby_msg_id)
            #     await m.edit(view=None)
            # except:
            #     pass
            try:
                active_games[channel_id].remove(game)
                if not active_games[channel_id]:
                    active_games.pop(channel_id, None)
            except Exception:
                pass

    bot.loop.create_task(duel_timeout())

# =========================
#  Fonctions existantes (défenses…)
# =========================
# ... (reprends ici tes commandes defstats, liste, alliance, alliances7j, graphic)

# =========================
#  Démarrage
# =========================
@bot.event
async def on_ready():
    try:
        await bot.tree.sync()
    except Exception as e:
        print("Sync error:", e)
    print(f"Connecté en tant que {bot.user}")

if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN manquant")
    bot.run(TOKEN)
