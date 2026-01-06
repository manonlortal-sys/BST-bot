import discord
from discord.ext import commands
from discord import app_commands
import uuid

CAFARD_ROLE_ID = 1449031629753286726

cafards = {}   # cafard_id -> data
votes = {}     # (cafard_id, user_id) -> bool
points = {}    # user_id -> int
pending = {}   # user_id -> temp cafard


class CafardCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="cafard", description="Créer un cafard")
    async def cafard(self, interaction: discord.Interaction, question: str):
        pending[interaction.user.id] = {
            "question": question,
            "answer": None
        }

        view = discord.ui.View(timeout=120)

        async def choose(inter: discord.Interaction, value: bool):
            if inter.user.id != interaction.user.id:
                await inter.response.send_message("❌ Interaction non autorisée", ephemeral=True)
                return

            pending[interaction.user.id]["answer"] = value
            await inter.response.edit_message(
                content=f"⚠️ **Validation du cafard**\n\n"
                        f"**Question :**\n{question}\n\n"
                        f"**Bonne réponse :** {'Oui' if value else 'Non'}",
                view=ValidationView(interaction.user.id)
            )

        async def cancel(inter: discord.Interaction):
            if inter.user.id == interaction.user.id:
                pending.pop(interaction.user.id, None)
                await inter.response.send_message("❌ Création annulée", ephemeral=True)

        view.add_item(discord.ui.Button(label="Oui", style=discord.ButtonStyle.success,
                                        callback=lambda i: choose(i, True)))
        view.add_item(discord.ui.Button(label="Non", style=discord.ButtonStyle.danger,
