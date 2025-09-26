import discord
from discord.ext import commands

from storage import (
    add_participant,
    incr_leaderboard,
    decr_leaderboard,
    set_outcome,
    set_incomplete,
    try_claim_first_defender,
)
from .alerts import build_ping_embed, EMOJI_VICTORY, EMOJI_DEFEAT, EMOJI_INCOMP, EMOJI_JOIN, AddDefendersButtonView
from .leaderboard import update_leaderboards

TARGET_EMOJIS = {EMOJI_VICTORY, EMOJI_DEFEAT, EMOJI_INCOMP, EMOJI_JOIN}

class ReactionsCog(commands.Cog):
    """MAJ via réactions sur les messages d’alerte (embed + leaderboards) + apparition du bouton ajouter défenseurs."""

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
        channel = guild.get_channel(payload.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        try:
            msg = await channel.fetch_message(payload.message_id)
        except discord.NotFound:
            return

        # ne traiter que les messages d'alerte du bot
        if msg.author.id != self.bot.user.id:
            return

        # Gestion participants + leaderboard pour 👍
        if emoji_str == EMOJI_JOIN and payload.user_id != self.bot.user.id:
            if is_add:
                inserted = add_participant(msg.id, payload.user_id, payload.user_id, "reaction")
                if inserted:
                    incr_leaderboard(guild.id, "defense", payload.user_id)

                # Tentative de claim "premier défenseur" -> ajoute le bouton si OK
                if try_claim_first_defender(msg.id, payload.user_id):
                    # ajoute la vue avec le bouton sur le message
                    try:
                        await msg.edit(view=AddDefendersButtonView(self.bot, msg.id))
                    except Exception:
                        pass

            else:
                # suppression du pouce -> on enlève la participation et décrémente
                # (optionnel : seulement si l'entrée venait d'une réaction ; on garde simple)
                try:
                    # on ne sait pas si c'était button ou reaction; par simplicité on décrémente si existait
                    decr_leaderboard(guild.id, "defense", payload.user_id)
                except Exception:
                    pass

        # Recalcule l'état global via les réactions présentes
        reactions = {str(r.emoji): r.count for r in msg.reactions}
        win_count = reactions.get(EMOJI_VICTORY, 0)
        loss_count = reactions.get(EMOJI_DEFEAT, 0)
        incomp_count = reactions.get(EMOJI_INCOMP, 0)

        if win_count > 0 and loss_count == 0:
            set_outcome(msg.id, "win")
        elif loss_count > 0 and win_count == 0:
            set_outcome(msg.id, "loss")
        else:
            set_outcome(msg.id, None)

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
