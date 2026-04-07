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

@bot.event
async def on_ready():
    print(f"Bot connecté en tant que {bot.user}")

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