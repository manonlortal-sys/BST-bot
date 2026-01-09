import discord
from discord.ext import commands
import json
import os
from datetime import datetime

CHANNEL_ID = 1459185721461051422
DATA_FILE = "data/ladder.json"

def current_period():
    now = datetime.utcnow()
    if now.day < 15:
        return f"{now.year}-{now.month:02d}-01_14"
    return f"{now.year}-{now.month:02d}-15_end"

class LadderLeaderboard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.message_id = None

    async def update_leaderboard(self):
        if not os.path.exists(DATA_FILE):
            return

        with open(DATA_FILE) as f:
            data = json.load(f)

        period = current_period()
        scores = data.get(period, {})
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:20]

        desc = "\n".join(
            f"{i+1}. <@{uid}> — {pts} pts"
            for i, (uid, pts) in enumerate(sorted_scores)
        ) or "Aucun point"

        embed = discord.Embed(
            title="LADDER GÉNÉRAL PVP",
            description=desc,
            color=discord.Color.gold(),
        )

        channel = self.bot.get_channel(CHANNEL_ID)
        if not channel:
            return

        if self.message_id:
            msg = await channel.fetch_message(self.message_id)
            await msg.edit(embed=embed)
        else:
            msg = await channel.send(embed=embed)
            self.message_id = msg.id

async def setup(bot):
    await bot.add_cog(LadderLeaderboard(bot))