# cogs/combat.py

import discord
from discord.ext import commands
from discord import app_commands

class CombatCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.combats_en_cours = {}  # key: joueur.id, value: dict avec infos du combat

    async def cog_load(self):
        print("✅ Cog Combat chargé et prêt")

    # ---------------------------
    # Commande /add_screen
    # ---------------------------
    @app_commands.command(name="add_screen", description="Ajouter un combat")
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
            "type": None,  # Attaque ou Défense
            "points": 0
        }

        # Créer un embed prévisualisation simple
        embed = discord.Embed(
            title="📝 Choix du type de combat",
            description="Validation en attente ⏳\nCliquez sur un bouton pour choisir",
            color=0x5865F2
        )
        embed.add_field(name="Joueurs présents", value=interaction.user.mention)
        embed.add_field(name="Points par joueur", value="0 points")

        # Créer les boutons
        view = CombatTypeView(self, joueur_id)

        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

# ---------------------------
# Vue avec boutons Attaque / Défense
# ---------------------------
class CombatTypeView(discord.ui.View):
    def __init__(self, cog, joueur_id):
        super().__init__(timeout=None)  # pas de timeout pour l’instant
        self.cog = cog
        self.joueur_id = joueur_id

    @discord.ui.button(label="🗡️ Attaque", style=discord.ButtonStyle.red)
    async def attaque_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.joueur_id:
            await interaction.response.send_message("❌ Ce n'est pas ton combat.", ephemeral=True)
            return

        self.cog.combats_en_cours[self.joueur_id]["type"] = "Attaque"
        await self.update_embed(interaction)

    @discord.ui.button(label="🛡️ Défense", style=discord.ButtonStyle.green)
    async def defense_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.joueur_id:
            await interaction.response.send_message("❌ Ce n'est pas ton combat.", ephemeral=True)
            return

        self.cog.combats_en_cours[self.joueur_id]["type"] = "Défense"
        await self.update_embed(interaction)

    async def update_embed(self, interaction: discord.Interaction):
        combat = self.cog.combats_en_cours[self.joueur_id]
        embed = discord.Embed(
            title=f"📝 Type de combat choisi : {combat['type']}",
            description="Validation en attente ⏳",
            color=0x5865F2
        )
        embed.add_field(name="Joueurs présents", value=interaction.user.mention)
        embed.add_field(name="Points par joueur", value=f"{combat['points']} points")

        await interaction.response.edit_message(embed=embed, view=self)

# ---------------------------
# Fonction pour charger le cog depuis main.py
# ---------------------------
async def setup(bot):
    await bot.add_cog(CombatCog(bot))