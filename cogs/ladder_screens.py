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


class ValidationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Valider", style=discord.ButtonStyle.success)
    async def validate(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not any(r.id == LADDER_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message(
                "Tu n’as pas le rôle requis pour valider.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "Validation lancée (étape suivante à venir).",
            ephemeral=True,
        )

    @discord.ui.button(label="Refuser", style=discord.ButtonStyle.danger)
    async def refuse(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not any(r.id == LADDER_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message(
                "Tu n’as pas le rôle requis pour refuser.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "Screen refusé.",
            ephemeral=True,
        )


class LadderScreens(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        if message.channel.id not in SCREEN_CHANNELS:
            return

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

        await message.channel.send(
            f"<@&{LADDER_ROLE_ID}> merci de valider ce screen",
            view=ValidationView(),
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(LadderScreens(bot))