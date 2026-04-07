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

        view = ChoixTypeView(self, joueur_id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)


class ChoixTypeView(discord.ui.View):
    def __init__(self, cog, joueur_id):
        super().__init__(timeout=None)
        self.cog = cog
        self.joueur_id = joueur_id

    @discord.ui.button(label="🗡️ Attaque", style=discord.ButtonStyle.red)
    async def attaque(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_type(interaction, "Attaque")

    @discord.ui.button(label="🛡️ Défense", style=discord.ButtonStyle.green)
    async def defense(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_type(interaction, "Défense")

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

        # Nouveau bouton pour passer à l'ajout des joueurs
        view = AjouterJoueursButton(self.cog, self.joueur_id)
        await interaction.response.edit_message(embed=embed, view=view)


class AjouterJoueursButton(discord.ui.View):
    def __init__(self, cog, joueur_id):
        super().__init__(timeout=None)
        self.cog = cog
        self.joueur_id = joueur_id

    @discord.ui.button(label="➕ Ajouter joueurs", style=discord.ButtonStyle.blurple)
    async def ajouter_joueurs(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.joueur_id:
            await interaction.response.send_message("❌ Ce n'est pas ton combat.", ephemeral=True)
            return

        combat = self.cog.combats_en_cours[self.joueur_id]

        options = [
            discord.SelectOption(label=m.name, value=str(m.id))
            for m in interaction.guild.members if not m.bot and m != interaction.user
        ]
        if not options:
            await interaction.response.send_message("❌ Aucun membre à ajouter.", ephemeral=True)
            return

        view = JoueurSelectView(self.cog, self.joueur_id, options)
        await interaction.response.send_message("Sélectionne les joueurs :", view=view, ephemeral=True)


class JoueurSelectView(discord.ui.View):
    def __init__(self, cog, joueur_id, options):
        super().__init__(timeout=None)
        self.cog = cog
        self.joueur_id = joueur_id
        self.add_item(JoueurSelect(cog, joueur_id, options))


class JoueurSelect(discord.ui.Select):
    def __init__(self, cog, joueur_id, options):
        super().__init__(
            placeholder="Ajouter des joueurs (max 4)",
            min_values=0,
            max_values=MAX_JOUEURS-1,
            options=options
        )
        self.cog = cog
        self.joueur_id = joueur_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.joueur_id:
            await interaction.response.send_message("❌ Ce n'est pas ton combat.", ephemeral=True)
            return

        combat = self.cog.combats_en_cours[self.joueur_id]
        for user_id_str in self.values:
            member = interaction.guild.get_member(int(user_id_str))
            if member and member not in combat["joueurs_present"]:
                if len(combat["joueurs_present"]) < MAX_JOUEURS:
                    combat["joueurs_present"].append(member)

        embed = discord.Embed(
            title=f"📝 Type de combat choisi : {combat['type']}",
            description="Validation en attente ⏳",
            color=0x5865F2
        )
        embed.add_field(name="Joueurs présents", value=", ".join([m.mention for m in combat["joueurs_present"]]))
        embed.add_field(name="Points par joueur", value=f"{combat['points']} points")

        await interaction.response.edit_message(embed=embed, view=self.view)


# ---------------------------
# Fonction pour charger le cog
# ---------------------------
async def setup(bot):
    await bot.add_cog(CombatCog(bot))