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

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.reactions = True  # nécessaire pour on_raw_reaction_add/remove

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def setup_hook():
    print("🚀 setup_hook démarré")

    # Charger les cogs
    for ext in ["cogs.alerts", "cogs.reactions", "cogs.leaderboard", "cogs.stats", "cogs.deletions", "cogs.snapshots"]:
        try:
            await bot.load_extension(ext)
            print(f"✅ {ext} chargé")
        except Exception as e:
            print(f"❌ Erreur chargement {ext} :", e)

    # View persistante pour les anciens panneaux postés
    try:
        from cogs.alerts import PingButtonsView
        bot.add_view(PingButtonsView(bot))
        print("✅ View PingButtonsView persistante enregistrée")
    except Exception as e:
        print("❌ Erreur enregistrement View PingButtonsView :", e)

    # Sync globale (peut prendre du temps à apparaître côté Discord)
    try:
        await bot.tree.sync()
        print("✅ Slash commands sync (global)")
    except Exception as e:
        print("❌ Slash sync error :", e)

@bot.event
async def on_ready():
    print(f"✅ Connecté en tant que {bot.user} (ID: {bot.user.id})")

    # 🔁 Sync par serveur pour rendre les slash visibles immédiatement (ex: /stats)
    try:
        for g in bot.guilds:
            await bot.tree.sync(guild=discord.Object(id=g.id))
        print("✅ Slash commands synced per guild")
    except Exception as e:
        print("❌ Per-guild slash sync error:", e)

    # (optionnel) Logs pour vérifier ce que Discord voit réellement
    try:
        cmds = [c.name for c in bot.tree.get_commands()]
        print("🌲 Global commands:", cmds)
        for g in bot.guilds:
            gcmds = [c.name for c in bot.tree.get_commands(guild=discord.Object(id=g.id))]
            print(f"🌲 Guild {g.id} commands:", gcmds)
    except Exception as e:
        print("🌲 Unable to list commands:", e)

    if LEADERBOARD_CHANNEL_ID:
        channel = bot.get_channel(LEADERBOARD_CHANNEL_ID)
        if channel:
            try:
                # Juste un message d'initialisation si rien
                async for m in channel.history(limit=10):
                    break
                else:
                    await channel.send("📊 **Leaderboard initialisé**")
            except Exception as e:
                print("❌ Erreur init leaderboard :", e)

if __name__ == "__main__":
    print("⚡ Démarrage du bot...")
    # Init DB
    try:
        from storage import create_db
        create_db()
        print("✅ DB vérifiée/initialisée")
    except Exception as e:
        print("⚠️ Impossible d'initialiser la DB au démarrage :", e)

    bot.run(DISCORD_TOKEN)
