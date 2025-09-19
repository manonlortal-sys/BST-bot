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

intents = discord.Intents.default()
intents.guilds = True

# --- Changement minimal pour slash-only ---
bot = commands.Bot(command_prefix=None, intents=intents)  # plus de "!" puisque slash-only

@bot.event
async def setup_hook():
    # IMPORTANT: enregistrer la vue persistante pour les boutons déjà envoyés avant un reboot
    try:
        from cogs.ping import PingButtonsView
        bot.add_view(PingButtonsView())
    except Exception as e:
        print("Warning: unable to register persistent views:", e)

    # Charger les cogs
    await bot.load_extension("cogs.ping")  # garde ton cog ping intact
    await bot.load_extension("cogs.roulette")  # on ajoute ton cog roulette

    # Sync des commandes slash (scope ciblé si GUILD_IDS fournis)
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
