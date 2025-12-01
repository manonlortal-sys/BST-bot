from __future__ import annotations

import discord
from discord.ext import commands
from discord import app_commands

from .utils import ROLE_ADMIN_ID, PING_BUTTON_EMOJI_ID


class PingPanelView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="Ping!",
        style=discord.ButtonStyle.danger,
        emoji=discord.PartialEmoji(name="pingemoji", id=PING_BUTTON_EMOJI_ID),
    )
    async def ping_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        alerts_cog = self.bot.get_cog("Alerts")  # type: ignore
        if not alerts_cog:
            return await interaction.response.send_message(
                "Système d'alertes indisponible.", ephemeral=True
            )

        await alerts_cog.handle_ping_button(interaction, is_test=False)  # type: ignore

    @discord.ui.button(
        label="Test",
        style=discord.ButtonStyle.primary,
        emoji="⚠️",
    )
    async def test_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        # Seuls les admins peuvent cliquer
        if not isinstance(interaction.user, discord.Member) or not any(
            r.id == ROLE_ADMIN_ID for r in interaction.user.roles
        ):
            return await interaction.response.send_message(
                "Ce bouton est réservé aux administrateurs.", ephemeral=True
            )

        alerts_cog = self.bot.get_cog("Alerts")  # type: ignore
        if not alerts_cog:
            return await interaction.response.send_message(
                "Système d'alertes indisponible.", ephemeral=True
            )

        await alerts_cog.handle_ping_button(interaction, is_test=True)  # type: ignore


class PingPanel(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.checks.has_role(ROLE_ADMIN_ID)
    @app_commands.command(
        name="ping",
        description="Afficher le panel d'alerte défense percepteurs.",
    )
    async def ping_command(self, interaction: discord.Interaction):
        """Affiche le panneau de ping défense percepteurs."""
        view = PingPanelView(self.bot)

        embed = discord.Embed(
            title="🚨 ALERTE DÉFENSE PERCEPTEURS 🚨",
            description='📣 Clique sur le bouton "Ping!" pour générer une alerte de défense percepteurs !',
            color=discord.Color.red(),
        )

        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(PingPanel(bot))
