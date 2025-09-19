import os
import threading
from flask import Flask

import discord
from discord.ext import commands

# ========= Flask keep-alive (Render) =========
app = Flask(__name__)

@app.get("/")
def home():
    return "Bot actif"

def run_flask():
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_flask, daemon=True).start()

# ========= Discord setup =========
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise SystemExit("Missing DISCORD_TOKEN environment variable.")

# Facultatif: liste d'IDs de serveurs pour sync ciblée ("123,456")
_gids = os.getenv("GUILD_IDS", "").strip()
GUILD_IDS = [int(x) for x in _gids.split(",") if x.strip().isdigit()] if _gids else []

LEADERBOARD_CHANNEL_ID = int(os.getenv("LEADERBOARD_CHANNEL_ID", "0"))

intents = discord.Intents.default()
intents.guilds = True
intents.members = True  # nécessaire pour afficher les noms des joueurs

bot = commands.Bot(command_prefix="!", intents=intents)  # command_prefix ignoré pour slashs

@bot.event
async def setup_hook():
    # ========= Charger les views persistantes =========
    try:
        from cogs.ping import PingButtonsView
        bot.add_view(PingButtonsView())
    except Exception as e:
        print("Warning: unable to register persistent views:", e)

    # ========= Charger les cogs =========
    try:
        await bot.load_extension("cogs.ping")
        await bot.load_extension("cogs.roulette")
    except Exception as e:
        print("Error loading cogs:", e)

    # ========= Sync des commandes slash =========
    try:
        if GUILD_IDS:
            for gid in GUILD_IDS:
                await bot.tree.sync(guild=discord.Object(id=gid))
                print(f"Synced app commands for guild {gid}")
        else:
            await bot.tree.sync()
            print("Synced global app commands")
    except Exception as e:
        print("Slash sync error:", e)

@bot.event
async def on_ready():
    print(f"Connecté en tant que {bot.user} (ID: {bot.user.id})")
    # Créer le message leaderboard si nécessaire
    if LEADERBOARD_CHANNEL_ID:
        channel = bot.get_channel(LEADERBOARD_CHANNEL_ID)
        if channel:
            try:
                # Vérifie s’il existe déjà un message, sinon créer un message vide pour les leaderboards
                messages = await channel.history(limit=10).flatten()
                if not any("Leaderboard" in (m.content or "") for m in messages):
                    await channel.send("📊 **Leaderboard initialisé**")
            except Exception as e:
                print("Erreur création message leaderboard :", e)

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
