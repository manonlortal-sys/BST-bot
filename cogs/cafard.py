import discord
from discord.ext import commands
from discord import app_commands
import uuid

cafards = {}     # cafard_id -> {question, answer}
votes = {}       # (cafard_id, user_id) -> bool
points = {}      # user_id -> int
pending = {}     # user_id -> temp cafard


class CafardCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ================= /CAFARD =================
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

    # ================= /QUIZ =================
    @app_commands.command(name="quiz", description="Répondre aux cafards non faits")
    async def quiz(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        remaining = [cid for cid in cafards if (cid, user_id) not in votes]

        if not remaining:
            await interaction.response.send_message(
                "🎉 Tu as répondu à tous les cafards disponibles !",
                ephemeral=True
            )
            return

        view = QuizView(user_id, remaining)
        cid = remaining[0]

        await interaction.response.send_message(
            f"🪳 **Quiz cafard**\n\n"
            f"**Question 1 / {len(remaining)}**\n"
            f"{cafards[cid]['question']}",
            ephemeral=True,
            view=view
        )

    # ================= /CLASSEMENT =================
    @app_commands.command(name="classement", description="Classement des cafards (Top 10)")
    async def classement(self, interaction: discord.Interaction):
        if not points:
            await interaction.response.send_message("🪳 Aucun point pour l’instant")
            return

        sorted_points = sorted(points.items(), key=lambda x: x[1], reverse=True)[:10]
        lines = []

        for i, (uid, pts) in enumerate(sorted_points, start=1):
            try:
                user = self.bot.get_user(uid) or await self.bot.fetch_user(uid)
                name = user.display_name
            except:
                name = f"Utilisateur {uid}"

            lines.append(f"{i}. {name} — {pts} 🪳")

        await interaction.response.send_message(
            "🏆 **Classement des cafards (Top 10)**\n\n" + "\n".join(lines)
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

        await interaction.channel.send(
            f"🪳 **{data['question']}**\n\nVotez une seule fois 👇",
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


class QuizView(discord.ui.View):
    def __init__(self, user_id, cafard_ids):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.cafard_ids = cafard_ids
        self.index = 0

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    async def _answer(self, interaction: discord.Interaction, value: bool):
        cid = self.cafard_ids[self.index]
        votes[(cid, self.user_id)] = value

        correct = cafards[cid]["answer"] == value
        if correct:
            points[self.user_id] = points.get(self.user_id, 0) + 1
            feedback = "🎉 Bonne réponse ! +1 🪳"
        else:
            feedback = "❌ Mauvaise réponse"

        self.index += 1

        if self.index >= len(self.cafard_ids):
            await interaction.response.edit_message(
                content=f"🏁 **Quiz terminé !**\n\n{feedback}",
                view=None
            )
            return

        next_cid = self.cafard_ids[self.index]
        await interaction.response.edit_message(
            content=(
                f"{feedback}\n\n"
                f"🪳 **Quiz cafard**\n\n"
                f"**Question {self.index + 1} / {len(self.cafard_ids)}**\n"
                f"{cafards[next_cid]['question']}"
            ),
            view=self
        )

    @discord.ui.button(label="Oui", style=discord.ButtonStyle.success)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._answer(interaction, True)

    @discord.ui.button(label="Non", style=discord.ButtonStyle.danger)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._answer(interaction, False)


async def setup(bot):
    await bot.add_cog(CafardCog(bot))
