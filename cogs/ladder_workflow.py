import discord
from discord.ext import commands
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

# =============================
# CONFIG
# =============================
DATA_FILE = "data/ladder.json"
TZ = ZoneInfo("Europe/Paris")


# =============================
# UTILS
# =============================
def current_period():
    now = datetime.now(TZ)
    if now.day < 15:
        return f"{now.year}-{now.month:02d}-01_14"
    return f"{now.year}-{now.month:02d}-15_end"


def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        return json.load(f)


def save_data(data):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# =============================
# VIEWS
# =============================
class TypeView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=300)
        self.bot = bot

    @discord.ui.button(label="Attaque", style=discord.ButtonStyle.danger)
    async def attack(self, interaction: discord.Interaction, _):
        await interaction.response.send_message(
            "Sélectionne les joueurs",
            view=PlayerSelectView(self.bot, "Attaque"),
            ephemeral=True,
        )

    @discord.ui.button(label="Défense", style=discord.ButtonStyle.success)
    async def defense(self, interaction: discord.Interaction, _):
        await interaction.response.send_message(
            "Sélectionne les joueurs",
            view=PlayerSelectView(self.bot, "Défense"),
            ephemeral=True,
        )


class PlayerSelectView(discord.ui.View):
    def __init__(self, bot: commands.Bot, combat_type: str):
        super().__init__(timeout=300)
        self.add_item(PlayerSelect(bot, combat_type))


class PlayerSelect(discord.ui.UserSelect):
    def __init__(self, bot: commands.Bot, combat_type: str):
        super().__init__(min_values=1, max_values=4)
        self.bot = bot
        self.combat_type = combat_type

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "Choisis la configuration",
            view=ConfigView(
                self.bot,
                self.combat_type,
                self.values,
                interaction.user.display_name,
            ),
            ephemeral=True,
        )


class ConfigView(discord.ui.View):
    def __init__(self, bot, combat_type, players, validator_name):
        super().__init__(timeout=300)
        self.bot = bot
        self.combat_type = combat_type
        self.players = players
        self.validator_name = validator_name

        if combat_type == "Attaque":
            self.add_item(ConfigButton("4v4 – 0 mort", 6))
            self.add_item(ConfigButton("4v4 – morts", 5))
            self.add_item(ConfigButton("3v4 victoire", 7))
        else:
            self.add_item(ConfigButton("4v4 – 0 mort", 4))
            self.add_item(ConfigButton("4v4 – morts", 3))
            self.add_item(ConfigButton("3v4 victoire", 5))

    async def apply(self, interaction: discord.Interaction, label: str, points: int):
        data = load_data()
        period = current_period()

        if period not in data:
            data[period] = {}

        for user in self.players:
            uid = str(user.id)
            data[period][uid] = data[period].get(uid, 0) + points

        save_data(data)

        # 🔁 MISE À JOUR DU LADDER (OBLIGATOIRE)
        leaderboard = interaction.client.get_cog("LadderLeaderboard")
        if leaderboard:
            await leaderboard.update_leaderboard()

        lines = [
            f"{user.display_name} +{points} pts"
            for user in self.players
        ]

        recap = (
            "🧾 **Récap Ladder**\n"
            f"Type : {self.combat_type}\n"
            f"Configuration : {label}\n"
            f"Validé par : {self.validator_name}\n\n"
            + "\n".join(lines)
        )

        await interaction.channel.send(recap)
        await interaction.response.send_message("✅ Points attribués", ephemeral=True)


class ConfigButton(discord.ui.Button):
    def __init__(self, label: str, points: int):
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self.points = points

    async def callback(self, interaction: discord.Interaction):
        await self.view.apply(interaction, self.label, self.points)


# =============================
# COG
# =============================
class LadderWorkflow(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ✅ MÉTHODE ATTENDUE PAR ladder_screens
    async def start(self, interaction: discord.Interaction, screen_message):
        await interaction.followup.send(
            "Type de combat ?",
            view=TypeView(self.bot),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(LadderWorkflow(bot))