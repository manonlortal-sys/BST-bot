import discord
from discord.ext import commands
from discord import app_commands

# On importe la View depuis alerts (elle sera définie là-bas)
from .alerts import PingButtonsView


class PanelCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        # Important : on ré-enregistre la View persistante à chaque redémarrage
        self.bot.add_view(PingButtonsView(self.bot))

    @app_commands.command(
        name="pingpanel",
        description="Publier le panneau de ping des percepteurs (défenses)"
    )
    async def pingpanel(self, interaction: discord.Interaction):
        view = PingButtonsView(self.bot)
        embed = discord.Embed(
            title="🛡️ Panneau de défense",
            description="Cliquez sur les boutons ci-dessous pour déclencher une alerte.",
            color=discord.Color.blue()
        )

        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(PanelCog(bot))
