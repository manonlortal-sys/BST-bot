# main.py

from flask import Flask
import threading
import discord
from discord.ext import commands
import os

# ---------------------------
# Flask pour Render
# ---------------------------
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot Discord actif ✅"

def run_flask():
    app.run(host="0.0.0.0", port=8080)

# ---------------------------
# Discord Bot
# ---------------------------
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------------------
# ID serveur pour sync immédiate
# ---------------------------
GUILD_ID = 123456789012345678  # Remplace par ton ID de serveur Discord

# ---------------------------
# Events
# ---------------------------
@bot.event
async def on_ready():
    print(f"Bot connecté en tant que {bot.user}")
    # Synchronisation des commandes slash pour ton serveur
    try:
        guild = discord.Object(id=GUILD_ID)
        await bot.tree.sync(guild=guild)
        print("✅ Commandes slash synchronisées pour le serveur")
    except Exception as e:
        print(f"❌ Erreur sync commandes: {e}")

# ---------------------------
# Charger les cogs
# ---------------------------
async def load_cogs():
    await bot.load_extension("cogs.combat")

# ---------------------------
# Lancement Flask + Discord
# ---------------------------
if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    bot.loop.create_task(load_cogs())
    bot.run(os.environ["DISCORD_TOKEN"])