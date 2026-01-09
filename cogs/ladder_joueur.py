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
DATA_FILE = "/var/data/ladder.json"
META_FILE = "/var/data/ladder_meta.json"
TZ = ZoneInfo("Europe/Paris")

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

# =============================
# VIEW
# =============================
class ActionView(discord.ui.View):
    def __init__(self, bot, target, validator):
        super().__init__(timeout=300)
        self.bot = bot
        self.target = target
        self.validator = validator

    async def interaction_check(self, interaction):
        return interaction.user.id == self.validator.id

    @discord.ui.button(label="➕ Ajouter", style=discord.ButtonStyle.success)
    async def add(self, interaction, _):
        await interaction.response.send_message(
            f"Nombre de points à **ajouter** pour {self.target.display_name} :",
            ephemeral=True
        )
        self.bot.pending_manual[self.validator.id] = ("add", self.target)

    @discord.ui.button(label="➖ Enlever", style=discord.ButtonStyle.danger)
    async def remove(self, interaction, _):
        await interaction.response.send_message(
            f"Nombre de points à **enlever** pour {self.target.display_name} :",
            ephemeral=True
        )
        self.bot.pending_manual[self.validator.id] = ("remove", self.target)

# =============================
# COG
# =============================
class LadderJoueur(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        if not hasattr(bot, "pending_manual"):
            bot.pending_manual = {}

    @app_commands.command(name="joueur", description="Modifier manuellement un joueur")
    async def joueur(self, interaction: discord.Interaction):
        if not any(r.id == LADDER_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("Accès refusé.", ephemeral=True)
            return

        view = discord.ui.View()
        view.add_item(discord.ui.UserSelect(min_values=1, max_values=1))

        await interaction.response.send_message(
            "Sélectionne un joueur :",
            view=view,
            ephemeral=True
        )

    @commands.Cog.listener()
    async def on_interaction(self, interaction):
        if not interaction.data or interaction.data.get("component_type") != 5:
            return

        if not any(r.id == LADDER_ROLE_ID for r in interaction.user.roles):
            return

        target_id = int(interaction.data["values"][0])
        target = interaction.guild.get_member(target_id)
        if not target:
            return

        await interaction.response.send_message(
            f"Action pour {target.display_name} :",
            view=ActionView(self.bot, target, interaction.user),
            ephemeral=True
        )

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        ctx = self.bot.pending_manual.pop(message.author.id, None)
        if not ctx:
            return

        action, target = ctx

        try:
            amount = int(message.content)
            if amount <= 0:
                raise ValueError
        except ValueError:
            await message.channel.send("Nombre invalide.")
            return

        data = load_json(DATA_FILE)
        meta = load_json(META_FILE)
        period = meta.get("active_period")

        if not period:
            return

        data.setdefault(period, {})
        uid = str(target.id)
        current = data[period].get(uid, 0)

        if action == "add":
            data[period][uid] = current + amount
            delta = f"+{amount}"
        else:
            data[period][uid] = max(0, current - amount)
            delta = f"-{amount}"

        save_json(DATA_FILE, data)

        await message.channel.send(
            f"🧾 Modification manuelle : {target.display_name} {delta} points "
            f"(par {message.author.display_name})"
        )

        leaderboard = self.bot.get_cog("LadderLeaderboard")
        if leaderboard:
            await leaderboard.update_leaderboard()

        await message.delete()


async def setup(bot):
    await bot.add_cog(LadderJoueur(bot))