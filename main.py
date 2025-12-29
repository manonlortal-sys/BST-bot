import os
import discord
from discord.ext import commands

TOKEN = os.getenv("DISCORD_TOKEN")
# ou TOKEN = "TON_TOKEN"

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Connecté en tant que {bot.user}")

async def setup():
    await bot.load_extension("cogs.copie")
    await bot.start(TOKEN)

import asyncio
asyncio.run(setup())
