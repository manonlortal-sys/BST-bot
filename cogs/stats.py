import discord
from discord.ext import commands
from discord import app_commands

class StatsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="stats", description="Test commande stats")
    async def stats(self, interaction: discord.Interaction):
        await interaction.response.send_message("✅ La commande /stats fonctionne !", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(StatsCog(bot))
