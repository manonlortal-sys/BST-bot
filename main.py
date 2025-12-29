import os
import discord
from discord.ext import commands
from copie import setup_copie

TOKEN = os.getenv("DISCORD_TOKEN")
# ou : TOKEN = "TON_TOKEN_ICI"

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Connecté en tant que {bot.user}")

# on branche la logique de copie
setup_copie(bot)

bot.run(TOKEN)
