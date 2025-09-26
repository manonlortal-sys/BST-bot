import discord
from discord.ext import commands
from discord import app_commands

from storage import get_player_stats


class StatsCog(commands.Cog):
    """Commandes de statistiques joueur (défenses, pings, victoires/défaites)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="stats", description="Voir les stats d’un joueur (défenses, pings, victoires/défaites)")
    @app_commands.describe(member="Membre à inspecter (optionnel). Laisse vide pour toi-même.")
    async def stats(self, interaction: discord.Interaction, member: discord.Member | None = None):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Cette commande doit être utilisée dans un serveur.", ephemeral=True)
            return

        target = member or interaction.user
        defenses, pings, wins, losses = get_player_stats(guild.id, target.id)

        embed = discord.Embed(
            title=f"📊 Stats de {target.display_name}",
            color=discord.Color.green(),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Défenses prises (👍)", value=str(defenses), inline=True)
        embed.add_field(name="Victoires (🏆)", value=str(wins), inline=True)
        embed.add_field(name="Défaites (❌)", value=str(losses), inline=True)
        embed.add_field(name="Pings envoyés", value=str(pings), inline=True)

        # Ratio victoire si défenses > 0
        total_fights = wins + losses
        ratio = f"{(wins / total_fights * 100):.1f}%" if total_fights else "0%"
        embed.add_field(name="Ratio victoire", value=ratio, inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(StatsCog(bot))
