import discord
from discord.ext import commands
from discord import app_commands
import uuid

CAFARD_ROLE_ID = 1449031629753286726

cafards = {}
votes = {}
points = {}
pending = {}


class CafardCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ---------- /CAFARD ----------
    @app_commands.command(name="cafard", description="Créer un cafard")
    async def cafard(self, interaction: discord.Interaction, question: str):
        pending[interaction.user.id] = {"question": question}

        await interaction.response.send_message(
            f"🪳 **Création d’un cafard**\n\n"
            f"**Question :**\n{question}\n\n"
            f"Pour être un cafard, il faut répondre :",
            ephemeral=True,
            view=AnswerSelectView(interaction.user.id)
        )

    # ---------- /CLASSEMENT ----------
    @app_commands.command(name="classement", description="Classement des cafards")
    async def classement(self, interaction: discord.Interaction):
        if not points:
            await interaction.response.send_message("🪳 Aucun point pour l’instant")
            return

        sorted_points = sorted(points.items(), key=lambda x: x[1], reverse=True)
        lines = []
        for i, (uid, pts) in enumerate(sorted_points, start=1):
            user = self.bot.get_user(uid)
            name = user.display_name if user else str(uid)
            lines.append(f"{i}️⃣ {name} — {pts} 🪳")

        await interaction.response.send_message(
            "🏆 **Classement des cafards**\n\n" + "\n".join(lines)
        )


# ================= VIEWS =================

class AnswerSelectView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=120)
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    @discord.ui.button(label="Oui", style=discord.ButtonStyle.success)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._select(interaction, True)

    @discord.ui.button(label="Non", style=discord.ButtonStyle.danger)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._select(interaction, False)

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        pending.pop(self.user_id, None)
        await interaction.response.edit_message(content="❌ Création annulée", view=None)

    async def _select(self, interaction: discord.Interaction, value: bool):
        pending[self.user_id]["answer"] = value
        await interaction.response.edit_message(
            content=(
                "⚠️ **Validation du cafard**\n\n"
                f"**Question :**\n{pending[self.user_id]['question']}\n\n"
                f"**Bonne réponse :** {'Oui' if value else 'Non'}"
            ),
            view=ValidationView(self.user_id)
        )


class ValidationView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=120)
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    @discord.ui.button(label="Valider", style=discord.ButtonStyle.success)
    async def validate(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = pending.pop(self.user_id)
        cafard_id = str(uuid.uuid4())
        cafards[cafard_id] = data

        role = interaction.guild.get_role(CAFARD_ROLE_ID)

        await interaction.channel.send(
            f"🪳 {role.mention}\n\n**{data['question']}**\n\nVotez une seule fois 👇",
            view=VoteView(cafard_id)
        )

        await interaction.response.edit_message(content="✅ Cafard publié", view=None)

    @discord.ui.button(label="Modifier", style=discord.ButtonStyle.primary)
    async def modify(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("↩️ Relance `/cafard`", ephemeral=True)

    @discord.ui.button(label="Supprimer", style=discord.ButtonStyle.danger)
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        pending.pop(self.user_id, None)
        await interaction.response.edit_message(content="❌ Cafard supprimé", view=None)


class VoteView(discord.ui.View):
    def __init__(self, cafard_id):
        super().__init__(timeout=None)
        self.cafard_id = cafard_id

    async def _vote(self, interaction: discord.Interaction, value: bool):
        key = (self.cafard_id, interaction.user.id)
        if key in votes:
            await interaction.response.send_message("❌ Tu as déjà voté", ephemeral=True)
            return

        votes[key] = value
        correct = cafards[self.cafard_id]["answer"] == value

        if correct:
            points[interaction.user.id] = points.get(interaction.user.id, 0) + 1
            await interaction.response.send_message("🎉 Bonne réponse ! +1 🪳", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Mauvaise réponse", ephemeral=True)

    @discord.ui.button(label="Oui", style=discord.ButtonStyle.success)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._vote(interaction, True)

    @discord.ui.button(label="Non", style=discord.ButtonStyle.danger)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._vote(interaction, False)


async def setup(bot):
    await bot.add_cog(CafardCog(bot))
