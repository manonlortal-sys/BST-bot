import discord
from discord.ext import commands

from storage import (
    add_participant,
    remove_participant,
    get_participant_entry,
    incr_leaderboard,
    decr_leaderboard,
    set_outcome,
    set_incomplete,
    get_first_defender,
)
from .alerts import (
    build_ping_embed,
    EMOJI_VICTORY, EMOJI_DEFEAT, EMOJI_INCOMP, EMOJI_JOIN,
    AddDefendersButtonView,
)
from .leaderboard import update_leaderboards

TARGET_EMOJIS = {EMOJI_VICTORY, EMOJI_DEFEAT, EMOJI_INCOMP, EMOJI_JOIN}


class ReactionsCog(commands.Cog):
    """Gère les réactions sur les messages d'alerte : participants (👍), état (🏆/❌/😡), embed & leaderboards."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _handle_reaction_event(self, payload: discord.RawReactionActionEvent, is_add: bool):
        if payload.guild_id is None:
            return

        emoji_str = str(payload.emoji)
        if emoji_str not in TARGET_EMOJIS:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return

        # Supporte TextChannel ET Thread
        channel = guild.get_channel(payload.channel_id) or guild.get_thread(payload.channel_id)
        if channel is None:
            return

        try:
            msg = await channel.fetch_message(payload.message_id)
        except discord.NotFound:
            return

        # Ne traiter que les messages d'alerte envoyés par le bot
        if msg.author.id != self.bot.user.id:
            return

        attach_add_defenders_view = False  # si True, on attachera la vue au prochain edit

        # ----- Gestion du 👍 -----
        if emoji_str == EMOJI_JOIN and payload.user_id != self.bot.user.id:
            if is_add:
                inserted = add_participant(msg.id, payload.user_id, payload.user_id, "reaction")
                if inserted:
                    incr_leaderboard(guild.id, "defense", payload.user_id)

                first_id = get_first_defender(msg.id)
                if first_id == payload.user_id:
                    attach_add_defenders_view = True
            else:
                entry = get_participant_entry(msg.id, payload.user_id)
                if entry:
                    added_by, source, _ = entry
                    if source == "reaction" and added_by == payload.user_id:
                        removed = remove_participant(msg.id, payload.user_id)
                        if removed:
                            decr_leaderboard(guild.id, "defense", payload.user_id)

        # ----- Recalcule l'état (🏆/❌/😡) -----
        reactions = {str(r.emoji): r.count for r in msg.reactions}
        win_count  = reactions.get(EMOJI_VICTORY, 0)
        loss_count = reactions.get(EMOJI_DEFEAT,  0)
        inc_count  = reactions.get(EMOJI_INCOMP,  0)

        if win_count > 0 and loss_count == 0:
            set_outcome(msg.id, "win")
        elif loss_count > 0 and win_count == 0:
            set_outcome(msg.id, "loss")
        else:
            set_outcome(msg.id, None)

        set_incomplete(msg.id, inc_count > 0)

        # ----- Rebuild embed + leaderboards -----
        try:
            emb = await build_ping_embed(msg)
            if attach_add_defenders_view:
                await msg.edit(embed=emb, view=AddDefendersButtonView(self.bot, msg.id))
            else:
                await msg.edit(embed=emb)
        except Exception:
            pass

        try:
            await update_leaderboards(self.bot, guild)
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return
        await self._handle_reaction_event(payload, is_add=True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return
        await self._handle_reaction_event(payload, is_add=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(ReactionsCog(bot))
