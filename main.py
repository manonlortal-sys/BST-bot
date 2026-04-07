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

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # Charger les cogs avant la connexion
        await self.load_extension("cogs.combat")
        # Synchronisation globale des commandes slash
        await self.tree.sync()
        print("✅ Cogs chargés et commandes slash synchronisées")

bot = MyBot()

@bot.event
async def on_ready():
    print(f"Bot connecté en tant que {bot.user}")

# ---------------------------
# Lancement Flask + Discord
# ---------------------------
if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    bot.run(os.environ["DISCORD_TOKEN"])