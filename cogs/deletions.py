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
    """Met à jour les stats/leaderboards quand une alerte est supprimée."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _handle_deleted_message(self, message_id: int, guild_id: int | None):
        # Vérifie que c'est une alerte suivie
        if not is_tracked_message(message_id):
            return

        info = get_message_info(message_id)
        if not info:
            return
        msg_guild_id, creator_id = info

        # Priorité à msg_guild_id depuis la DB
        gid = msg_guild_id or guild_id
        if gid is None:
            return

        # Décrémenter pingeur si connu
        if creator_id is not None:
            decr_leaderboard(gid, "pingeur", creator_id)

        # Décrémenter toutes les défenses liées
        for uid in get_participants_ids(message_id):
            decr_leaderboard(gid, "defense", uid)

        # Supprimer la trace en DB (participants + message)
        delete_message_cascade(message_id)

        # Rafraîchir les leaderboards
        guild = self.bot.get_guild(gid)
        if guild is not None:
            try:
                await update_leaderboards(self.bot, guild)
            except Exception:
                pass

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        await self._handle_deleted_message(payload.message_id, payload.guild_id)

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent):
        for mid in payload.message_ids:
            await self._handle_deleted_message(mid, payload.guild_id)

async def setup(bot: commands.Bot):
    await bot.add_cog(DeletionsCog(bot))
