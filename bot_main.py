import os
import threading
from flask import Flask
import discord
from discord.ext import commands

# ========= Flask keep-alive =========
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

# ---------- Intents ----------
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ========= Setup Hook =========
@bot.event
async def setup_hook():
    print("🚀 setup_hook démarré")

    # Charger les cogs
    for cog in ["cogs.panel", "cogs.alerts", "cogs.leaderboard"]:
        try:
            await bot.load_extension(cog)
            print(f"✅ {cog} chargé")
        except Exception as e:
            print(f"❌ Erreur chargement {cog} :", e)

    # Synchronisation des slash commands (globale)
    try:
        await bot.tree.sync()
        print("✅ Global slash commands sync (may take up to 1 hour to appear)")
    except Exception as e:
        print("❌ Slash sync error :", e)

@bot.event
async def on_ready():
    print(f"✅ Connecté en tant que {bot.user} (ID: {bot.user.id})")

if __name__ == "__main__":
    print("⚡ Démarrage du bot...")

    # Initialisation DB avant lancement du bot
    from storage import create_db
    create_db()

    bot.run(DISCORD_TOKEN)
