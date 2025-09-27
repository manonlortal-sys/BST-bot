# cogs/deletions.py
import discord
from discord.ext import commands

from storage import (
    is_tracked_message,
    delete_message_cascade,
    decr_leaderboard,
)
from .leaderboard import update_leaderboards

class DeletionsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        # On n'a pas l'objet message, donc on travaille via payload
        # Si ce n'est pas un message suivi, on ignore
        if not is_tracked_message(payload.message_id):
            return

        # Récupère guild
        guild = self.bot.get_guild(payload.guild_id) if payload.guild_id else None
        if guild is None:
            return

        # Supprime en DB et récupère les IDs à décrémenter
        creator_id, participants = delete_message_cascade(payload.message_id)

        # Décrémente les compteurs
        try:
            if creator_id:
                decr_leaderboard(guild.id, "pingeur", creator_id)
            for uid in participants:
                decr_leaderboard(guild.id, "defense", uid)
        except Exception:
            pass

        # Rafraîchit les leaderboards
        try:
            await update_leaderboards(self.bot, guild)
        except Exception:
            pass

async def setup(bot: commands.Bot):
    await bot.add_cog(DeletionsCog(bot))
