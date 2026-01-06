import os
import discord
from discord.ext import commands

INTENTS = discord.Intents.default()
INTENTS.message_content = True

bot = commands.Bot(intents=INTENTS)

@bot.event
async def on_ready():
    print(f"Connecté en tant que {bot.user}")
    await bot.tree.sync()

async def setup():
    await bot.load_extension("cogs.cafard")

bot.loop.create_task(setup())

bot.run(os.getenv("DISCORD_TOKEN"))
