import discord
from discord.ext import commands

# =============================
# CONFIG
# =============================
SCREEN_CHANNELS = {
    1326667338636066931,
    1459153753587449948,
}

LADDER_ROLE_ID = 1459190410835660831


class ScreenValidationView(discord.ui.View):
    def __init__(self, bot: commands.Bot, screen_message: discord.Message):
        super().__init__(timeout=None)
        self.bot = bot
        self.screen_message = screen_message
        self.locked = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return any(r.id == LADDER_ROLE_ID for r in interaction.user.roles)

    def _disable_buttons(self):
        for item in self.children:
            item.disabled = True

    @discord.ui.button(label="Valider", style=discord.ButtonStyle.success)
    async def validate(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.locked:
            await interaction.response.send_message(
                "⛔ Validation déjà en cours.",
                ephemeral=True,
            )
            return

        # ✅ ACK immédiat obligatoire
        await interaction.response.defer(ephemeral=True)

        self.locked = True
        self._disable_buttons()
        await interaction.message.edit(view=self)

        workflow = self.bot.get_cog("LadderWorkflow")
        if not workflow:
            await interaction.followup.send(
                "❌ Workflow ladder introuvable.",
                ephemeral=True,
            )
            return

        # 🔗 Lancement du workflow
        await workflow.start(interaction, self.screen_message)

    @discord.ui.button(label="Refuser", style=discord.ButtonStyle.danger)
    async def refuse(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.locked:
            await interaction.response.send_message(
                "⛔ Ce screen est déjà traité.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        self.locked = True
        self._disable_buttons()
        await interaction.message.edit(view=self)

        await interaction.followup.send(
            "❌ Screen refusé.",
            ephemeral=True,
        )


class LadderScreens(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.seen_messages: set[int] = set()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignorer messages du bot
        if message.author.bot:
            return

        # Ignorer hors canaux ladder
        if message.channel.id not in SCREEN_CHANNELS:
            return

        # Anti-doublon strict
        if message.id in self.seen_messages:
            return
        self.seen_messages.add(message.id)

        # Détection image
        has_image = False

        for attachment in message.attachments:
            if attachment.content_type and attachment.content_type.startswith("image/"):
                has_image = True
                break

        if not has_image:
            for embed in message.embeds:
                if embed.type == "image":
                    has_image = True
                    break

        if not has_image:
            return

        # Message de validation
        await message.channel.send(
            f"<@&{LADDER_ROLE_ID}> merci de valider ce screen",
            view=ScreenValidationView(self.bot, message),
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(LadderScreens(bot))