# --- Keep-alive Flask (Render Web Service) ---
from flask import Flask
from threading import Thread
import os

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running!"

def run():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

Thread(target=run, daemon=True).start()

# --- Discord bot (slash only) ---
import discord
from discord.ext import commands

intents = discord.Intents.default()
intents.guilds = True
intents.reactions = True  # utile pour le bot de ping
# pas de message_content / pas de members

bot = commands.Bot(command_prefix="!", intents=intents)

INITIAL_COGS = ["cogs.roulette", "cogs.ping"]
TEST_GUILD_ID = int(os.getenv("TEST_GUILD_ID", "0"))  # mets l’ID de TON serveur pour sync instantané

@bot.event
async def setup_hook():
    # charge les cogs
    for ext in INITIAL_COGS:
        try:
            await bot.load_extension(ext)
            print(f"[OK] Loaded {ext}")
        except Exception as e:
            print(f"[ERR] {ext} -> {e}")

    # sync slash (par serveur si possible = immédiat)
    try:
        if TEST_GUILD_ID:
            await bot.tree.sync(guild=discord.Object(id=TEST_GUILD_ID))
            print(f"Slash synced to guild {TEST_GUILD_ID}")
        else:
            synced = await bot.tree.sync()
            print(f"Globally synced {len(synced)} commands (peut prendre quelques minutes)")
    except Exception as e:
        print(f"Sync error: {e}")

@bot.event
async def on_ready():
    print(f"✅ Connecté en tant que {bot.user} (ID: {bot.user
