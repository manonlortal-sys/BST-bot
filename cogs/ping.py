import discord
from discord.ext import commands

class PingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(name="testping", description="Test: le cog Ping est chargé")
    async def testping(self, interaction: discord.Interaction):
        await interaction.response.send_message("📢 Cog Ping OK (slash)")

async def setup(bot):
    await bot.add_cog(PingCog(bot))
