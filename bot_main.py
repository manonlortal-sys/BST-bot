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

LEADERBOARD_CHANNEL_ID = int(os.getenv("LEADERBOARD_CHANNEL_ID", "0"))

# ---------- Intents ----------
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.reactions = True
# message_content pas nécessaire pour ton bot

bot = commands.Bot(command_prefix="!", intents=intents)

# ========= Setup Hook =========
@bot.event
async def setup_hook():
    print("🚀 setup_hook démarré")

    # Charger les cogs
    for ext in ["cogs.panel", "cogs.alerts", "cogs.leaderboard", "cogs.reactions"]:
        try:
            await bot.load_extension(ext)
            print(f"✅ {ext} chargé")
        except Exception as e:
            print(f"❌ Erreur chargement {ext} :", e)

    # Sync global des slashs
    try:
        await bot.tree.sync()
        print("✅ Slash commands sync (global)")
    except Exception as e:
        print("❌ Slash sync error :", e)

@bot.event
async def on_ready():
    print(f"✅ Connecté en tant que {bot.user} (ID: {bot.user.id})")

    if LEADERBOARD_CHANNEL_ID:
        channel = bot.get_channel(LEADERBOARD_CHANNEL_ID)
        if channel:
            try:
                messages = []
                async for m in channel.history(limit=10):
                    messages.append(m)

                if not any("Leaderboard" in (m.content or "") for m in messages):
                    await channel.send("📊 **Leaderboard initialisé**")
            except Exception as e:
                print("❌ Erreur création message leaderboard :", e)

if __name__ == "__main__":
    print("⚡ Démarrage du bot...")
    bot.run(DISCORD_TOKEN)
