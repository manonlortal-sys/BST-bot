import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# =============================
# CONFIG
# =============================
CHANNEL_LADDER_ID = 1459185721461051422
LADDER_ROLE_ID = 1459190410835660831
LEAD_ROLE_ID = 1280235149191020625

DATA_FILE = "/var/data/ladder.json"
META_FILE = "/var/data/ladder_meta.json"
TZ = ZoneInfo("Europe/Paris")

MOIS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre"
]

# =============================
# UTILS
# =============================
def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return json.load(f)

def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def compute_period(now: datetime):
    if now.day < 15:
        return f"{now.year}-{now.month:02d}-01_14"
    return f"{now.year}-{now.month:02d}-15_end"

def period_dates(period: str):
    year, month, span = period.split("-")
    year, month = int(year), int(month)
    mois = MOIS_FR[month - 1]

    if span == "01_14":
        return f"1er {mois} {year}", f"14 {mois} {year}"

    if month == 12:
        next_month = datetime(year + 1, 1, 1, tzinfo=TZ)
    else:
        next_month = datetime(year, month + 1, 1, tzinfo=TZ)

    last_day = (next_month - timedelta(days=1)).day
    return f"15 {mois} {year}", f"{last_day} {mois} {year}"

# =============================
# COG
# =============================
class LadderLeaderboard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.message_id = None
        self.active_period = None
        self._load_meta()
        self.period_task.start()

    # -------------------------
    # META
    # -------------------------
    def _load_meta(self):
        meta = load_json(META_FILE)
        self.message_id = meta.get("message_id")
        self.active_period = meta.get("active_period")

        if not self.active_period:
            self.active_period = compute_period(datetime.now(TZ))
            self._save_meta()

    def _save_meta(self):
        save_json(META_FILE, {
            "message_id": self.message_id,
            "active_period": self.active_period,
        })

    # -------------------------
    # EMBEDS
    # -------------------------
    def build_embed(self, period: str, title_override=None):
        data = load_json(DATA_FILE)
        scores = data.get(period, {})

        start, end = period_dates(period)
        title = title_override or "🏆 LADDER GÉNÉRAL PVP 🏆"

        embed = discord.Embed(title=title, color=discord.Color.gold())
        embed.set_footer(text=f"Période : du {start} au {end}")

        if not scores:
            embed.description = "Aucun point pour cette période."
            return embed

        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        lines = []
        for i, (uid, pts) in enumerate(sorted_scores, start=1):
            user = self.bot.get_user(int(uid))
            name = user.display_name if user else f"Utilisateur {uid}"
            lines.append(f"{i}. {name} — {pts} pts")

        embed.description = "\n".join(lines)
        return embed

    # -------------------------
    # RECOMPENSES
    # -------------------------
    def build_rewards_message(self, period: str):
        data = load_json(DATA_FILE)
        scores = data.get(period, {})
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        start, end = period_dates(period)
        lines = [
            f"🏆 **RÉCOMPENSES LADDER PVP**",
            f"**Période : du {start} au {end}**\n"
        ]

        for i, (uid, _) in enumerate(sorted_scores[:24], start=1):
            mention = f"<@{uid}>"
            if i <= 3:
                reward = "3 percepteurs"
            elif i <= 10:
                reward = "2 percepteurs"
            else:
                reward = "1 percepteur"

            lines.append(f"**{i}e** — {mention} → {reward}")

        lines.append("")
        lines.append(f"<@&{LEAD_ROLE_ID}>")
        lines.append(
            "Merci d’attribuer un percepteur :\n"
            "- au meilleur PvM de la période\n"
            "- au contrôleur perco\n"
            "- au compteur ladder\n"
        )
        lines.append(
            "⚠️ **Merci de lever vos percepteurs dans les 24h pour faire de la place aux joueurs de la période. "
            "À défaut, vos percepteurs seront levés et les ressources intégrées au coffre guilde.**"
        )

        return "\n".join(lines)

    # -------------------------
    # PERIOD TASK
    # -------------------------
    @tasks.loop(minutes=1)
    async def period_task(self):
        now = datetime.now(TZ)
        current = compute_period(now)

        if current == self.active_period:
            return

        channel = self.bot.get_channel(CHANNEL_LADDER_ID)
        if not channel:
            return

        # 1️⃣ Ladder figé
        frozen_embed = self.build_embed(
            self.active_period,
            title_override=f"🏆 LADDER DU {period_dates(self.active_period)[0]} AU {period_dates(self.active_period)[1]} 🏆"
        )
        await channel.send(embed=frozen_embed)

        # 2️⃣ Récompenses
        await channel.send(self.build_rewards_message(self.active_period))

        # 3️⃣ Reset
        self.active_period = current
        self._save_meta()
        await self.update_leaderboard()

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

        msg = await channel.send(embed=self.build_embed(self.active_period))
        self.message_id = msg.id
        self._save_meta()

    async def update_leaderboard(self):
        await self.ensure_message()
        channel = self.bot.get_channel(CHANNEL_LADDER_ID)
        if not channel or not self.message_id:
            return

        msg = await channel.fetch_message(self.message_id)
        await msg.edit(embed=self.build_embed(self.active_period))

    # -------------------------
    # COMMANDES
    # -------------------------
    @app_commands.command(name="ladder", description="Afficher le ladder actuel")
    async def ladder(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=self.build_embed(self.active_period))

    @app_commands.command(name="recompenses", description="Envoyer les récompenses du ladder")
    async def recompenses(self, interaction: discord.Interaction):
        if not any(r.id in (LADDER_ROLE_ID, LEAD_ROLE_ID) for r in interaction.user.roles):
            await interaction.response.send_message("Accès refusé.", ephemeral=True)
            return

        await interaction.response.send_message(
            self.build_rewards_message(self.active_period)
        )

    @commands.Cog.listener()
    async def on_ready(self):
        await self.ensure_message()
        await self.update_leaderboard()


async def setup(bot: commands.Bot):
    await bot.add_cog(LadderLeaderboard(bot))