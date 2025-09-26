import os
import discord
from discord.ext import commands

# DB helpers
from storage import (
    add_participant,
    remove_participant,
    incr_leaderboard,
    decr_leaderboard,
    set_outcome,
    set_incomplete,
)

# Rebuild embed + refresh leaderboards
from .alerts import build_ping_embed, EMOJI_VICTORY, EMOJI_DEFEAT, EMOJI_INCOMP, EMOJI_JOIN
from .leaderboard import update_leaderboards


ALERT_CHANNEL_ID = int(os.getenv("ALERT_CHANNEL_ID", "0"))

TARGET_EMOJIS = {EMOJI_VICTORY, EMOJI_DEFEAT, EMOJI_INCOMP, EMOJI_JOIN}


class ReactionsCog(commands.Cog):
    """Gère les mises à jour via réactions sur les messages d’alerte."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _handle_reaction_event(self, payload: discord.RawReactionActionEvent, is_add: bool):
        # Filtrage salon + emoji
        if payload.guild_id is None or payload.channel_id != ALERT_CHANNEL_ID:
            return
        emoji_str = str(payload.emoji)
        if emoji_str not in TARGET_EMOJIS:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        channel = guild.get_channel(payload.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        try:
            msg = await channel.fetch_message(payload.message_id)
        except discord.NotFound:
            return

        # Ne traiter que les messages du bot (messages d'alerte)
        if msg.author.id != self.bot.user.id:
            return

        # 👍 → MAJ participants + leaderboard "defense"
        if emoji_str == EMOJI_JOIN and payload.user_id != self.bot.user.id:
            try:
                if is_add:
                    add_participant(msg.id, payload.user_id)
                    incr_leaderboard(guild.id, "defense", payload.user_id)
                else:
                    remove_participant(msg.id, payload.user_id)
                    decr_leaderboard(guild.id, "defense", payload.user_id)
            except Exception:
                # on ne crash pas sur une erreur DB ponctuelle
                pass

        # Recalcule l'état global à partir des réactions présentes
        reactions = {str(r.emoji): r.count for r in msg.reactions}

        win_count = reactions.get(EMOJI_VICTORY, 0)
        loss_count = reactions.get(EMOJI_DEFEAT, 0)
        incomp_count = reactions.get(EMOJI_INCOMP, 0)

        # outcome
        if win_count > 0 and loss_count == 0:
            set_outcome(msg.id, "win")
        elif loss_count > 0 and win_count == 0:
            set_outcome(msg.id, "loss")
        else:
            set_outcome(msg.id, None)

        # incomplete flag
        set_incomplete(msg.id, incomp_count > 0)

        # Rebuild embed + refresh leaderboards
        try:
            emb = await build_ping_embed(msg)
            await msg.edit(embed=emb)
        except Exception:
            pass

        try:
            await update_leaderboards(self.bot, guild)
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        # Ignore les réactions des bots
        if payload.user_id == self.bot.user.id:
            return
        await self._handle_reaction_event(payload, is_add=True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        # (payload.user_id est disponible ici aussi)
        if payload.user_id == self.bot.user.id:
            return
        await self._handle_reaction_event(payload, is_add=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(ReactionsCog(bot))
