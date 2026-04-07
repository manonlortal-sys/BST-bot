# cogs/combat.py

import discord
from discord.ext import commands
from discord import app_commands

MAX_JOUEURS = 4

class CombatCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.combats_en_cours = {}  # key: joueur.id, value: dict avec infos du combat

    async def cog_load(self):
        print("✅ Cog Combat chargé et prêt")

    @app_commands.command(name="add_screen", description="Ajouter un combat")
    async def add_screen(self, interaction: discord.Interaction):
        joueur_id = interaction.user.id

        if joueur_id in self.combats_en_cours:
            await interaction.response.send_message(
                "❌ Tu as déjà un combat en cours. Termine-le avant d'en lancer un autre.", 
                ephemeral=True
            )
            return

        self.combats_en_cours[joueur_id] = {
            "status": "en_cours",
            "joueurs_present": [interaction.user],
            "type": None,
            "points": 0
        }

        embed = discord.Embed(
            title="📝 Choix du type de combat",
            description="Validation en attente ⏳\nCliquez sur un bouton pour choisir le type",
            color=0x5865F2
        )
        embed.add_field(name="Joueurs présents", value=interaction.user.mention)
        embed.add_field(name="Points par joueur", value="0 points")

        # Vue unique avec boutons
        view = CombatView(self, joueur_id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

    @app_commands.command(name="reset_combat", description="Réinitialiser ton combat en cours")
    async def reset_combat(self, interaction: discord.Interaction):
        joueur_id = interaction.user.id
        if joueur_id in self.combats_en_cours:
            del self.combats_en_cours[joueur_id]
            await interaction.response.send_message("✅ Ton combat en cours a été réinitialisé.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Tu n'as pas de combat en cours.", ephemeral=True)


# ---------------------------
# Vue unique pour tout le combat
# ---------------------------
class CombatView(discord.ui.View):
    def __init__(self, cog, joueur_id):
        super().__init__(timeout=None)
        self.cog = cog
        self.joueur_id = joueur_id

    # Attaque
    @discord.ui.button(label="🗡️ Attaque", style=discord.ButtonStyle.red)
    async def attaque(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_type(interaction, "Attaque")

    # Défense
    @discord.ui.button(label="🛡️ Défense", style=discord.ButtonStyle.green)
    async def defense(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_type(interaction, "Défense")

    # Ajouter joueurs
    @discord.ui.button(label="➕ Ajouter joueurs", style=discord.ButtonStyle.blurple)
    async def ajouter_joueurs(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.joueur_id:
            await interaction.response.send_message("❌ Ce n'est pas ton combat.", ephemeral=True)
            return

        # On utilise un modal pour que l'utilisateur tape les noms des joueurs
        modal = AjouterJoueursModal(self.cog, self.joueur_id)
        await interaction.response.send_modal(modal)

    async def set_type(self, interaction: discord.Interaction, combat_type: str):
        if interaction.user.id != self.joueur_id:
            await interaction.response.send_message("❌ Ce n'est pas ton combat.", ephemeral=True)
            return

        self.cog.combats_en_cours[self.joueur_id]["type"] = combat_type
        embed = discord.Embed(
            title=f"📝 Type de combat choisi : {combat_type}",
            description="Validation en attente ⏳",
            color=0x5865F2
        )
        joueurs = self.cog.combats_en_cours[self.joueur_id]["joueurs_present"]
        embed.add_field(name="Joueurs présents", value=", ".join([m.mention for m in joueurs]))
        embed.add_field(name="Points par joueur", value=f"{self.cog.combats_en_cours[self.joueur_id]['points']} points")
        await interaction.response.edit_message(embed=embed, view=self)


# ---------------------------
# Modal pour ajouter les joueurs via texte (auto-complétion)
# ---------------------------
class AjouterJoueursModal(discord.ui.Modal, title="Ajouter des joueurs (max 4)"):
    joueurs = discord.ui.TextInput(
        label="Mentions ou noms des joueurs séparés par une virgule",
        style=discord.TextStyle.short,
        placeholder="Ex: @Yohan, @Alex",
        required=True,
        max_length=200
    )

    def __init__(self, cog, joueur_id):
        super().__init__()
        self.cog = cog
        self.joueur_id = joueur_id

    async def on_submit(self, interaction: discord.Interaction):
        combat = self.cog.combats_en_cours[self.joueur_id]
        guild = interaction.guild

        mentions = [name.strip() for name in self.joueurs.value.split(",")]
        for m_name in mentions:
            # tenter de récupérer le membre par mention ou nom
            member = None
            if m_name.startswith("<@") and m_name.endswith(">"):
                member_id = int(m_name.replace("<@", "").replace(">", "").replace("!", ""))
                member = guild.get_member(member_id)
            else:
                # rechercher par nom
                member = discord.utils.find(lambda x: x.name == m_name, guild.members)
            if member and member not in combat["joueurs_present"] and len(combat["joueurs_present"]) < MAX_JOUEURS:
                combat["joueurs_present"].append(member)

        embed = discord.Embed(
            title=f"📝 Type de combat choisi : {combat['type']}",
            description="Validation en attente ⏳",
            color=0x5865F2
        )
        embed.add_field(name="Joueurs présents", value=", ".join([m.mention for m in combat["joueurs_present"]]))
        embed.add_field(name="Points par joueur", value=f"{combat['points']} points")
        await interaction.response.edit_message(embed=embed, view=interaction.message.components[0].view)


# ---------------------------
# Fonction pour charger le cog
# ---------------------------
async def setup(bot):
    await bot.add_cog(CombatCog(bot))