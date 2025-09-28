import os
import threading
from flask import Flask
import discord
from discord.ext import commands

from storage import create_db, upsert_guild_config

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

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def setup_hook():
    print("🚀 setup_hook démarré")

    for ext in ["cogs.alerts", "cogs.reactions", "cogs.leaderboard", "cogs.stats", "cogs.snapshots"]:
        try:
            await bot.load_extension(ext)
            print(f"✅ {ext} chargé")
        except Exception as e:
            print(f"❌ Erreur chargement {ext} :", e)

    try:
        from cogs.alerts import PingButtonsView
        bot.add_view(PingButtonsView(bot))
        print("✅ View PingButtonsView persistante enregistrée")
    except Exception as e:
        print("❌ Erreur enregistrement View PingButtonsView :", e)

    try:
        await bot.tree.sync()
        print("✅ Slash commands sync (global)")
    except Exception as e:
        print("❌ Slash sync error :", e)

@bot.event
async def on_ready():
    print(f"✅ Connecté en tant que {bot.user} (ID: {bot.user.id})")

    try:
        for g in bot.guilds:
            await bot.tree.sync(guild=discord.Object(id=g.id))
        print("✅ Slash commands synced per guild")
    except Exception as e:
        print("❌ Per-guild slash sync error:", e)

if __name__ == "__main__":
    print("⚡ Démarrage du bot...")
    try:
        create_db()
        # Insert ta config actuelle
        upsert_guild_config(
            guild_id=1280396795046006836,  # ⚠️ remplace par ton vrai guild_id
            alert_channel_id=1327548733398843413,
            leaderboard_channel_id=1419025350641582182,
            snapshot_channel_id=1421100876977803274,
            role_def_id=1326671483455537172,
            role_def2_id=1328097429525893192,
            role_test_id=1358771105980088390,
            admin_role_id=1280396795046006836
        )
        print("✅ DB vérifiée/initialisée avec config serveur")
    except Exception as e:
        print("⚠️ Impossible d'initialiser la DB :", e)

    bot.run(DISCORD_TOKEN)
