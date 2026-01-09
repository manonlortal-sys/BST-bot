import discord
from discord.ext import commands
from discord import app_commands
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# =============================
# CONFIG
# =============================
CHANNEL_LADDER_ID = 1459185721461051422
DATA_FILE = "data/ladder.json"
META_FILE = "data/ladder_meta.json"
TZ = ZoneInfo("Europe/Paris")

MOIS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre"
]


# =============================
# UTILS
# =============================
def current_period():
    now = datetime.now(TZ)
    if now.day < 15:
        return f"{now.year}-{now.month:02d}-01_14"
    return f"{now.year}-{now.month:02d}-15_end"


def period_label(period: str) -> str:
    year, month, span = period.split("-")
    month_i = int(month)
    mois = MOIS_FR[month_i - 1]

    if span == "01_14":
        start = f"1er {mois} {year}"
        end = f"14 {mois} {year}"
    else:
        start = f"15 {mois} {year}"
        if month_i == 12:
            last_day = 31
        else:
            next_month = datetime(int(year), month_i + 1, 1, tzinfo=TZ)
            last_day = (next_month - timedelta(days=1)).day
        end = f"{last_day} {mois} {year}"

    return f"Période : du {start} au {end}"


def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# =============================
# COG
# =============================
class LadderLeaderboard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.message_id: int | None = None
        self._load_message_id()

    # -------------------------
    # Persistance message_id
    # -------------------------
    def _load_message_id(self):
        meta = load_json(META_FILE)
        self.message_id = meta.get("message_id")

    def _save_message_id(self):
        save_json(META_FILE, {"message_id": self.message_id})

    # -------------------------
    # Embed
    # -------------------------
    def build_embed(self):
        data = load_json(DATA_FILE)
        period = current_period()
        scores = data.get(period, {})

        embed = discord.Embed(
            title="🏆 LADDER GÉNÉRAL PVP 🏆",
            color=discord.Color.gold()
        )

        embed.set_footer(text=period_label(period))

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
    # Message ladder
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
        self._save_message_id()

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

        await msg.edit(embed=self.build_embed())

    # -------------------------
    # /ladder
    # -------------------------
    @app_commands.command(name="ladder", description="Afficher le ladder actuel")
    async def ladder(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            embed=self.build_embed()
        )

    # -------------------------
    # Events
    # -------------------------
    @commands.Cog.listener()
    async def on_ready(self):
        await self.ensure_message()
        await self.update_leaderboard()


async def setup(bot: commands.Bot):
    await bot.add_cog(LadderLeaderboard(bot))