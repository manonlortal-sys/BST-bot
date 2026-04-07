# cogs/combat.py

import discord
from discord.ext import commands
from discord import app_commands
import asyncio
from datetime import datetime

MAX_JOUEURS = 4
MAX_SCREENS = 5
LADDER_ROLE_ID = 1459190410835660831  # rôle ladder

class CombatCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.combats_en_cours = {}

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
        embed.add_field(name="💠 Points du combat", value="—")
        embed.add_field(name="💰 Points par joueur", value="0 pts")
        embed.add_field(name="🖼️ Screens ajoutés", value="0 / 5")

        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)
        message = await interaction.original_response()

        self.combats_en_cours[joueur_id] = {
            "status": "en_cours",
            "joueurs_present": [interaction.user],
            "type": None,
            "aucun_mort": False,
            "superiorite": False,
            "inferiorite": False,
            "points": 0,
            "bonus": {"aucun_mort": 0, "attaque": 0, "defense": 0, "superiorite": 0, "inferiorite": 0},
            "message": message,
            "view": view,
            "screens": [],
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
    BONUS_POINTS = {"aucun_mort": 3, "attaque": 5, "defense": 5, "superiorite": -2, "inferiorite": 3}

    def __init__(self, cog, joueur_id):
        super().__init__(timeout=None)
        self.cog = cog
        self.joueur_id = joueur_id

    # Boutons principaux
    @discord.ui.button(label="🗡️ Attaque", style=discord.ButtonStyle.red)
    async def attaque(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_type(interaction, "Attaque")

    @discord.ui.button(label="🛡️ Défense", style=discord.ButtonStyle.red)
    async def defense(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_type(interaction, "Défense")

    @discord.ui.button(label="➕ Ajouter joueurs", style=discord.ButtonStyle.blurple)
    async def ajouter_joueurs(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = AjouterJoueursView(self.cog, self.joueur_id)
        await interaction.response.send_message(
            "Sélectionne les joueurs à ajouter ⬇️",
            view=view,
            ephemeral=True
        )

    # Autres boutons
    @discord.ui.button(label="☠️ Aucun mort", style=discord.ButtonStyle.gray)
    async def aucun_mort(self, interaction: discord.Interaction, button: discord.ui.Button):
        combat = self.cog.combats_en_cours[self.joueur_id]
        combat["aucun_mort"] = not combat["aucun_mort"]
        combat["bonus"]["aucun_mort"] = self.BONUS_POINTS["aucun_mort"] if combat["aucun_mort"] else 0
        combat["points"] = sum(combat["bonus"].values())
        await self.update_embed(combat)
        await interaction.response.defer()

    @discord.ui.button(label="🖼️ Ajouter screen(s)", style=discord.ButtonStyle.gray)
    async def ajouter_screens(self, interaction: discord.Interaction, button: discord.ui.Button):
        combat = self.cog.combats_en_cours[self.joueur_id]

        def check(msg):
            return msg.author.id == self.joueur_id and msg.attachments

        await interaction.response.send_message(
            f"Envoie jusqu'à {MAX_SCREENS - len(combat['screens'])} screen(s) dans ce canal.",
            ephemeral=True
        )

        try:
            msg = await self.cog.bot.wait_for("message", check=check, timeout=300)
        except asyncio.TimeoutError:
            await interaction.followup.send("⏰ Temps écoulé, screens non ajoutés.", ephemeral=True)
            return

        for att in msg.attachments:
            if len(combat["screens"]) < MAX_SCREENS:
                combat["screens"].append(att.url)

        await self.update_embed(combat)
        await interaction.followup.send(f"✅ {len(msg.attachments)} screen(s) ajoutés.", ephemeral=True)

    @discord.ui.button(label="⬆️ Supériorité", style=discord.ButtonStyle.gray)
    async def superiorite(self, interaction: discord.Interaction, button: discord.ui.Button):
        combat = self.cog.combats_en_cours[self.joueur_id]
        combat["superiorite"] = not combat["superiorite"]
        combat["inferiorite"] = False
        combat["bonus"]["superiorite"] = self.BONUS_POINTS["superiorite"] if combat["superiorite"] else 0
        combat["bonus"]["inferiorite"] = 0
        combat["points"] = sum(combat["bonus"].values())
        await self.update_embed(combat)
        await interaction.response.defer()

    @discord.ui.button(label="⬇️ Infériorité", style=discord.ButtonStyle.gray)
    async def inferiorite(self, interaction: discord.Interaction, button: discord.ui.Button):
        combat = self.cog.combats_en_cours[self.joueur_id]
        combat["inferiorite"] = not combat["inferiorite"]
        combat["superiorite"] = False
        combat["bonus"]["inferiorite"] = self.BONUS_POINTS["inferiorite"] if combat["inferiorite"] else 0
        combat["bonus"]["superiorite"] = 0
        combat["points"] = sum(combat["bonus"].values())
        await self.update_embed(combat)
        await interaction.response.defer()

    # Validation joueur
    @discord.ui.button(label="✅ Valider combat", style=discord.ButtonStyle.green)
    async def valider_combat(self, interaction: discord.Interaction, button: discord.ui.Button):
        combat = self.cog.combats_en_cours[self.joueur_id]

        # Check screens
        if len(combat["screens"]) == 0:
            await interaction.response.send_message("❌ Tu dois ajouter au moins un screen pour valider le combat.", ephemeral=True)
            return

        # Désactive tous les boutons
        for child in self.children:
            child.disabled = True
        await combat["message"].edit(view=self)

        # Envoie le message au rôle ladder avec bouton de validation ladder
        ladder_view = ValidationLadderView(self.cog, self.joueur_id)
        role = interaction.guild.get_role(LADDER_ROLE_ID)
        embed = self._build_ladder_embed(combat)

        await interaction.response.send_message(
            content=f"{role.mention} un combat a été ajouté, merci de valider ⏳",
            embed=embed,
            view=ladder_view,
            allowed_mentions=discord.AllowedMentions(roles=True)
        )

        # Le joueur n'a plus son combat en cours
        del self.cog.combats_en_cours[self.joueur_id]

    def _build_ladder_embed(self, combat):
        points_lines = []
        if combat['bonus']['attaque'] > 0:
            points_lines.append(f"🗡️ Attaque : +{combat['bonus']['attaque']} pts")
        if combat['bonus']['defense'] > 0:
            points_lines.append(f"🛡️ Défense : +{combat['bonus']['defense']} pts")
        if combat['bonus']['aucun_mort'] > 0:
            points_lines.append(f"☠️ Aucun mort : +{combat['bonus']['aucun_mort']} pts")
        if combat['bonus']['superiorite'] != 0 or combat['bonus']['inferiorite'] != 0:
            val = combat['bonus']['superiorite'] + combat['bonus']['inferiorite']
            points_lines.append(f"⚖️ Supériorité / Infériorité : {val:+} pts")

        embed = discord.Embed(
            title="📊 Combat à valider par le ladder",
            description="Détails du combat :",
            color=0x57F287
        )
        embed.add_field(
            name="👥 Joueurs présents",
            value=", ".join([m.mention for m in combat["joueurs_present"]])
        )
        embed.add_field(name="💠 Détail des points", value="\n".join(points_lines) if points_lines else "—")
        embed.add_field(name="💰 Total points", value=f"{combat['points']} pts")
        if combat['screens']:
            embed.add_field(name="🖼️ Screens", value="\n".join(combat['screens']), inline=False)
        embed.set_footer(text=f"Combat ajouté le {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        return embed

    async def set_type(self, interaction: discord.Interaction, combat_type: str):
        combat = self.cog.combats_en_cours[self.joueur_id]
        combat["type"] = combat_type
        combat["bonus"]["attaque" if combat_type == "Attaque" else "defense"] = self.BONUS_POINTS[combat_type.lower()]
        combat["points"] = sum(combat["bonus"].values())
        await self.update_embed(combat)
        await interaction.response.defer()

    async def update_embed(self, combat):
        points_lines = []
        if combat['bonus']['attaque'] > 0:
            points_lines.append(f"🗡️ Attaque : +{combat['bonus']['attaque']} pts")
        if combat['bonus']['defense'] > 0:
            points_lines.append(f"🛡️ Défense : +{combat['bonus']['defense']} pts")
        if combat['bonus']['aucun_mort'] > 0:
            points_lines.append(f"☠️ Aucun mort : +{combat['bonus']['aucun_mort']} pts")
        if combat['bonus']['superiorite'] != 0 or combat['bonus']['inferiorite'] != 0:
            val = combat['bonus']['superiorite'] + combat['bonus']['inferiorite']
            points_lines.append(f"⚖️ Supériorité / Infériorité : {val:+} pts")

        embed = discord.Embed(
            title="📊 Ajout d’un combat au ladder purgatoire",
            description="Validation en attente ⏳",
            color=0x5865F2
        )
        embed.add_field(
            name="👥 Joueurs présents",
            value=", ".join([m.mention for m in combat["joueurs_present"]])
        )
        embed.add_field(name="💠 Points du combat", value="\n".join(points_lines) if points_lines else "—")
        embed.add_field(name="💰 Points par joueur", value=f"{combat['points']} pts")
        embed.add_field(name="🖼️ Screens ajoutés", value=f"{len(combat['screens'])} / {MAX_SCREENS}")
        await combat["message"].edit(embed=embed, view=combat["view"])


# ---------------------------
# Vue de validation par ladder
# ---------------------------
class ValidationLadderView(discord.ui.View):
    def __init__(self, cog, joueur_id):
        super().__init__(timeout=None)
        self.cog = cog
        self.joueur_id = joueur_id

    @discord.ui.button(label="✅ Valider le combat", style=discord.ButtonStyle.green)
    async def valider(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Vérifie le rôle ladder
        roles_ids = [role.id for role in interaction.user.roles]
        if LADDER_ROLE_ID not in roles_ids:
            await interaction.response.send_message("❌ Seuls les membres du rôle ladder peuvent valider.", ephemeral=True)
            return

        # Récupère les infos du joueur et envoie message public
        combat_data = self.cog.combats_en_cours.get(self.joueur_id)
        if combat_data is None:
            await interaction.response.send_message("❌ Combat déjà validé ou introuvable.", ephemeral=True)
            return

        # Mettre à jour leaderboard (exemple fictif, à connecter au cog Leaderboard)
        leaderboard_cog = self.cog.bot.get_cog("LeaderboardCog")
        if leaderboard_cog:
            # Suppose qu'on prend le dernier leaderboard créé
            if leaderboard_cog.leaderboards:
                lb = list(leaderboard_cog.leaderboards.values())[-1]
                for member in combat_data["joueurs_present"]:
                    lb["classement"][member.id] = lb["classement"].get(member.id, 0) + combat_data["points"]

        # Message public de validation
        await interaction.channel.send(
            f"✅ Combat envoyé par {interaction.user.mention} à {datetime.now().strftime('%H:%M')} validé par le ladder."
        )

        # Désactive le bouton
        button.disabled = True
        await interaction.message.edit(view=self)

        # Supprime le combat du stockage
        if self.joueur_id in self.cog.combats_en_cours:
            del self.cog.combats_en_cours[self.joueur_id]


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