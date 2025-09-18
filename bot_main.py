import os
import discord
from discord.ext import commands

# --- Mini serveur keep-alive pour Render ---
from flask import Flask
from threading import Thread
import os

app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

Thread(target=run).start()

# --- Intents ---
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.reactions = True

# --- Bot ---
bot = commands.Bot(command_prefix="!", intents=intents)

# --- Liste des cogs à charger ---
initial_cogs = ["cogs.roulette", "cogs.ping"]

@bot.event
async def on_ready():
    print(f"✅ Connecté en tant que {bot.user} (ID: {bot.user.id})")
    print("📦 Cogs chargés :", initial_cogs)

# Charger les cogs
for cog in initial_cogs:
    try:
        bot.load_extension(cog)
    except Exception as e:
        print(f"⚠️ Erreur en chargeant {cog}: {e}")

# --- Run ---
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("❌ DISCORD_TOKEN manquant dans les variables d'environnement")
bot.run(TOKEN)
