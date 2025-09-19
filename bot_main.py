import os
import threading
from flask import Flask
import discord
from discord.ext import commands
import importlib
import pathlib

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

# Guild IDs pour sync ciblée (optionnel)
_gids = os.getenv("GUILD_IDS", "").strip()
GUILD_IDS = [int(x) for x in _gids.split(",") if x.strip().isdigit()] if _gids else []

# Intents minimalistes pour slash commands
intents = discord.Intents.default()
intents.guilds = True

# Bot sans préfixe, uniquement slash commands
bot = commands.Bot(command_prefix=None, intents=intents)

@bot.event
async def setup_hook():
    # 1) Enregistrer les vues persistantes (ex: PingButtonsView)
    try:
        from cogs.ping import PingButtonsView
        bot.add_view(PingButtonsView())
    except Exception as e:
        print("Warning: unable to register persistent views:", e)

    # 2) Charger automatiquement tous les cogs dans le dossier cogs/
    cogs_path = pathlib.Path("cogs")
    for file in cogs_path.glob("*.py"):
        if file.name.startswith("_"):  # ignorer __init__.py ou fichiers privés
            continue
        cog_name = f"cogs.{file.stem}"
        try:
            await bot.load_extension(cog_name)
            print(f"Loaded cog: {cog_name}")
        except Exception as e:
            print(f"Failed to load cog {cog_name}: {e}")

    # 3) Synchroniser les slash commands
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

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
