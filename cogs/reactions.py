from __future__ import annotations

import discord
from discord.ext import commands

from .utils import get_state


class Reactions(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None:
            return
        if payload.user_id == self.bot.user.id:
            return

        state = get_state(self.bot)
        if payload.message_id not in state.alerts:
            return

        emoji_str = str(payload.emoji)

        alerts_cog = self.bot.get_cog("Alerts")  # type: ignore
        if not alerts_cog:
            return

        # 👍 => défenseur
        if emoji_str == "👍":
            await alerts_cog.add_defender_to_alert(payload.message_id, payload.user_id)  # type: ignore

        # 🏆 => victoire
        elif emoji_str == "🏆":
            await alerts_cog.mark_defense_won(payload.message_id)  # type: ignore

        # ❌ => défaite
        elif emoji_str == "❌":
            await alerts_cog.mark_defense_lost(payload.message_id)  # type: ignore

        # 😡 => incomplète
        elif emoji_str == "😡":
            await alerts_cog.toggle_incomplete(payload.message_id)  # type: ignore


async def setup(bot: commands.Bot):
    await bot.add_cog(Reactions(bot))

