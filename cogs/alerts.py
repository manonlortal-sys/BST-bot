import os
import discord
from discord.ext import commands

# Fonctions DB depuis storage.py
from storage import (
    upsert_message,
    incr_leaderboard,
)

# Rafraîchissement des leaderboards
from .leaderboard import update_leaderboards

# Fonction embed (on la garde ici pour l’instant)
from .embeds import build_ping_embed  # si tu veux isoler les embeds dans un fichier séparé


# ---------- ENV ----------
ALERT_CHANNEL_ID = int(os.getenv("ALERT_CHANNEL_ID", "0"))
ROLE_DEF_ID = int(os.getenv("ROLE_DEF_ID", "0"))
ROLE_DEF2_ID = int(os.getenv("ROLE_DEF2_ID", "0"))
ROLE_TEST_ID = int(os.getenv("ROLE_TEST_ID", "0"))
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", "0"))


# ---------- View boutons ----------
class PingButtonsView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def _handle_click(self, interaction: discord.Interaction, role_id: int):
        try:
            await interaction.response.defer(ephemeral=True, thinking=False)
        except Exception:
            pass

        guild = interaction.guild
        if guild is None or ALERT_CHANNEL_ID == 0:
            return
        alert_channel = guild.get_channel(ALERT_CHANNEL_ID)
        if not isinstance(alert_channel, discord.TextChannel):
            return

        role_mention = f"<@&{role_id}>" if role_id else ""
        content = f"{role_mention} — **Percepteur attaqué !** Merci de vous connecter." if role_mention else "**Percepteur attaqué !** Merci de vous connecter."

        msg = await alert_channel.send(content)
        upsert_message(
            msg.id,
            msg.guild.id,
            msg.channel.id,
            int(msg.created_at.timestamp()),
            creator_id=interaction.user.id
        )
        incr_leaderboard(interaction.guild.id, "pingeur", interaction.user.id)
        emb = await build_ping_embed(msg)
        try:
            await msg.edit(embed=emb)
        except Exception:
            pass

        await update_leaderboards(self.bot, guild)

        try:
            await interaction.followup.send("✅ Alerte envoyée.", ephemeral=True)
        except Exception:
            pass

    @discord.ui.button(
        label="Guilde 1",
        style=discord.ButtonStyle.primary,
        custom_id="pingpanel:def1"
    )
    async def btn_def(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_click(interaction, ROLE_DEF_ID)

    @discord.ui.button(
        label="Guilde 2",
        style=discord.ButtonStyle.danger,
        custom_id="pingpanel:def2"
    )
    async def btn_def2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_click(interaction, ROLE_DEF2_ID)

    @discord.ui.button(
        label="TEST (Admin)",
        style=discord.ButtonStyle.secondary,
        custom_id="pingpanel:test"
    )
    async def btn_test(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not any(r.id == ADMIN_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("Bouton réservé aux admins.", ephemeral=True)
            return
        await self._handle_click(interaction, ROLE_TEST_ID)


# ---------- Cog principal ----------
class AlertsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot


async def setup(bot: commands.Bot):
    await bot.add_cog(AlertsCog(bot))
