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
# note: message_content n'est pas nécessaire pour lire les attachments

bot = commands.Bot(command_prefix="!", intents=intents)

# ========= Setup Hook avec logs =========
@bot.event
async def setup_hook():
    print("🚀 setup_hook démarré")

    # Charger le cog Ping
    try:
        await bot.load_extension("cogs.ping")
        print("✅ Cog Ping chargé")
    except Exception as e:
        print("❌ Erreur chargement PingCog :", e)

    # Charger le cog Roulette si présent
    try:
        await bot.load_extension("cogs.roulette")
        print("✅ Cog Roulette chargé")
    except Exception as e:
        print("❌ Erreur chargement Roulette :", e)

    # Charger le cog OCR + leaderboard AVANT la sync des slashs
    try:
        await bot.load_extension("cogs.ocr_leaderboard")
        print("✅ Cog OCR + Leaderboard chargé")
    except Exception as e:
        print("❌ Erreur chargement OCR + Leaderboard :", e)

    # Synchronisation des slash commands
    try:
        # Pour tests rapides : définis TEST_GUILD_ID en variable d'env pour synchroniser localement
        TEST_GUILD_ID = int(os.getenv("TEST_GUILD_ID", "0"))
        if TEST_GUILD_ID:
            await bot.tree.sync(guild=discord.Object(id=TEST_GUILD_ID))
            print("✅ Slash commands synced to guild", TEST_GUILD_ID)
        else:
            await bot.tree.sync()
            print("✅ Global slash commands sync (may take up to 1 hour to appear)")
    except Exception as e:
        print("❌ Slash sync error :", e)

@bot.event
async def on_ready():
    print(f"✅ Connecté en tant que {bot.user} (ID: {bot.user.id})")

    if LEADERBOARD_CHANNEL_ID:
        channel = bot.get_channel(LEADERBOARD_CHANNEL_ID)
        if channel:
            try:
                # récupération des derniers messages sans utiliser .flatten()
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
