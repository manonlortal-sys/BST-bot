# cogs/stats.py
from typing import Optional
import discord
from discord.ext import commands
from discord import app_commands

# on importe uniquement la fonction nécessaire
from storage import get_player_stats

class StatsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="stats", description="Voir les stats d’un joueur")
    @app_commands.describe(member="Membre à inspecter (optionnel)")
    async def stats(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "Commande à utiliser sur un serveur.",
                ephemeral=True
            )
            return

        target = member or interaction.user

        # garde-fou: si storage lève une exception, on renvoie un message clair
        try:
            defenses, pings, wins, losses = get_player_stats(guild.id, target.id)
        except Exception as e:
            await interaction.response.send_message(
                f"⚠️ Impossible de récupérer les stats (DB indisponible).",
                ephemeral=True
            )
            return

        ratio = f"{(wins/(wins+losses)*100):.1f}%" if (wins + losses) else "0%"

        embed = discord.Embed(
            title=f"📊 Stats de {target.display_name}",
            color=discord.Color.blurple()
        )
        embed.add_field(name="🛡️ Défenses prises", value=str(defenses), inline=True)
        embed.add_field(name="⚡ Pings envoyés", value=str(pings), inline=True)
        embed.add_field(name="🏆 Victoires", value=str(wins), inline=True)
        embed.add_field(name="❌ Défaites", value=str(losses), inline=True)
        embed.add_field(name="📊 Ratio victoire", value=ratio, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=False)

async def setup(bot: commands.Bot):
    await bot.add_cog(StatsCog(bot))
