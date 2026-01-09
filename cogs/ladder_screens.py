import discord
from discord.ext import commands
from discord import app_commands

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
            await interaction.response.send_message("⛔ Validation déjà en cours.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        self.locked = True
        self._disable_buttons()
        await interaction.message.edit(view=self)

        workflow = self.bot.get_cog("LadderWorkflow")
        if not workflow:
            await interaction.followup.send("❌ Workflow ladder introuvable.", ephemeral=True)
            return

        await workflow.start(interaction, self.screen_message)

    @discord.ui.button(label="Refuser", style=discord.ButtonStyle.danger)
    async def refuse(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.locked:
            await interaction.response.send_message("⛔ Ce screen est déjà traité.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        self.locked = True
        self._disable_buttons()
        await interaction.message.edit(view=self)

        await interaction.followup.send("❌ Screen refusé.", ephemeral=True)


class LadderScreens(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.seen_messages: set[int] = set()

    def _is_image_message(self, message: discord.Message) -> bool:
        for att in message.attachments:
            if att.content_type and att.content_type.startswith("image/"):
                return True
        for emb in message.embeds:
            if emb.type == "image":
                return True
        return False

    async def _send_validation(self, channel: discord.TextChannel, message: discord.Message):
        await channel.send(
            f"<@&{LADDER_ROLE_ID}> merci de valider ce screen",
            view=ScreenValidationView(self.bot, message),
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if message.channel.id not in SCREEN_CHANNELS:
            return
        if message.id in self.seen_messages:
            return
        if not self._is_image_message(message):
            return

        self.seen_messages.add(message.id)
        await self._send_validation(message.channel, message)

    # =============================
    # /valider (manuel)
    # =============================
    @app_commands.command(name="valider", description="Envoyer manuellement la validation sur le dernier screen")
    async def manual_validate(self, interaction: discord.Interaction):
        if not any(r.id == LADDER_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)
            return

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("❌ Salon invalide.", ephemeral=True)
            return

        async for msg in channel.history(limit=20):
            if self._is_image_message(msg):
                await self._send_validation(channel, msg)
                await interaction.response.send_message("✅ Validation envoyée.", ephemeral=True)
                return

        await interaction.response.send_message("❌ Aucun screen trouvé récemment.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(LadderScreens(bot))