import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

LEADERBOARD_CHANNEL_ID = 1459185721461051422
DATA_FILE = "data/ladder.json"
META_FILE = "data/ladder_meta.json"
TZ = ZoneInfo("Europe/Paris")


def current_period(now=None):
    if not now:
        now = datetime.now(TZ)

    start_day = 1 if now.day < 15 else 15
    start = now.replace(day=start_day, hour=0, minute=0, second=0, microsecond=0)

    if start_day == 1:
        end = start.replace(day=14, hour=23, minute=59, second=59)
    else:
        next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        end = next_month - timedelta(seconds=1)

    key = f"{start.strftime('%Y-%m-%d')}__{end.strftime('%Y-%m-%d')}"
    label = f"{start.strftime('%d %B %Y')} → {end.strftime('%d %B %Y')}"

    return key, label, start, end


def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


class LadderLeaderboard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.message_id = None
        self.check_reset.start()

    def build_embed(self, period_key, period_label, scores):
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:20]

        desc = "\n".join(
            f"{i+1}. <@{uid}> — {pts} pts"
            for i, (uid, pts) in enumerate(sorted_scores)
        ) or "Aucun point pour cette période."

        embed = discord.Embed(
            title="LADDER GÉNÉRAL PVP",
            description=desc,
            color=discord.Color.gold(),
        )

        embed.set_footer(text=f"Période : {period_label}")
        return embed

    async def update_leaderboard(self):
        data = load_json(DATA_FILE)
        period_key, period_label, _, _ = current_period()
        scores = data.get(period_key, {})

        embed = self.build_embed(period_key, period_label, scores)
        channel = self.bot.get_channel(LEADERBOARD_CHANNEL_ID)
        if not isinstance(channel, discord.TextChannel):
            return

        if self.message_id:
            try:
                msg = await channel.fetch_message(self.message_id)
                await msg.edit(embed=embed)
                return
            except discord.NotFound:
                self.message_id = None

        msg = await channel.send(embed=embed)
        self.message_id = msg.id

    @tasks.loop(minutes=1)
    async def check_reset(self):
        now = datetime.now(TZ)
        meta = load_json(META_FILE)
        data = load_json(DATA_FILE)

        period_key, period_label, start, _ = current_period(now)

        last_frozen = meta.get("last_frozen")
        if last_frozen == period_key:
            return

        if now == start:
            previous_key, previous_label, _, _ = current_period(start - timedelta(minutes=1))
            scores = data.get(previous_key)

            if scores:
                channel = self.bot.get_channel(LEADERBOARD_CHANNEL_ID)
                if channel:
                    embed = self.build_embed(previous_key, previous_label, scores)
                    await channel.send("📌 **Classement figé de la période**", embed=embed)

            meta["last_frozen"] = period_key
            save_json(META_FILE, meta)

    @check_reset.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="ladder", description="Afficher le ladder actuel")
    async def ladder(self, interaction: discord.Interaction):
        data = load_json(DATA_FILE)
        period_key, period_label, _, _ = current_period()
        scores = data.get(period_key, {})
        embed = self.build_embed(period_key, period_label, scores)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(LadderLeaderboard(bot))