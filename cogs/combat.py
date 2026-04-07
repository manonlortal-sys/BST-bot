# cogs/combat.py

import discord
from discord.ext import commands
from discord import app_commands
import asyncio

MAX_JOUEURS = 4
MAX_SCREENS = 5
LADDER_ROLE_ID = 1459190410835660831


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
                "❌ Tu as déjà un combat en cours.",
                ephemeral=True
            )
            return

        view = CombatView(self, joueur_id)

        embed = discord.Embed(
            title="📊 Ajout d’un combat au ladder",
            description="Validation en attente ⏳",
            color=0x5865F2
        )
        embed.add_field(name="👥 Joueurs présents", value=interaction.user.mention)
        embed.add_field(name="💠 Points du combat", value="—")
        embed.add_field(name="💰 Points par joueur", value="0 pts")
        embed.add_field(name="🖼️ Screens ajoutés", value="0 / 5")

        await interaction.response.send_message(embed=embed, view=view)
        message = await interaction.original_response()

        self.combats_en_cours[joueur_id] = {
            "joueurs_present": [interaction.user],
            "points": 0,
            "bonus": {
                "attaque": 0,
                "defense": 0,
                "aucun_mort": 0,
                "superiorite": 0,
                "inferiorite": 0
            },
            "message": message,
            "view": view,
            "screens": [],
        }


# ---------------- VIEW COMBAT ----------------

class CombatView(discord.ui.View):
    BONUS_POINTS = {
        "attaque": 5,
        "defense": 5,
        "aucun_mort": 3,
        "superiorite": -2,
        "inferiorite": 3
    }

    def __init__(self, cog, joueur_id):
        super().__init__(timeout=None)
        self.cog = cog
        self.joueur_id = joueur_id

    @discord.ui.button(label="🗡️ Attaque", style=discord.ButtonStyle.red)
    async def attaque(self, interaction, button):
        combat = self.cog.combats_en_cours[self.joueur_id]
        combat["bonus"]["attaque"] = 5
        combat["bonus"]["defense"] = 0
        combat["points"] = sum(combat["bonus"].values())
        await self.update_embed(combat)
        await interaction.response.defer()

    @discord.ui.button(label="🛡️ Défense", style=discord.ButtonStyle.red)
    async def defense(self, interaction, button):
        combat = self.cog.combats_en_cours[self.joueur_id]
        combat["bonus"]["defense"] = 5
        combat["bonus"]["attaque"] = 0
        combat["points"] = sum(combat["bonus"].values())
        await self.update_embed(combat)
        await interaction.response.defer()

    @discord.ui.button(label="☠️ Aucun mort", style=discord.ButtonStyle.gray)
    async def aucun_mort(self, interaction, button):
        combat = self.cog.combats_en_cours[self.joueur_id]
        combat["bonus"]["aucun_mort"] = 3 if combat["bonus"]["aucun_mort"] == 0 else 0
        combat["points"] = sum(combat["bonus"].values())
        await self.update_embed(combat)
        await interaction.response.defer()

    @discord.ui.button(label="⬆️ Supériorité", style=discord.ButtonStyle.gray)
    async def sup(self, interaction, button):
        combat = self.cog.combats_en_cours[self.joueur_id]
        combat["bonus"]["superiorite"] = -2
        combat["bonus"]["inferiorite"] = 0
        combat["points"] = sum(combat["bonus"].values())
        await self.update_embed(combat)
        await interaction.response.defer()

    @discord.ui.button(label="⬇️ Infériorité", style=discord.ButtonStyle.gray)
    async def inf(self, interaction, button):
        combat = self.cog.combats_en_cours[self.joueur_id]
        combat["bonus"]["inferiorite"] = 3
        combat["bonus"]["superiorite"] = 0
        combat["points"] = sum(combat["bonus"].values())
        await self.update_embed(combat)
        await interaction.response.defer()

    @discord.ui.button(label="➕ Ajouter joueurs", style=discord.ButtonStyle.blurple)
    async def add_players(self, interaction, button):
        view = AjouterJoueursView(self.cog, self.joueur_id)
        await interaction.response.send_message("Choisis les joueurs", view=view, ephemeral=True)

    @discord.ui.button(label="🖼️ Ajouter screen(s)", style=discord.ButtonStyle.gray)
    async def screens(self, interaction, button):
        combat = self.cog.combats_en_cours[self.joueur_id]

        def check(msg):
            return msg.author.id == self.joueur_id and msg.attachments

        await interaction.response.send_message("Envoie tes screens", ephemeral=True)

        try:
            msg = await self.cog.bot.wait_for("message", check=check, timeout=120)
        except:
            return

        for att in msg.attachments:
            if len(combat["screens"]) < MAX_SCREENS:
                combat["screens"].append(att.url)

        await self.update_embed(combat)

    @discord.ui.button(label="✅ Valider combat", style=discord.ButtonStyle.green)
    async def valider(self, interaction, button):
        combat = self.cog.combats_en_cours[self.joueur_id]
        role = interaction.guild.get_role(LADDER_ROLE_ID)

        embed = discord.Embed(title="📊 Combat terminé", color=0x57F287)
        embed.add_field(name="👥 Joueurs", value=", ".join([m.mention for m in combat["joueurs_present"]]))
        embed.add_field(name="💰 Points", value=f"{combat['points']} pts")

        if combat["screens"]:
            embed.add_field(name="🖼️ Screens", value="\n".join(combat["screens"]))

        await interaction.response.send_message(
            content=f"{role.mention} merci de valider le résultat du combat ⏳",
            embed=embed,
            view=ValidationLadderView(self.cog, combat),
            allowed_mentions=discord.AllowedMentions(roles=True)
        )

        del self.cog.combats_en_cours[self.joueur_id]

    async def update_embed(self, combat):
        points_lines = []
        if combat["bonus"]["attaque"]:
            points_lines.append(f"🗡️ Attaque : +5 pts")
        if combat["bonus"]["defense"]:
            points_lines.append(f"🛡️ Défense : +5 pts")
        if combat["bonus"]["aucun_mort"]:
            points_lines.append(f"☠️ Aucun mort : +3 pts")
        if combat["bonus"]["superiorite"]:
            points_lines.append(f"⚖️ Supériorité : -2 pts")
        if combat["bonus"]["inferiorite"]:
            points_lines.append(f"⚖️ Infériorité : +3 pts")

        embed = discord.Embed(
            title="📊 Ajout d’un combat au ladder",
            description="Validation en attente ⏳",
            color=0x5865F2
        )
        embed.add_field(name="👥 Joueurs", value=", ".join([m.mention for m in combat["joueurs_present"]]))
        embed.add_field(name="💠 Points du combat", value="\n".join(points_lines) if points_lines else "—")
        embed.add_field(name="💰 Points", value=f"{combat['points']} pts")
        embed.add_field(name="🖼️ Screens", value=f"{len(combat['screens'])}/{MAX_SCREENS}")

        await combat["message"].edit(embed=embed, view=combat["view"])


# ---------------- AJOUT JOUEURS ----------------

class AjouterJoueursView(discord.ui.View):
    def __init__(self, cog, joueur_id):
        super().__init__(timeout=300)
        self.add_item(JoueurSelect(cog, joueur_id))


class JoueurSelect(discord.ui.UserSelect):
    def __init__(self, cog, joueur_id):
        super().__init__(max_values=MAX_JOUEURS)
        self.cog = cog
        self.joueur_id = joueur_id

    async def callback(self, interaction):
        combat = self.cog.combats_en_cours[self.joueur_id]

        for m in self.values:
            if m not in combat["joueurs_present"] and len(combat["joueurs_present"]) < MAX_JOUEURS:
                combat["joueurs_present"].append(m)

        await interaction.response.edit_message(content="✅ Joueurs ajoutés", view=None)
        await combat["view"].update_embed(combat)


# ---------------- VALIDATION LADDER ----------------

class ValidationLadderView(discord.ui.View):
    def __init__(self, cog, combat):
        super().__init__(timeout=None)
        self.cog = cog
        self.combat = combat

    @discord.ui.button(label="✅ Valider le combat", style=discord.ButtonStyle.green)
    async def valider(self, interaction, button):
        roles_ids = [r.id for r in interaction.user.roles]
        if LADDER_ROLE_ID not in roles_ids:
            await interaction.response.send_message("❌ Pas autorisé", ephemeral=True)
            return

        leaderboard_cog = self.cog.bot.get_cog("LeaderboardCog")
        leaderboard = list(leaderboard_cog.leaderboards.values())[-1]

        for joueur in self.combat["joueurs_present"]:
            leaderboard["classement"][joueur.id] = leaderboard["classement"].get(joueur.id, 0) + self.combat["points"]

        classement = sorted(leaderboard["classement"].items(), key=lambda x: x[1], reverse=True)

        texte = "\n".join([f"{i+1}. <@{uid}> — {pts} pts" for i, (uid, pts) in enumerate(classement)])

        embed = leaderboard["message"].embeds[0]
        embed.set_field_at(0, name="🏆 Classement", value=texte or "—", inline=False)

        await leaderboard["message"].edit(embed=embed)

        self.clear_items()
        await interaction.response.edit_message(view=self)


# ---------------- SETUP ----------------

async def setup(bot):
    await bot.add_cog(CombatCog(bot))