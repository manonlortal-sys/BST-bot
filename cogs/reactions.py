# cogs/reactions.py
import os
import discord
from discord.ext import commands

from storage import (
    is_tracked_message,
    add_participant,
    remove_participant,
    set_outcome,
    set_incomplete,
)
from .leaderboard import update_leaderboards
from .alerts import build_ping_embed, AddDefendersButtonView

EMOJI_VICTORY = "🏆"
EMOJI_DEFEAT  = "❌"
EMOJI_INCOMP  = "😡"
EMOJI_JOIN    = "👍"

class ReactionsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # Ajout réaction
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return

        channel = guild.get_channel(payload.channel_id) or guild.get_thread(payload.channel_id)
        if channel is None:
            return
        try:
            msg = await channel.fetch_message(payload.message_id)
        except Exception:
            return

        if not is_tracked_message(payload.message_id):
            return

        emoji = str(payload.emoji)
        user = guild.get_member(payload.user_id)
        if user is None or user.bot:
            return

        changed = False

        if emoji == EMOJI_JOIN:
            # premier 👍 -> attacher la view si absente
            if not any(isinstance(i, discord.ui.Button) for i in msg.components[0].children) if msg.components else True:
                try:
                    await msg.edit(view=AddDefendersButtonView(self.bot, msg.id))
                except Exception:
                    pass
            if add_participant(payload.message_id, user.id, added_by=None, source="reaction"):
                changed = True

        elif emoji == EMOJI_VICTORY:
            set_outcome(payload.message_id, "win")
            changed = True
        elif emoji == EMOJI_DEFEAT:
            set_outcome(payload.message_id, "loss")
            changed = True
        elif emoji == EMOJI_INCOMP:
            set_incomplete(payload.message_id, True)
            changed = True

        if changed:
            try:
                emb = await build_ping_embed(msg)
                await msg.edit(embed=emb)
            except Exception:
                pass
            try:
                await update_leaderboards(self.bot, guild)
            except Exception:
                pass

    # Retrait réaction
    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return

        channel = guild.get_channel(payload.channel_id) or guild.get_thread(payload.channel_id)
        if channel is None:
            return
        try:
            msg = await channel.fetch_message(payload.message_id)
        except Exception:
            return

        if not is_tracked_message(payload.message_id):
            return

        emoji = str(payload.emoji)
        user_id = payload.user_id

        changed = False
        if emoji == EMOJI_JOIN:
            if remove_participant(payload.message_id, user_id):
                changed = True
        elif emoji == EMOJI_INCOMP:
            set_incomplete(payload.message_id, False)
            changed = True
        elif emoji in (EMOJI_VICTORY, EMOJI_DEFEAT):
            # On efface l'issue si on retire l'unique réaction ; par simplicité on remet None
            set_outcome(payload.message_id, None)
            changed = True

        if changed:
            try:
                emb = await build_ping_embed(msg)
                await msg.edit(embed=emb)
            except Exception:
                pass
            try:
                await update_leaderboards(self.bot, guild)
            except Exception:
                pass

async def setup(bot: commands.Bot):
    await bot.add_cog(ReactionsCog(bot))
