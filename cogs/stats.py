from typing import Optional
import discord
from discord.ext import commands
from discord import app_commands

from storage import get_player_stats

class StatsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="stats", description="Voir les stats d’un joueur")
    @app_commands.describe(member="Membre à inspecter (optionnel)")
    async def stats(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Impossible de récupérer le serveur.", ephemeral=True)
            return

        defenses, pings, wins, losses = get_player_stats(guild.id, target.id)
        ratio = f"{(wins/(wins+losses)*100):.1f}%" if (wins+losses) else "0%"

        embed = discord.Embed(title=f"📈 Stats de {target.display_name}", color=discord.Color.blurple())
        embed.add_field(name="Défenses", value=str(defenses))
        embed.add_field(name="Pings envoyés", value=str(pings))
        embed.add_field(name="Victoires", value=str(wins))
        embed.add_field(name="Défaites", value=str(losses))
        embed.add_field(name="Ratio victoire", value=ratio, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=False)

async def setup(bot: commands.Bot):
    await bot.add_cog(StatsCog(bot))
