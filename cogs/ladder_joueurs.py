import discord
from discord.ext import commands
from discord import app_commands
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

# =============================
# CONFIG
# =============================
LADDER_ROLE_ID = 1459190410835660831
DATA_FILE = "data/ladder.json"
META_FILE = "data/ladder_meta.json"
TZ = ZoneInfo("Europe/Paris")


# =============================
# UTILS
# =============================
def current_period():
    now = datetime.now(TZ)
    if now.day < 15:
        return f"{now.year}-{now.month:02d}-01_14"
    return f"{now.year}-{now.month:02d}-15_end"


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
# VIEWS
# =============================
class ActionView(discord.ui.View):
    def __init__(self, bot, target: discord.Member, validator: discord.Member):
        super().__init__(timeout=300)
        self.bot = bot
        self.target = target
        self.validator = validator

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.validator.id

    @discord.ui.button(label="➕ Ajouter des points", style=discord.ButtonStyle.success)
    async def add_points(self, interaction: discord.Interaction, _):
        await interaction.response.send_message(
            f"Entre le nombre de points à **AJOUTER** pour {self.target.display_name}",
            ephemeral=True,
        )
        self.bot.pending_manual[self.validator.id] = {
            "target": self.target,
            "action": "add",
            "channel": interaction.channel,
        }

    @discord.ui.button(label="➖ Enlever des points", style=discord.ButtonStyle.danger)
    async def remove_points(self, interaction: discord.Interaction, _):
        await interaction.response.send_message(
            f"Entre le nombre de points à **ENLEVER** pour {self.target.display_name}",
            ephemeral=True,
        )
        self.bot.pending_manual[self.validator.id] = {
            "target": self.target,
            "action": "remove",
            "channel": interaction.channel,
        }


# =============================
# COG
# =============================
class LadderJoueur(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        if not hasattr(bot, "pending_manual"):
            bot.pending_manual = {}

    # -------------------------
    # /joueur
    # -------------------------
    @app_commands.command(
        name="joueur",
        description="Ajouter ou enlever des points à un joueur (manuel)",
    )
    async def joueur(self, interaction: discord.Interaction):
        if not any(r.id == LADDER_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message(
                "❌ Accès refusé.",
                ephemeral=True,
            )
            return

        view = discord.ui.View(timeout=300)
        view.add_item(
            discord.ui.UserSelect(
                placeholder="Sélectionne un joueur…",
                min_values=1,
                max_values=1,
            )
        )

        await interaction.response.send_message(
            "Choisis le joueur à modifier :",
            view=view,
            ephemeral=True,
        )

    # -------------------------
    # UserSelect
    # -------------------------
    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if not interaction.data:
            return

        if interaction.data.get("component_type") != 5:
            return

        if not interaction.guild or not interaction.user:
            return

        if not any(r.id == LADDER_ROLE_ID for r in interaction.user.roles):
            return

        target_id = int(interaction.data["values"][0])
        target = interaction.guild.get_member(target_id)
        if not target:
            await interaction.response.send_message(
                "❌ Joueur introuvable.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"Action à effectuer pour **{target.display_name}** :",
            view=ActionView(self.bot, target, interaction.user),
            ephemeral=True,
        )

    # -------------------------
    # Saisie du nombre
    # -------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        user_id = message.author.id
        if user_id not in self.bot.pending_manual:
            return

        try:
            amount = int(message.content.strip())
            if amount <= 0:
                raise ValueError
        except ValueError:
            await message.channel.send(
                "❌ Merci d’entrer un **nombre entier positif**."
            )
            return

        ctx = self.bot.pending_manual.pop(user_id)
        target = ctx["target"]
        action = ctx["action"]
        channel = ctx["channel"]

        data = load_json(DATA_FILE)
        meta = load_json(META_FILE)
        period = current_period()

        if period not in data:
            data[period] = {}

        uid = str(target.id)
        current = data[period].get(uid, 0)

        if action == "add":
            new_score = current + amount
            delta = f"+{amount}"
        else:
            new_score = max(0, current - amount)
            delta = f"-{amount}"

        data[period][uid] = new_score

        meta.setdefault("manual_logs", []).append({
            "date": datetime.now(TZ).isoformat(),
            "period": period,
            "player": target.display_name,
            "delta": delta,
            "validator": message.author.display_name,
        })

        save_json(DATA_FILE, data)
        save_json(META_FILE, meta)

        recap = (
            "🧾 **Récap Ladder — Modification manuelle**\n"
            f"Joueur : {target.display_name}\n"
            f"Action : {delta} points\n"
            f"Validé par : {message.author.display_name}"
        )

        await channel.send(recap)

        leaderboard = self.bot.get_cog("LadderLeaderboard")
        if leaderboard:
            await leaderboard.update_leaderboard()

        await message.delete()


async def setup(bot: commands.Bot):
    await bot.add_cog(LadderJoueur(bot))