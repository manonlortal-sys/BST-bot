import os
import asyncio
import logging

import discord
from discord.ext import commands
from aiohttp import web

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


# --- Petit serveur web pour Render / UptimeRobot ---

async def handle_root(request: web.Request) -> web.Response:
    return web.Response(text="OK")


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_root)

    port = int(os.getenv("PORT", "10000"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Serveur web démarré sur le port {port}")


# --- Démarrage bot + serveur web ---

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

    # On démarre le serveur web pour Render / UptimeRobot
    await start_web_server()

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
