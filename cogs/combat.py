import discord
from discord.ext import commands
from discord import app_commands

# Config des rôles
ROLE_LADDER_ID = 1459190410835660831
ROLE_LEAD_ID = 1280235149191020625

# Points bonus
POINTS_INFERIORITE = 3
POINTS_SUPERIORITE = -2

class CombatCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.current_combat = None  # Contient les infos du combat en cours

    async def update_embed(self):
        """Met à jour l'embed principal du combat"""
        if not self.current_combat:
            return
        embed = discord.Embed(
            title="📊 Ajout d’un combat au ladder purgatoire",
            description="Validation en attente ⏳",
            color=discord.Color.blue()
        )

        # Type de combat
        embed.add_field(
            name="Type de combat",
            value=f"{self.current_combat.get('type', 'Non défini')} (+{self.current_combat.get('points_type', 0)} pts)",
            inline=False
        )

        # Aucun mort
        embed.add_field(
            name="Aucun mort",
            value=f"{self.current_combat.get('aucun_mort', 'Non')} (+{self.current_combat.get('points_aucun_mort', 0)} pts)",
            inline=False
        )

        # Supériorité / Infériorité
        embed.add_field(
            name="Supériorité / Infériorité",
            value=f"Infériorité : +{self.current_combat.get('points_inferiorite',0)} pts\n"
                  f"Supériorité : {self.current_combat.get('points_superiorite',0)} pts",
            inline=False
        )

        # Joueurs et points
        if self.current_combat.get("joueurs"):
            joueurs_txt = ""
            for j in self.current_combat["joueurs"]:
                total = self.current_combat["joueurs"][j]["total"]
                joueurs_txt += f"{j} : {total} pts\n"
            embed.add_field(name="Joueurs", value=joueurs_txt, inline=False)
        await self.current_combat["message"].edit(embed=embed)

    # ------------------ Commande /add ------------------
    @app_commands.command(name="add", description="Ajouter un combat")
    async def add_combat(self, interaction: discord.Interaction):
        self.current_combat = {
            "type": None,
            "points_type": 0,
            "aucun_mort": None,
            "points_aucun_mort": 0,
            "points_inferiorite": 0,
            "points_superiorite": 0,
            "joueurs": {},
        }

        embed = discord.Embed(
            title="📊 Ajout d’un combat au ladder purgatoire",
            description="Validation en attente ⏳",
            color=discord.Color.blue()
        )

        # Boutons
        view = discord.ui.View()
        view.add_item(CombatTypeButton("🗡️ Attaque", "attaque"))
        view.add_item(CombatTypeButton("🛡️ Défense", "defense"))
        view.add_item(JoueursButton())
        view.add_item(BonusButton("🟢 Infériorité", "inferiorite"))
        view.add_item(BonusButton("🔴 Supériorité", "superiorite"))

        message = await interaction.response.send_message(embed=embed, view=view)
        self.current_combat["message"] = await interaction.original_response()

# ------------------ Boutons ------------------

class CombatTypeButton(discord.ui.Button):
    def __init__(self, label, ctype):
        super().__init__(style=discord.ButtonStyle.success, label=label)
        self.ctype = ctype

    async def callback(self, interaction: discord.Interaction):
        cog: CombatCog = interaction.client.get_cog("CombatCog")
        if not cog.current_combat:
            await interaction.response.send_message("Pas de combat en cours", ephemeral=True)
            return

        # Appliquer le type de combat
        cog.current_combat["type"] = self.label
        cog.current_combat["points_type"] = 5 if self.ctype == "attaque" else 4

        # Mettre à jour les points des joueurs
        for j in cog.current_combat["joueurs"]:
            cog.current_combat["joueurs"][j]["total"] = (
                cog.current_combat["joueurs"][j]["total_base"] +
                cog.current_combat["points_type"] +
                cog.current_combat.get("points_aucun_mort",0) +
                cog.current_combat.get("points_inferiorite",0) +
                cog.current_combat.get("points_superiorite",0)
            )
        await cog.update_embed()
        await interaction.response.send_message(f"Type {self.label} appliqué ✅", ephemeral=True)

class BonusButton(discord.ui.Button):
    def __init__(self, label, bonus_type):
        super().__init__(style=discord.ButtonStyle.primary, label=label)
        self.bonus_type = bonus_type

    async def callback(self, interaction: discord.Interaction):
        cog: CombatCog = interaction.client.get_cog("CombatCog")
        if not cog.current_combat:
            await interaction.response.send_message("Pas de combat en cours", ephemeral=True)
            return

        if self.bonus_type == "inferiorite":
            cog.current_combat["points_inferiorite"] = POINTS_INFERIORITE
        elif self.bonus_type == "superiorite":
            cog.current_combat["points_superiorite"] = POINTS_SUPERIORITE

        # Mettre à jour les points joueurs
        for j in cog.current_combat["joueurs"]:
            cog.current_combat["joueurs"][j]["total"] = (
                cog.current_combat["joueurs"][j]["total_base"] +
                cog.current_combat["points_type"] +
                cog.current_combat.get("points_aucun_mort",0) +
                cog.current_combat.get("points_inferiorite",0) +
                cog.current_combat.get("points_superiorite",0)
            )
        await cog.update_embed()
        await interaction.response.send_message(f"{self.label} appliqué ✅", ephemeral=True)

class JoueursButton(discord.ui.Button):
    def __init__(self):
        super().__init__(style=discord.ButtonStyle.secondary, label="➕ Ajouter joueurs")

    async def callback(self, interaction: discord.Interaction):
        # Ici tu dois implémenter le UserSelect pour choisir jusqu'à 4 joueurs
        await interaction.response.send_message("Sélection de joueurs (placeholder) ✅", ephemeral=True)

# ------------------ Setup ------------------

async def setup(bot):
    await bot.add_cog(CombatCog(bot))