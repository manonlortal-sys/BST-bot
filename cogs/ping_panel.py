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
        custom_id="panel_ping",
        emoji=discord.PartialEmoji(id=PING_BUTTON_EMOJI_ID),
    )
    async def ping_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        alerts_cog = self.bot.get_cog("Alerts")  # type: ignore
        if not alerts_cog:
            await interaction.response.send_message(
                "Système d'alertes indisponible.", ephemeral=True
            )
            return

        await alerts_cog.handle_ping_button(interaction, is_test=False)  # type: ignore

    @discord.ui.button(
        label="Test",
        style=discord.ButtonStyle.primary,
        custom_id="panel_test",
        emoji="⚠️",
    )
    async def test_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        # Vérification admin ici
        if not isinstance(interaction.user, discord.Member) or not any(
            r.id == ROLE_ADMIN_ID for r in interaction.user.roles
        ):
            await interaction.response.send_message(
                "Ce bouton est réservé aux administrateurs.", ephemeral=True
            )
            return

        alerts_cog = self.bot.get_cog("Alerts")  # type: ignore
        if not alerts_cog:
            await interaction.response.send_message(
                "Système d'alertes indisponible.", ephemeral=True
            )
            return

        await alerts_cog.handle_ping_button(interaction, is_test=True)  # type: ignore


class PingPanel(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.view = PingPanelView(bot)

        # Vue persistante pour que les boutons restent actifs
        bot.add_view(self.view)

        # 💡 Enregistrement explicite de la commande slash dans le CommandTree
        # (ce qui semble ne pas bien se faire automatiquement chez toi)
        self.bot.tree.add_command(self.ping_command)

    @app_commands.checks.has_role(ROLE_ADMIN_ID)
    @app_commands.command(
        name="ping",
        description="Afficher le panel d'alerte défense percepteurs.",
    )
    async def ping_command(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🚨 ALERTE DÉFENSE PERCEPTEURS 🚨",
            description='📣 Clique sur le bouton "Ping!" pour générer une alerte de défense percepteurs !',
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed, view=self.view)


async def setup(bot: commands.Bot):
    await bot.add_cog(PingPanel(bot))
