import os
import discord
from discord.ext import commands
from flask import Flask
from threading import Thread

# -------------------------
# Flask keep-alive (Render)
# -------------------------
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is alive!"

def run_web():
    app.run(host="0.0.0.0", port=10000)

# -------------------------
# Discord Bot
# -------------------------
TOKEN = os.getenv("DISCORD_TOKEN")
TEST_GUILD_ID = int(os.getenv("TEST_GUILD_ID", "0"))  # facultatif

intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def setup_hook():
    # Charger les cogs
    await bot.load_extension("cogs.roulette")
    await bot.load_extension("cogs.ping")

    try:
        if TEST_GUILD_ID:  # sync rapide sur serveur de test
            await bot.tree.sync(guild=discord.Object(id=TEST_GUILD_ID))
            print(f"Slash commands synced to test guild {TEST_GUILD_ID}")
        else:  # sync globale (multi-serveurs)
            await bot.tree.sync()
            print("Slash commands globally synced")
    except Exception as e:
        print(f"Sync error: {e}")
        
from cogs.ping import PingButtonsView  # import la classe
bot.add_view(PingButtonsView())        # ré-attache les callbacks au boot

@bot.event
async def on_ready():
    print(f"✅ Connecté en tant que {bot.user} (ID: {bot.user.id})")

if __name__ == "__main__":
    # lancer Flask keep-alive
    Thread(target=run_web).start()
    # lancer le bot
    bot.run(TOKEN)
