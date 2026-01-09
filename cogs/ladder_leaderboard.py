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


def period_dates(period: str):
    year, month, span = period.split("-")
    year = int(year)
    month = int(month)
    mois = MOIS_FR[month - 1]

    if span == "01_14":
        start = f"1er {mois} {year}"
        end = f"14 {mois} {year}"
    else:
        start = f"15 {mois} {year}"

        # calcul du dernier jour du mois (FIABLE)
        if month == 12:
            next_month = datetime(year + 1, 1, 1, tzinfo=TZ)
        else:
            next_month = datetime(year, month + 1, 1, tzinfo=TZ)

        last_day = (next_month - timedelta(days=1)).day
        end = f"{last_day} {mois} {year}"

    return start, end


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
        self.last_period: str | None = None
        self._load_meta()

    # -------------------------
    # META
    # -------------------------
    def _load_meta(self):
        meta = load_json(META_FILE)
        self.message_id = meta.get("message_id")
        self.last_period = meta.get("last_period")

    def _save_meta(self):
        save_json(META_FILE, {
            "message_id": self.message_id,
            "last_period": self.last_period,
        })

    # -------------------------
    # EMBED
    # -------------------------
    def build_embed(self, period: str, limit: int | None = 20, title_override: str | None = None):
        data = load_json(DATA_FILE)
        scores = data.get(period, {})

        start, end = period_dates(period)

        title = title_override or "🏆 LADDER GÉNÉRAL PVP 🏆"

        embed = discord.Embed(
            title=title,
            color=discord.Color.gold()
        )

        embed.set_footer(text=f"Période : du {start} au {end}")

        if not scores:
            embed.description = "Aucun point pour cette période."
            return embed

        sorted_scores = sorted(
            scores.items(),
            key=lambda x: x[1],
            reverse=True
        )

        if limit:
            sorted_scores = sorted_scores[:limit]

        lines = []
        for i, (uid, pts) in enumerate(sorted_scores, start=1):
            user = self.bot.get_user(int(uid))
            name = user.display_name if user else f"Utilisateur {uid}"
            lines.append(f"{i}. {name} — {pts} pts")

        embed.description = "\n".join(lines)
        return embed

    # -------------------------
    # FIGEAGE
    # -------------------------
    async def check_period_change(self):
        current = current_period()

        if self.last_period and self.last_period != current:
            channel = self.bot.get_channel(CHANNEL_LADDER_ID)
            if channel:
                start, end = period_dates(self.last_period)
                title = f"🏆 LADDER DU {start} AU {end} 🏆"
                frozen = self.build_embed(
                    self.last_period,
                    limit=None,
                    title_override=title
                )
                await channel.send(embed=frozen)

        self.last_period = current
        self._save_meta()

    # -------------------------
    # MESSAGE PERSISTANT
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

        msg = await channel.send(embed=self.build_embed(current_period()))
        self.message_id = msg.id
        self._save_meta()

    async def update_leaderboard(self):
        await self.check_period_change()

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

        await msg.edit(embed=self.build_embed(current_period()))

    # -------------------------
    # /ladder
    # -------------------------
    @app_commands.command(name="ladder", description="Afficher le ladder actuel")
    async def ladder(self, interaction: discord.Interaction):
        await self.check_period_change()
        await interaction.response.send_message(
            embed=self.build_embed(current_period())
        )

    # -------------------------
    # EVENTS
    # -------------------------
    @commands.Cog.listener()
    async def on_ready(self):
        await self.check_period_change()
        await self.ensure_message()
        await self.update_leaderboard()


async def setup(bot: commands.Bot):
    await bot.add_cog(LadderLeaderboard(bot))