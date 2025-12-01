from __future__ import annotations

from typing import Optional, List, Tuple

import discord
from discord.ext import commands

from .utils import get_state, CHANNEL_LEADERBOARD_ID


class Leaderboard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def ensure_messages(self) -> None:
        state = get_state(self.bot)
        channel = self.bot.get_channel(CHANNEL_LEADERBOARD_ID)
        if not isinstance(channel, discord.TextChannel):
            return

        ping_msg: Optional[discord.Message] = None
        def_msg: Optional[discord.Message] = None

        # Réutiliser si on a déjà des IDs
        if state.leaderboard_ping_message_id:
            try:
                ping_msg = await channel.fetch_message(state.leaderboard_ping_message_id)
            except discord.HTTPException:
                ping_msg = None
        if state.leaderboard_def_message_id:
            try:
                def_msg = await channel.fetch_message(state.leaderboard_def_message_id)
            except discord.HTTPException:
                def_msg = None

        # Sinon, on essaie de les retrouver dans l'historique
        if not ping_msg or not def_msg:
            async for msg in channel.history(limit=50):
                if msg.author.id != self.bot.user.id:
                    continue
                if not ping_msg and msg.content.startswith("🏆 Leaderboard Pings"):
                    ping_msg = msg
                elif not def_msg and msg.content.startswith("🛡️ Leaderboard Défenseurs"):
                    def_msg = msg
                if ping_msg and def_msg:
                    break

        # Sinon, on les crée
        if not ping_msg:
            ping_msg = await channel.send(
                "🏆 Leaderboard Pings\nAucune donnée pour le moment."
            )
        if not def_msg:
            def_msg = await channel.send(
                "🛡️ Leaderboard Défenseurs\nAucune donnée pour le moment."
            )

        state.leaderboard_ping_message_id = ping_msg.id
        state.leaderboard_def_message_id = def_msg.id

    async def update_leaderboards(self):
        state = get_state(self.bot)
        await self.ensure_messages()

        channel = self.bot.get_channel(CHANNEL_LEADERBOARD_ID)
        if not isinstance(channel, discord.TextChannel):
            return

        ping_msg = None
        def_msg = None

        try:
            ping_msg = await channel.fetch_message(state.leaderboard_ping_message_id)
        except Exception:
            pass
        try:
            def_msg = await channel.fetch_message(state.leaderboard_def_message_id)
        except Exception:
            pass

        # --- Leaderboard Ping ---

        ping_lines: List[str] = []

        ping_items: List[Tuple[int, int]] = [
            (uid, count)
            for uid, count in state.ping_counts.items()
            if count > 0
        ]
        ping_items.sort(key=lambda x: x[1], reverse=True)

        if not ping_items:
            ping_content = "🏆 Leaderboard Pings\nAucune donnée pour le moment."
        else:
            ping_lines.append("🏆 Leaderboard Pings")
            for idx, (user_id, count) in enumerate(ping_items, start=1):
                medal = ""
                if idx == 1:
                    medal = "🥇 "
                elif idx == 2:
                    medal = "🥈 "
                elif idx == 3:
                    medal = "🥉 "

                mention = f"<@{user_id}>"
                ping_lines.append(f"{medal}{mention} — {count} pings")

            ping_content = "\n".join(ping_lines)

        # --- Leaderboard Défenseurs ---

        def_lines: List[str] = []

        def_items: List[Tuple[int, int]] = [
            (uid, count)
            for uid, count in state.defense_counts.items()
            if count > 0
        ]
        def_items.sort(key=lambda x: x[1], reverse=True)

        if not def_items:
            def_content = "🛡️ Leaderboard Défenseurs\nAucune donnée pour le moment."
        else:
            def_lines.append("🛡️ Leaderboard Défenseurs")
            for idx, (user_id, count) in enumerate(def_items, start=1):
                medal = ""
                if idx == 1:
                    medal = "🥇 "
                elif idx == 2:
                    medal = "🥈 "
                elif idx == 3:
                    medal = "🥉 "

                mention = f"<@{user_id}>"
                def_lines.append(f"{medal}{mention} — {count} défenses")

            def_content = "\n".join(def_lines)

        if ping_msg:
            try:
                await ping_msg.edit(content=ping_content)
            except discord.HTTPException:
                pass

        if def_msg:
            try:
                await def_msg.edit(content=def_content)
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_ready(self):
        await self.update_leaderboards()

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        state = get_state(self.bot)
        changed = False
        if member.id in state.ping_counts:
            del state.ping_counts[member.id]
            changed = True
        if member.id in state.defense_counts:
            del state.defense_counts[member.id]
            changed = True

        if changed:
            await self.update_leaderboards()


async def setup(bot: commands.Bot):
    await bot.add_cog(Leaderboard(bot))
