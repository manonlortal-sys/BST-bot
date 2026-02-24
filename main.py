import random
import discord
from discord.ext import commands
import os
from flask import Flask
from threading import Thread

# ====== FLASK POUR RENDER ======

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running"

def run():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()

# ====== DISCORD BOT ======

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

TARGET_ID = 278874848061554688

reponses = [
    "silence flûte",
    "on t'a pas sonné",
    "qui a demandé l'heure à patrikus?",
    "merci d'ignorer ce qu'il raconte",
    "bonjour, non",
    "coupez lui internet",
    "la paix non",
    "Y VA LA FERMER SA GUEULE"
]

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if message.author.id == TARGET_ID:
        await message.channel.send(random.choice(reponses))

    await bot.process_commands(message)

# LANCE FLASK
keep_alive()

# LANCE DISCORD
bot.run(os.getenv("DISCORD_TOKEN"))
