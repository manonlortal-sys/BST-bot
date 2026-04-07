# cogs/combat.py

import discord
from discord.ext import commands

class CombatCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.combats_en_cours = {}  # key: joueur.id, value: dict avec infos du combat

    @commands.Cog.listener()
    async def on_ready(self):
        print("Cog Combat chargé ✅")

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        # Nécessaire pour les interactions futures (buttons, menus)
        pass

    @commands.tree.command(name="add_screen", description="Ajouter un combat")
    async def add_screen(self, interaction: discord.Interaction):
        joueur_id = interaction.user.id

        # Vérifier si le joueur a déjà un combat en cours
        if joueur_id in self.combats_en_cours:
            await interaction.response.send_message(
                "❌ Tu as déjà un combat en cours. Termine-le avant d'en lancer un autre.", 
                ephemeral=True
            )
            return

        # Créer le combat minimal
        self.combats_en_cours[joueur_id] = {
            "status": "en_cours",
            "joueurs_present": [interaction.user],
            "points": 0
        }

        # Créer un embed prévisualisation simple
        embed = discord.Embed(
            title="📝 Combat en cours",
            description="Prévisualisation du combat ⏳",
            color=0x5865F2
        )
        embed.add_field(name="Joueurs présents", value=interaction.user.mention)
        embed.add_field(name="Points par joueur", value="0 points")

        await interaction.response.send_message(embed=embed, ephemeral=False)

# Fonction pour charger le cog depuis main.py
async def setup(bot):
    await bot.add_cog(CombatCog(bot))