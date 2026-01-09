import discord
from discord.ext import commands
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

DATA_FILE = "data/ladder.json"
TZ = ZoneInfo("Europe/Paris")


def current_period():
    now = datetime.now(TZ)
    if now.day < 15:
        return f"{now.year}-{now.month:02d}-01_14"
    return f"{now.year}-{now.month:02d}-15_end"


class LadderWorkflow(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -------------------------
    # Utils
    # -------------------------
    def load_data(self):
        if not os.path.exists(DATA_FILE):
            return {}
        with open(DATA_FILE, "r") as f:
            return json.load(f)

    def save_data(self, data):
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=2)

    # -------------------------
    # Validation finale screen
    # -------------------------
    async def apply_points(
        self,
        interaction: discord.Interaction,
        players: list[int],
        points: int,
    ):
        data = self.load_data()
        period = current_period()

        if period not in data:
            data[period] = {}

        for uid in players:
            uid = str(uid)
            data[period][uid] = data[period].get(uid, 0) + points

        self.save_data(data)

        # ✅ CORRECTION CRITIQUE : UPDATE DU LADDER
        leaderboard = interaction.client.get_cog("LadderLeaderboard")
        if leaderboard:
            await leaderboard.update_leaderboard()

        # recap
        names = []
        for uid in players:
            user = interaction.guild.get_member(uid)
            names.append(user.display_name if user else str(uid))

        recap = (
            "🧾 Récap Ladder\n"
            f"Type : victoire / défense\n"
            f"Configuration : {points} pts\n"
            f"Joueurs : {', '.join(names)}\n"
            f"Validé par : {interaction.user.display_name}"
        )

        await interaction.channel.send(recap)


async def setup(bot: commands.Bot):
    await bot.add_cog(LadderWorkflow(bot))