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
    choice: Optional[str] = None  # "rouge" | "noir"
    lobby_msg_id: Optional[int] = None
    spin_msg_id: Optional[int] = None

active_games: Dict[int, List[RouletteGame]] = {}

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

class ChoiceView(discord.ui.View):
    def __init__(self, game: RouletteGame, *, timeout: float = 45.0):
        super().__init__(timeout=timeout)
        self.game = game

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.game.starter_id:
            await interaction.response.send_message("Seul le créateur de la partie peut choisir.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Rouge", style=discord.ButtonStyle.danger, emoji="🔴")
    async def btn_rouge(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.resolve(interaction, "rouge")

    @discord.ui.button(label="Noir", style=discord.ButtonStyle.secondary, emoji="⚫")
    async def btn_noir(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.resolve(interaction, "noir")

    async def resolve(self, interaction: discord.Interaction, choice: str):
        self.game.choice = choice
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

        desc_base = (f"👥 Joueurs : <@{self.game.starter_id}> vs <@{self.game.joiner_id}>\n"
                     f"🎯 Choix : **{choice.upper()}**\n"
                     f"💵 Mise : **{self.game.bet} kamas**\n")

        spin_embed = discord.Embed(title="🎰 SPIN EN COURS !", description=desc_base + "⌛ La roue tourne... **5**", color=COLOR_GOLD)
        if THUMB_URL:
            spin_embed.set_thumbnail(url=THUMB_URL)
        if SPIN_GIF_URL:
            spin_embed.set_image(url=SPIN_GIF_URL)

        await interaction.response.edit_message(embed=spin_embed, view=self)
        msg = await interaction.original_response()
        self.game.spin_msg_id = msg.id

        # compte à rebours
        channel = interaction.channel
        for t in [4,3,2,1]:
            await asyncio.sleep(1)
            try:
                m = await channel.fetch_message(self.game.spin_msg_id)
                spin_embed.description = desc_base + f"⌛ La roue tourne... **{t}**"
                await m.edit(embed=spin_embed, view=self)
            except:
                break
        await asyncio.sleep(1)

        n, color = spin_wheel()
        winner = self.game.starter_id if color == choice else self.game.joiner_id
        loser = self.game.joiner_id if winner == self.game.starter_id else self.game.starter_id
        color_emoji = "🔴" if color == "rouge" else ("⚫" if color == "noir" else "🟢")

        result_embed = discord.Embed(title=f"🏁 Résultat : {n} {color_emoji}",
                                     description=f"🏆 Gagnant : <@{winner}> +{self.game.bet} kamas\n"
                                                 f"💤 Perdant : <@{loser}> -{self.game.bet} kamas",
                                     color=color_for_embed(color))
        if THUMB_URL:
            result_embed.set_thumbnail(url=THUMB_URL)

        try:
            m = await channel.fetch_message(self.game.spin_msg_id)
            await m.edit(embed=result_embed, view=None)
        except:
            await channel.send(embed=result_embed)

        remove_game(self.game)

@bot.tree.command(name="roulette", description="Créer/Rejoindre une roulette à 2 joueurs (mise en kamas)")
@app_commands.describe(mise="Montant à miser (en kamas)")
async def roulette_cmd(interaction: discord.Interaction, mise: Optional[int] = 0):
    if mise is None:
        mise = 0
    if mise < 0:
        return await interaction.response.send_message("La mise ne peut pas être négative.", ephemeral=True)

    channel_id = interaction.channel_id
    user_id = interaction.user.id

    open_lobbies = [g for g in active_games.get(channel_id, []) if g.joiner_id is None and g.starter_id != user_id]

    if open_lobbies:
        game = open_lobbies[0]
        game.joiner_id = user_id
        view = ChoiceView(game)

        embed = discord.Embed(title="👥 Joueur rejoint !",
                              description=f"<@{game.starter_id}> vs <@{game.joiner_id}>\n💵 Mise : {game.bet} kamas",
                              color=COLOR_GOLD)
        await interaction.response.send_message(embed=embed, view=view)
        sent = await interaction.original_response()
        game.lobby_msg_id = sent.id
        return

    game = RouletteGame(channel_id=channel_id, starter_id=user_id, bet=mise)
    add_game(game)

    embed = discord.Embed(title="🎲 Roulette – Lobby ouvert",
                          description=f"Créateur : <@{user_id}>\n💵 Mise : {mise} kamas\n➡️ Un joueur a 5 min pour rejoindre avec /roulette",
                          color=COLOR_GOLD)
    await interaction.response.send_message(embed=embed)
    sent = await interaction.original_response()
    game.lobby_msg_id = sent.id

    async def lobby_timeout():
        await asyncio.sleep(300)
        if game.joiner_id is None:
            channel = interaction.channel
            await channel.send(f"⏳ Lobby expiré (créé par <@{user_id}>).")
            remove_game(game)
    bot.loop.create_task(lobby_timeout())

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
