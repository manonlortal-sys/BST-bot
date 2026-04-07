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
            title="📊 Ajout d’un combat au ladder purgatoire",
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
            "bonus": {"aucun_mort": 0, "attaque": 0, "defense": 0, "superiorite": 0, "inferiorite": 0},
            "message": message,
            "view": view,
            "screens": [],
        }


# ---------------- VIEW COMBAT ----------------

class CombatView(discord.ui.View):
    BONUS_POINTS = {"aucun_mort": 3, "attaque": 5, "defense": 5, "superiorite": -2, "inferiorite": 3}

    def __init__(self, cog, joueur_id):
        super().__init__(timeout=None)
        self.cog = cog
        self.joueur_id = joueur_id

    @discord.ui.button(label="🗡️ Attaque", style=discord.ButtonStyle.red)
    async def attaque(self, interaction: discord.Interaction, button: discord.ui.Button):
        combat = self.cog.combats_en_cours[self.joueur_id]
        combat["bonus"]["attaque"] = 5
        combat["points"] = sum(combat["bonus"].values())
        await self.update_embed(combat)
        await interaction.response.defer()

    @discord.ui.button(label="🛡️ Défense", style=discord.ButtonStyle.red)
    async def defense(self, interaction: discord.Interaction, button: discord.ui.Button):
        combat = self.cog.combats_en_cours[self.joueur_id]
        combat["bonus"]["defense"] = 5
        combat["points"] = sum(combat["bonus"].values())
        await self.update_embed(combat)
        await interaction.response.defer()

    @discord.ui.button(label="☠️ Aucun mort", style=discord.ButtonStyle.gray)
    async def aucun_mort(self, interaction: discord.Interaction, button: discord.ui.Button):
        combat = self.cog.combats_en_cours[self.joueur_id]
        combat["bonus"]["aucun_mort"] = 3 if combat["bonus"]["aucun_mort"] == 0 else 0
        combat["points"] = sum(combat["bonus"].values())
        await self.update_embed(combat)
        await interaction.response.defer()

    @discord.ui.button(label="⬆️ Supériorité", style=discord.ButtonStyle.gray)
    async def superiorite(self, interaction: discord.Interaction, button: discord.ui.Button):
        combat = self.cog.combats_en_cours[self.joueur_id]
        combat["bonus"]["superiorite"] = -2
        combat["bonus"]["inferiorite"] = 0
        combat["points"] = sum(combat["bonus"].values())
        await self.update_embed(combat)
        await interaction.response.defer()

    @discord.ui.button(label="⬇️ Infériorité", style=discord.ButtonStyle.gray)
    async def inferiorite(self, interaction: discord.Interaction, button: discord.ui.Button):
        combat = self.cog.combats_en_cours[self.joueur_id]
        combat["bonus"]["inferiorite"] = 3
        combat["bonus"]["superiorite"] = 0
        combat["points"] = sum(combat["bonus"].values())
        await self.update_embed(combat)
        await interaction.response.defer()

    @discord.ui.button(label="🖼️ Ajouter screen(s)", style=discord.ButtonStyle.gray)
    async def screens(self, interaction: discord.Interaction, button: discord.ui.Button):
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
    async def valider(self, interaction: discord.Interaction, button: discord.ui.Button):
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
        embed = discord.Embed(title="📊 Ajout d’un combat au ladder purgatoire", color=0x5865F2)
        embed.add_field(name="👥 Joueurs", value=", ".join([m.mention for m in combat["joueurs_present"]]))
        embed.add_field(name="💰 Points", value=f"{combat['points']} pts")
        embed.add_field(name="🖼️ Screens", value=f"{len(combat['screens'])}/{MAX_SCREENS}")
        await combat["message"].edit(embed=embed, view=combat["view"])


# ---------------- VIEW LADDER ----------------

class ValidationLadderView(discord.ui.View):
    def __init__(self, cog, combat):
        super().__init__(timeout=None)
        self.cog = cog
        self.combat = combat

    @discord.ui.button(label="✅ Valider le combat", style=discord.ButtonStyle.green)
    async def valider(self, interaction: discord.Interaction, button: discord.ui.Button):
        roles_ids = [r.id for r in interaction.user.roles]
        if LADDER_ROLE_ID not in roles_ids:
            await interaction.response.send_message("❌ Pas autorisé", ephemeral=True)
            return

        leaderboard_cog = self.cog.bot.get_cog("LeaderboardCog")
        if not leaderboard_cog or not leaderboard_cog.leaderboards:
            await interaction.response.send_message("❌ Aucun leaderboard actif", ephemeral=True)
            return

        leaderboard = list(leaderboard_cog.leaderboards.values())[-1]

        for joueur in self.combat["joueurs_present"]:
            leaderboard["classement"][joueur.id] = leaderboard["classement"].get(joueur.id, 0) + self.combat["points"]

        classement = sorted(leaderboard["classement"].items(), key=lambda x: x[1], reverse=True)

        texte = ""
        for i, (uid, pts) in enumerate(classement, 1):
            texte += f"{i}. <@{uid}> — {pts} pts\n"

        embed = leaderboard["message"].embeds[0]
        embed.set_field_at(0, name="🏆 Classement", value=texte or "—", inline=False)

        await leaderboard["message"].edit(embed=embed)

        self.clear_items()
        await interaction.response.edit_message(view=self)

# ---------------- SETUP ----------------

async def setup(bot):
    await bot.add_cog(CombatCog(bot))