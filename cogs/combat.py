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

        view = CombatView(self, joueur_id)
        embed = discord.Embed(
            title="📝 Choix du type de combat",
            description="Validation en attente ⏳\nCliquez sur un bouton pour choisir le type",
            color=0x5865F2
        )
        embed.add_field(name="Joueurs présents", value=interaction.user.mention)
        embed.add_field(name="Aucun mort", value="❌ Non")
        embed.add_field(name="Points par joueur", value="0 points")

        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)
        message = await interaction.original_response()

        self.combats_en_cours[joueur_id] = {
            "status": "en_cours",
            "joueurs_present": [interaction.user],
            "type": None,
            "aucun_mort": False,
            "points": 0,
            "message": message,
            "view": view,
            "points_joueurs": {interaction.user.id: 0}
        }

    @app_commands.command(name="reset_combat", description="Réinitialiser ton combat en cours")
    async def reset_combat(self, interaction: discord.Interaction):
        joueur_id = interaction.user.id
        if joueur_id in self.combats_en_cours:
            del self.combats_en_cours[joueur_id]
            await interaction.response.send_message("✅ Ton combat en cours a été réinitialisé.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Tu n'as pas de combat en cours.", ephemeral=True)


# ---------------------------
# Vue principale avec boutons
# ---------------------------
class CombatView(discord.ui.View):
    def __init__(self, cog, joueur_id):
        super().__init__(timeout=None)
        self.cog = cog
        self.joueur_id = joueur_id

    @discord.ui.button(label="🗡️ Attaque", style=discord.ButtonStyle.red)
    async def attaque(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.joueur_id:
            await interaction.response.send_message("❌ Ce n'est pas ton combat.", ephemeral=True)
            return
        await interaction.response.defer()
        await self.set_type(interaction, "Attaque")

    @discord.ui.button(label="🛡️ Défense", style=discord.ButtonStyle.green)
    async def defense(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.joueur_id:
            await interaction.response.send_message("❌ Ce n'est pas ton combat.", ephemeral=True)
            return
        await interaction.response.defer()
        await self.set_type(interaction, "Défense")

    @discord.ui.button(label="❎ Aucun mort", style=discord.ButtonStyle.gray)
    async def aucun_mort(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.joueur_id:
            await interaction.response.send_message("❌ Ce n'est pas ton combat.", ephemeral=True)
            return

        await interaction.response.defer()
        combat = self.cog.combats_en_cours[self.joueur_id]
        combat["aucun_mort"] = not combat["aucun_mort"]

        # On peut ajouter des points bonus si Aucun mort est choisi
        if combat["aucun_mort"]:
            for member in combat["joueurs_present"]:
                combat["points_joueurs"][member.id] = combat["points_joueurs"].get(member.id, 0) + 10
        else:
            for member in combat["joueurs_present"]:
                combat["points_joueurs"][member.id] = max(combat["points_joueurs"].get(member.id, 0) - 10, 0)

        await self.update_embed(combat)

    @discord.ui.button(label="➕ Ajouter joueurs", style=discord.ButtonStyle.blurple)
    async def ajouter_joueurs(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.joueur_id:
            await interaction.response.send_message("❌ Ce n'est pas ton combat.", ephemeral=True)
            return

        view = AjouterJoueursView(self.cog, self.joueur_id)
        await interaction.response.send_message(
            "Sélectionne les joueurs à ajouter ⬇️",
            view=view,
            ephemeral=True
        )

    async def set_type(self, interaction: discord.Interaction, combat_type: str):
        combat = self.cog.combats_en_cours[self.joueur_id]
        combat["type"] = combat_type
        await self.update_embed(combat)

    async def update_embed(self, combat):
        embed = discord.Embed(
            title=f"📝 Type de combat : {combat['type'] or 'Non choisi'}",
            description="Validation en attente ⏳",
            color=0x5865F2
        )
        embed.add_field(
            name="Joueurs présents",
            value=", ".join([m.mention for m in combat["joueurs_present"]])
        )
        embed.add_field(name="Aucun mort", value="✅ Oui" if combat["aucun_mort"] else "❌ Non")

        points_text = "\n".join([
            f"{self.cog.bot.get_user(uid).mention}: {pts} pts"
            for uid, pts in combat["points_joueurs"].items()
        ])
        embed.add_field(name="Points par joueur", value=points_text or "0 points")

        await combat["message"].edit(embed=embed, view=combat["view"])


# ---------------------------
# Vue avec menu de sélection des joueurs
# ---------------------------
class AjouterJoueursView(discord.ui.View):
    def __init__(self, cog, joueur_id):
        super().__init__(timeout=900)
        self.cog = cog
        self.joueur_id = joueur_id
        self.add_item(JoueurSelect(cog, joueur_id))


class JoueurSelect(discord.ui.UserSelect):
    def __init__(self, cog, joueur_id):
        super().__init__(max_values=MAX_JOUEURS, placeholder="Sélectionne jusqu'à 4 joueurs")
        self.cog = cog
        self.joueur_id = joueur_id

    async def callback(self, interaction: discord.Interaction):
        combat = self.cog.combats_en_cours[self.joueur_id]

        for member in self.values:
            if member not in combat["joueurs_present"] and len(combat["joueurs_present"]) < MAX_JOUEURS:
                combat["joueurs_present"].append(member)
                combat["points_joueurs"][member.id] = 0

        await interaction.response.defer()
        await combat["view"].update_embed(combat)


# ---------------------------
# Fonction pour charger le cog
# ---------------------------
async def setup(bot):
    await bot.add_cog(CombatCog(bot))