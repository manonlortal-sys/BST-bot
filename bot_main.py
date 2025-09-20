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

# Liste d'IDs de serveurs pour sync ciblée ("123,456")
_gids = os.getenv("GUILD_IDS", "").strip()
GUILD_IDS = [int(x) for x in _gids.split(",") if x.strip().isdigit()] if _gids else []

LEADERBOARD_CHANNEL_ID = int(os.getenv("LEADERBOARD_CHANNEL_ID", "0"))

# ---------- Intents ----------
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- Liste des cogs ----------
COGS = ["cogs.ping", "cogs.roulette"]

# ========= Setup Hook =========
@bot.event
async def setup_hook():
    print("🚀 setup_hook démarré")
    
    # Charger les cogs
    for cog in COGS:
        try:
            await bot.load_extension(cog)
            print(f"✅ Cog {cog.split('.')[-1]} chargé")
        except Exception as e:
            print(f"❌ Erreur chargement {cog} :", e)

    # Synchroniser les commandes slash
    try:
        if GUILD_IDS:
            for gid in GUILD_IDS:
                await bot.tree.sync(guild=discord.Object(id=gid))
                print(f"✅ Slash commands sync pour guild {gid}")
        else:
            await bot.tree.sync()
            print("✅ Slash commands sync globale")
    except Exception as e:
        print("❌ Slash sync error :", e)

# ========= Ready Event =========
@bot.event
async def on_ready():
    print(f"✅ Connecté en tant que {bot.user} (ID: {bot.user.id})")

if __name__ == "__main__":
    print("⚡ Démarrage du bot...")
    bot.run(DISCORD_TOKEN)
