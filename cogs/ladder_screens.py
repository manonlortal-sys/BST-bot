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

# Verrou global anti-doublon
SEEN_MESSAGES = set()

# screen_message_id -> state
SCREEN_STATES = {}  # pending | validated | refused


class ValidationView(discord.ui.View):
    def __init__(self, screen_message_id: int):
        super().__init__(timeout=None)
        self.screen_message_id = screen_message_id

    def has_permission(self, interaction: discord.Interaction) -> bool:
        return any(r.id == LADDER_ROLE_ID for r in interaction.user.roles)

    @discord.ui.button(label="Valider", style=discord.ButtonStyle.success)
    async def validate(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.has_permission(interaction):
            await interaction.response.send_message(
                "Tu n’as pas le rôle Ladder.",
                ephemeral=True,
            )
            return

        if SCREEN_STATES.get(self.screen_message_id) != "pending":
            await interaction.response.send_message(
                "Ce screen est déjà traité.",
                ephemeral=True,
            )
            return

        SCREEN_STATES[self.screen_message_id] = "validated"

        await interaction.response.send_message(
            "Screen validé. (Étape suivante à venir)",
            ephemeral=True,
        )

    @discord.ui.button(label="Refuser", style=discord.ButtonStyle.danger)
    async def refuse(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.has_permission(interaction):
            await interaction.response.send_message(
                "Tu n’as pas le rôle Ladder.",
                ephemeral=True,
            )
            return

        if SCREEN_STATES.get(self.screen_message_id) != "pending":
            await interaction.response.send_message(
                "Ce screen est déjà traité.",
                ephemeral=True,
            )
            return

        SCREEN_STATES[self.screen_message_id] = "refused"

        await interaction.response.send_message(
            "Screen refusé.",
            ephemeral=True,
        )


class LadderScreens(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # 🔒 ignorer messages du bot
        if message.author.bot:
            return

        # 🔒 verrou immédiat anti-doublon (CRITIQUE)
        if message.id in SEEN_MESSAGES:
            return
        SEEN_MESSAGES.add(message.id)

        # 🔒 ignorer hors canaux ladder
        if message.channel.id not in SCREEN_CHANNELS:
            return

        # 🔒 déjà traité
        if message.id in SCREEN_STATES:
            return

        # 🔍 détection image
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

        # ✅ screen détecté
        SCREEN_STATES[message.id] = "pending"

        await message.channel.send(
            f"<@&{LADDER_ROLE_ID}> merci de valider ce screen",
            view=ValidationView(message.id),
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(LadderScreens(bot))