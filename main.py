import random
import discord
from discord.ext import commands
import os

intents = discord.Intents.default()
intents.message_content = True  # IMPORTANT pour lire les messages

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

bot.run(os.getenv("TOKEN"))
