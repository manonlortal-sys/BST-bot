import discord
from discord.ext import commands
from discord import app_commands

class PingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # On laisse tomber create_db pour l'instant pour éviter les erreurs de chargement

    @app_commands.command(name="pingpanel", description="Publier le panneau de ping minimal")
    async def pingpanel(self, interaction: discord.Interaction):
        # Répond immédiatement pour éviter "l'application ne répond plus"
        await interaction.response.send_message("🛡️ Panneau de défense minimal actif !", ephemeral=False)

async def setup(bot: commands.Bot):
    await bot.add_cog(PingCog(bot))
    # Sync globale pour éviter la dépendance au TEST_GUILD_ID
    await bot.tree.sync()
