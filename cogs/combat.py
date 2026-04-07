# cogs/combat.py

import discord
from discord.ext import commands
from discord import app_commands

MAX_JOUEURS = 4
MAX_SCREENS = 5  # Limite de screens par combat

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
            title="📊 Ajout d’un combat au ladder purgatoire",
            description="Validation en attente ⏳",
            color=0x5865F2
        )
        embed.add_field(name="👥 Joueurs présents", value=interaction.user.mention)
        embed.add_field(
            name="💠 Points du combat",
            value="🗡️ Attaque : +0 pts\n🛡️ Défense : +0 pts\n❎ Aucun mort : +0 pts\n⬇️ Infériorité : +0 pts\n⬆️ Supériorité : 0 pts"
        )
        embed.add_field(name="💰 Points par joueur", value="0 pts")
        embed.add_field(name="🖼️ Screens", value="0 screen(s) ajoutés")

        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)
        message = await interaction.original_response()

        self.combats_en_cours[joueur_id] = {
            "status": "en_cours",
            "joueurs_present": [interaction.user],
            "type": None,
            "aucun_mort": False,
            "inferiorite": 0,
            "superiorite": 0,
            "points": 0,
            "bonus": {"aucun_mort": 0, "attaque": 0, "defense": 0, "inferiorite": 0, "superiorite": 0},
            "screens": [],
            "message": message,
            "view": view,
        }

    @app_commands.command(name="reset_combat", description="Réinitialiser ton combat en cours")
    async def reset_combat(self, interaction: discord.Interaction):
        joueur_id = interaction.user.id
        if joueur_id in self.combats_en_cours:
            del self.combats_en_cours[joueur_id]
            await interaction.response.send_message("✅ Ton combat en cours a été réinitialisé.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Tu n'as pas de combat en cours.", ephemeral=True)

    @app_commands.command(name="add_screen_file", description="Ajouter un ou plusieurs screens au combat")
    @app_commands.describe(fichiers="Les fichiers images du combat")
    async def add_screen_file(self, interaction: discord.Interaction, fichiers: discord.Attachment):
        joueur_id = interaction.user.id
        if joueur_id not in self.combats_en_cours:
            await interaction.response.send_message("❌ Tu n'as pas de combat en cours.", ephemeral=True)
            return

        combat = self.combats_en_cours[joueur_id]

        if len(combat["screens"]) >= MAX_SCREENS:
            await interaction.response.send_message(f"❌ Limite de {MAX_SCREENS} screens par combat atteinte.", ephemeral=True)
            return

        combat["screens"].append(fichiers.url)
        await interaction.response.send_message(f"✅ Screen ajouté ! ({len(combat['screens'])}/{MAX_SCREENS})", ephemeral=True)
        await combat["view"].update_embed(combat)


# ---------------------------
# Vue principale avec boutons
# ---------------------------
class CombatView(discord.ui.View):
    BONUS_POINTS = {"aucun_mort": 10, "attaque": 5, "defense": 5, "inferiorite": 3, "superiorite": -2}

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

    @discord.ui.button(label="❎ Aucun mort", style=discord.ButtonStyle.gray)
    async def aucun_mort(self, interaction: discord.Interaction, button: discord.ui.Button):
        combat = self.cog.combats_en_cours[self.joueur_id]
        combat["aucun_mort"] = not combat["aucun_mort"]
        combat["bonus"]["aucun_mort"] = self.BONUS_POINTS["aucun_mort"] if combat["aucun_mort"] else 0
        combat["points"] = sum(combat["bonus"].values())
        await self.update_embed(combat)
        await interaction.response.defer()

    @discord.ui.button(label="➕ Ajouter joueurs", style=discord.ButtonStyle.blurple)
    async def ajouter_joueurs(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = AjouterJoueursView(self.cog, self.joueur_id)
        await interaction.response.send_message(
            "Sélectionne les joueurs à ajouter ⬇️",
            view=view,
            ephemeral=True
        )

    @discord.ui.button(label="⬇️ Infériorité", style=discord.ButtonStyle.blurple)
    async def inferiorite(self, interaction: discord.Interaction, button: discord.ui.Button):
        combat = self.cog.combats_en_cours[self.joueur_id]
        combat["bonus"]["inferiorite"] = self.BONUS_POINTS["inferiorite"]
        combat["points"] = sum(combat["bonus"].values())
        await self.update_embed(combat)
        await interaction.response.defer()

    @discord.ui.button(label="⬆️ Supériorité", style=discord.ButtonStyle.blurple)
    async def superiorite(self, interaction: discord.Interaction, button: discord.ui.Button):
        combat = self.cog.combats_en_cours[self.joueur_id]
        combat["bonus"]["superiorite"] = self.BONUS_POINTS["superiorite"]
        combat["points"] = sum(combat["bonus"].values())
        await self.update_embed(combat)
        await interaction.response.defer()

    async def set_type(self, interaction: discord.Interaction, combat_type: str):
        combat = self.cog.combats_en_cours[self.joueur_id]
        combat["type"] = combat_type
        combat["bonus"]["attaque" if combat_type == "Attaque" else "defense"] = self.BONUS_POINTS[combat_type.lower()]
        combat["points"] = sum(combat["bonus"].values())
        await self.update_embed(combat)
        await interaction.response.defer()

    async def update_embed(self, combat):
        points_lines = [
            f"🗡️ Attaque : +{combat['bonus']['attaque']} pts",
            f"🛡️ Défense : +{combat['bonus']['defense']} pts",
            f"❎ Aucun mort : +{combat['bonus']['aucun_mort']} pts",
            f"⬇️ Infériorité : +{combat['bonus']['inferiorite']} pts",
            f"⬆️ Supériorité : {combat['bonus']['superiorite']} pts"
        ]
        embed = discord.Embed(
            title="📊 Ajout d’un combat au ladder purgatoire",
            description="Validation en attente ⏳",
            color=0x5865F2
        )
        embed.add_field(
            name="👥 Joueurs présents",
            value=", ".join([m.mention for m in combat["joueurs_present"]])
        )
        embed.add_field(name="💠 Points du combat", value="\n".join(points_lines))
        embed.add_field(name="💰 Points par joueur", value=f"{combat['points']} pts")
        embed.add_field(name="🖼️ Screens", value=f"{len(combat['screens'])} screen(s) ajoutés")
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
        super().__init__(max_values=MAX_JOUEURS, placeholder="Recherche un membre...")
        self.cog = cog
        self.joueur_id = joueur_id

    async def callback(self, interaction: discord.Interaction):
        combat = self.cog.combats_en_cours[self.joueur_id]

        for member in self.values:
            if member not in combat["joueurs_present"] and len(combat["joueurs_present"]) < MAX_JOUEURS:
                combat["joueurs_present"].append(member)

        combat["points"] = sum(combat["bonus"].values())

        await interaction.response.edit_message(content="✅ Joueurs ajoutés !", view=None)
        await combat["view"].update_embed(combat)


# ---------------------------
# Fonction pour charger le cog
# ---------------------------
async def setup(bot):
    await bot.add_cog(CombatCog(bot))