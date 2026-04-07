import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime

# IDs des rôles
ROLE_LADDER_ID = 1459190410835660831
ROLE_LEAD_ID = 1280235149191020625

class LeaderboardEditCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        print("✅ Cog Leaderboard Edit chargé et prêt")

    @app_commands.command(
        name="modifier_joueur",
        description="Modifier manuellement les points d’un joueur dans le leaderboard"
    )
    @app_commands.describe(
        message_id="ID du message du leaderboard à modifier",
        joueur="Le joueur dont tu veux modifier les points",
        nouveau_total="Nouveau total de points à mettre"
    )
    async def modifier_joueur(
        self,
        interaction: discord.Interaction,
        message_id: str,
        joueur: discord.Member,
        nouveau_total: int
    ):
        # Vérifier rôle
        roles_ids = [role.id for role in interaction.user.roles]
        if ROLE_LADDER_ID not in roles_ids and ROLE_LEAD_ID not in roles_ids:
            await interaction.response.send_message(
                "❌ Tu n’as pas la permission de modifier le leaderboard.", ephemeral=True
            )
            return

        # Récupérer le leaderboard correspondant
        leaderboard_cog = self.bot.get_cog("LeaderboardCog")
        if leaderboard_cog is None:
            await interaction.response.send_message(
                "❌ Cog Leaderboard introuvable.", ephemeral=True
            )
            return

        try:
            msg_id_int = int(message_id)
        except ValueError:
            await interaction.response.send_message(
                "❌ L’ID du message doit être un nombre.", ephemeral=True
            )
            return

        if msg_id_int not in leaderboard_cog.leaderboards:
            await interaction.response.send_message(
                "❌ Leaderboard introuvable pour ce message.", ephemeral=True
            )
            return

        leaderboard = leaderboard_cog.leaderboards[msg_id_int]

        ancien_total = leaderboard["classement"].get(joueur.id, 0)
        leaderboard["classement"][joueur.id] = nouveau_total

        # Mettre à jour l'embed du leaderboard
        embed = leaderboard["message"].embeds[0]
        classement_lines = []
        for member_id, points in leaderboard["classement"].items():
            member = interaction.guild.get_member(member_id)
            if member:
                classement_lines.append(f"{member.display_name} : {points} pts")
        embed.set_field_at(
            2,
            name="🏆 Classement",
            value="\n".join(classement_lines) if classement_lines else "*(vide pour l’instant)*",
            inline=False
        )
        await leaderboard["message"].edit(embed=embed)

        # Message public de suivi
        now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
        await interaction.channel.send(
            f"Total points du joueur {joueur.mention} modifié par {interaction.user.mention} : {ancien_total} pts -> {nouveau_total} pts. {now_str}"
        )

        await interaction.response.send_message(
            "✅ Modification effectuée.", ephemeral=True
        )


# Fonction pour charger le cog
async def setup(bot):
    await bot.add_cog(LeaderboardEditCog(bot))