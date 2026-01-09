import discord
from discord.ext import commands
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

CHANNEL_LADDER_ID = 1459185721461051422
DATA_FILE = "data/ladder.json"
TZ = ZoneInfo("Europe/Paris")


def current_period():
    now = datetime.now(TZ)
    if now.day < 15:
        return f"{now.year}-{now.month:02d}-01_14"
    return f"{now.year}-{now.month:02d}-15_end"


class LadderLeaderboard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.message_id: int | None = None

    # -------------------------
    # Utils JSON
    # -------------------------
    def load_data(self):
        if not os.path.exists(DATA_FILE):
            return {}
        with open(DATA_FILE, "r") as f:
            return json.load(f)

    # -------------------------
    # Embed
    # -------------------------
    def build_embed(self):
        data = self.load_data()
        period = current_period()
        scores = data.get(period, {})

        embed = discord.Embed(
            title="LADDER GÉNÉRAL PVP",
            color=discord.Color.gold()
        )

        start, end = (
            (1, 14) if "01_14" in period else (15, "fin")
        )
        embed.set_footer(
            text=f"Période : {start} → {end}"
        )

        if not scores:
            embed.description = "Aucun point pour cette période."
            return embed

        sorted_scores = sorted(
            scores.items(),
            key=lambda x: x[1],
            reverse=True
        )[:20]

        lines = []
        for i, (uid, pts) in enumerate(sorted_scores, start=1):
            user = self.bot.get_user(int(uid))
            name = user.display_name if user else f"Utilisateur {uid}"
            lines.append(f"{i}. {name} — {pts} pts")

        embed.description = "\n".join(lines)
        return embed

    # -------------------------
    # Message management
    # -------------------------
    async def ensure_message(self):
        channel = self.bot.get_channel(CHANNEL_LADDER_ID)
        if not channel:
            return

        if self.message_id:
            try:
                await channel.fetch_message(self.message_id)
                return
            except discord.NotFound:
                self.message_id = None

        embed = self.build_embed()
        msg = await channel.send(embed=embed)
        self.message_id = msg.id

    async def update_leaderboard(self):
        channel = self.bot.get_channel(CHANNEL_LADDER_ID)
        if not channel:
            return

        await self.ensure_message()
        if not self.message_id:
            return

        try:
            msg = await channel.fetch_message(self.message_id)
        except discord.NotFound:
            self.message_id = None
            await self.ensure_message()
            return

        embed = self.build_embed()
        await msg.edit(embed=embed)

    # -------------------------
    # Events
    # -------------------------
    @commands.Cog.listener()
    async def on_ready(self):
        await self.ensure_message()
        await self.update_leaderboard()


async def setup(bot: commands.Bot):
    await bot.add_cog(LadderLeaderboard(bot))