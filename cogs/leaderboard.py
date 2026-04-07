# cogs/leaderboard.py

import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime

# IDs à utiliser
ROLE_LADDER_ID = 1459190410835660831
ROLE_LEAD_ID = 1280235149191020625
ROLE_MEMBRES_ID = 1280235478733422673
CANAL_LEADERBOARD_ID = 1491009331762696344

class LeaderboardCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.leaderboards = {}  # stocke tous les leaderboards en mémoire

    async def cog_load(self):
        print("✅ Cog Leaderboard chargé et prêt")

    @app_commands.command(name="new", description="Créer un nouveau leaderboard purgatoire")
    @app_commands.describe(
        cible="Nom de la cible du purgatoire",
        date_debut="Date de début (JJ/MM/AAAA)",
        date_fin="Date de fin (JJ/MM/AAAA)"
    )
    async def new(self, interaction: discord.Interaction, cible: str, date_debut: str, date_fin: str):
        # Vérification des rôles
        roles_ids = [role.id for role in interaction.user.roles]
        if ROLE_LADDER_ID not in roles_ids and ROLE_LEAD_ID not in roles_ids:
            await interaction.response.send_message(
                "❌ Tu n'as pas la permission de créer un leaderboard.", ephemeral=True
            )
            return

        # Conversion dates en datetime pour validation simple
        try:
            debut_dt = datetime.strptime(date_debut, "%d/%m/%Y")
            fin_dt = datetime.strptime(date_fin, "%d/%m/%Y")
            if fin_dt < debut_dt:
                await interaction.response.send_message(
                    "❌ La date de fin ne peut pas être avant la date de début.", ephemeral=True
                )
                return
        except ValueError:
            await interaction.response.send_message(
                "❌ Format de date invalide. Utilise JJ/MM/AAAA.", ephemeral=True
            )
            return

        # Préparer l'embed
        embed = discord.Embed(
            title=f"📊 Nouveau leaderboard purgatoire",
            description=f"🎯 **Cible du purgatoire :** {cible}\n"
                        f"📅 **Durée :** {date_debut} → {date_fin}",
            color=0x5865F2
        )
        embed.add_field(name="🏆 Classement", value="*(vide pour l’instant)*", inline=False)
        embed.set_footer(text=f"Créé par {interaction.user.display_name}")

        # Envoyer dans le canal prévu
        canal = self.bot.get_channel(CANAL_LEADERBOARD_ID)
        if canal is None:
            await interaction.response.send_message("❌ Impossible de trouver le canal du leaderboard.", ephemeral=True)
            return

        msg = await canal.send(
            content=f"<@&{ROLE_MEMBRES_ID}> merci de valider le leaderboard ⏳",
            embed=embed
        )

        # Stocker en mémoire
        self.leaderboards[msg.id] = {
            "cible": cible,
            "debut": debut_dt,
            "fin": fin_dt,
            "message": msg,
            "classement": {},  # clé: joueur.id, valeur: points
        }

        await interaction.response.send_message(
            f"✅ Leaderboard créé avec succès dans {canal.mention}", ephemeral=True
        )

# Fonction pour charger le cog
async def setup(bot):
    await bot.add_cog(LeaderboardCog(bot))