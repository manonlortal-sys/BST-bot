import discord
from discord.ext import commands
from discord import app_commands
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

LEADERBOARD_CHANNEL_ID = 1459185721461051422
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

    def build_embed(self) -> discord.Embed:
        scores = {}

        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r") as f:
                data = json.load(f)
            scores = data.get(current_period(), {})

        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:20]

        desc = "\n".join(
            f"{i+1}. <@{uid}> — {pts} pts"
            for i, (uid, pts) in enumerate(sorted_scores)
        ) or "Aucun point pour cette période."

        return discord.Embed(
            title="LADDER GÉNÉRAL PVP",
            description=desc,
            color=discord.Color.gold(),
        )

    async def update_leaderboard(self):
        channel = self.bot.get_channel(LEADERBOARD_CHANNEL_ID)
        if not isinstance(channel, discord.TextChannel):
            return

        embed = self.build_embed()

        if self.message_id:
            try:
                msg = await channel.fetch_message(self.message_id)
                await msg.edit(embed=embed)
                return
            except discord.NotFound:
                self.message_id = None

        msg = await channel.send(embed=embed)
        self.message_id = msg.id

    # =============================
    # /ladder
    # =============================
    @app_commands.command(name="ladder", description="Afficher le ladder actuel")
    async def ladder(self, interaction: discord.Interaction):
        embed = self.build_embed()
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(LadderLeaderboard(bot))