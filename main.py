import os
import asyncio
import logging

import discord
from discord.ext import commands

logging.basicConfig(level=logging.INFO)

INTENTS = discord.Intents.default()
INTENTS.guilds = True
INTENTS.members = True
INTENTS.messages = True
INTENTS.reactions = True

bot = commands.Bot(command_prefix="!", intents=INTENTS)


@bot.event
async def on_ready():
    print(f"Connecté en tant que {bot.user} (ID: {bot.user.id})")
    try:
        await bot.tree.sync()
        print("Commandes slash synchronisées.")
    except Exception as e:
        print(f"Erreur de sync des commandes : {e}")


async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("La variable d'environnement DISCORD_TOKEN est manquante.")

    initial_extensions = [
        "cogs.alerts",
        "cogs.leaderboard",
        "cogs.reactions",
        "cogs.ping_panel",
    ]

    async with bot:
        for ext in initial_extensions:
            try:
                await bot.load_extension(ext)
                print(f"Extension chargée : {ext}")
            except Exception as e:
                print(f"Erreur en chargeant {ext} : {e}")
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
