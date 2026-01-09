import discord
from discord.ext import commands

LADDER_ROLE_ID = 1459190410835660831


class ScreenValidationView(discord.ui.View):
    def __init__(self, bot, screen_message: discord.Message):
        super().__init__(timeout=None)
        self.bot = bot
        self.screen_message = screen_message
        self.locked = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return any(r.id == LADDER_ROLE_ID for r in interaction.user.roles)

    @discord.ui.button(label="Valider", style=discord.ButtonStyle.success)
    async def validate(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.locked:
            await interaction.response.send_message(
                "⛔ Validation déjà en cours.", ephemeral=True
            )
            return

        self.locked = True
        self.disable_all_items()
        await interaction.message.edit(view=self)

        await interaction.response.send_message(
            "✅ Screen validé. Lancement de la validation…",
            ephemeral=True,
        )

        workflow = self.bot.get_cog("LadderWorkflow")
        if not workflow:
            await interaction.followup.send(
                "❌ Workflow ladder introuvable.", ephemeral=True
            )
            return

        # 👉 APPEL MANQUANT AVANT (BUG)
        await workflow.start(interaction, self.screen_message)

    @discord.ui.button(label="Refuser", style=discord.ButtonStyle.danger)
    async def refuse(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.disable_all_items()
        await interaction.message.edit(view=self)

        await interaction.response.send_message(
            "❌ Screen refusé.",
            ephemeral=True,
        )


class LadderScreens(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        if not message.attachments:
            return

        if not any(
            att.content_type and att.content_type.startswith("image")
            for att in message.attachments
        ):
            return

        channel_ids = {
            1326667338636066931,
            1459153753587449948,
        }

        if message.channel.id not in channel_ids:
            return

        role_mention = f"<@&{LADDER_ROLE_ID}>"

        await message.channel.send(
            f"{role_mention} merci de valider ce screen",
            view=ScreenValidationView(self.bot, message),
        )


async def setup(bot):
    await bot.add_cog(LadderScreens(bot))