# cogs/deletions.py
import discord
from discord.ext import commands

from storage import (
    is_tracked_message,
    get_message_info,
    get_participants_ids,
    decr_leaderboard,
    delete_message_cascade,
)
from .leaderboard import update_leaderboards

class DeletionsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener("on_raw_message_delete")
    async def handle_alert_delete(self, payload: discord.RawMessageDeleteEvent):
        msg_id = payload.message_id

        if not is_tracked_message(msg_id):
            return

        info = get_message_info(msg_id)
        if info is None:
            return
        guild_id, _channel_id, _team, creator_id = info

        participants = get_participants_ids(msg_id)

        # décrémentations
        for uid in participants:
            decr_leaderboard(guild_id, "defense", uid)
        if creator_id:
            decr_leaderboard(guild_id, "pingeur", creator_id)

        # suppression en DB
        delete_message_cascade(msg_id)

        # refresh leaderboard
        guild = self.bot.get_guild(guild_id)
        if guild:
            try:
                await update_leaderboards(self.bot, guild)
            except Exception:
                pass

async def setup(bot: commands.Bot):
    await bot.add_cog(DeletionsCog(bot))
