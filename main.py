import os
import discord
from discord.ext import commands

INTENTS = discord.Intents.default()
INTENTS.message_content = True


class CafardBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=INTENTS
        )

    async def setup_hook(self):
        await self.load_extension("cogs.cafard")
        await self.tree.sync()


bot = CafardBot()


@bot.event
async def on_ready():
    print(f"Connecté en tant que {bot.user}")


bot.run(os.getenv("DISCORD_TOKEN"))
