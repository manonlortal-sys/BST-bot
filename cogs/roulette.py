import discord
from discord.ext import commands

class Roulette(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(name="testroulette", description="Test: le cog Roulette est chargé")
    async def testroulette(self, interaction: discord.Interaction):
        await interaction.response.send_message("🎰 Cog Roulette OK (slash)")

async def setup(bot):
    await bot.add_cog(Roulette(bot))
