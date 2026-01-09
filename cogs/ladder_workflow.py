import discord
from discord.ext import commands
import json
import os
from datetime import datetime

LADDER_ROLE_ID = 1459190410835660831
DATA_FILE = "data/ladder.json"


def current_period():
    now = datetime.utcnow()
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
        json.dump(data, f, indent=2)


class TypeView(discord.ui.View):
    def __init__(self, bot, screen_msg):
        super().__init__(timeout=300)
        self.bot = bot
        self.screen_msg = screen_msg

    async def interaction_check(self, interaction):
        return any(r.id == LADDER_ROLE_ID for r in interaction.user.roles)

    @discord.ui.button(label="Attaque", style=discord.ButtonStyle.danger)
    async def attack(self, interaction: discord.Interaction, _):
        await interaction.response.send_message(
            "Sélectionne les joueurs",
            view=PlayerSelectView(self.bot, self.screen_msg, "attack"),
            ephemeral=True,
        )

    @discord.ui.button(label="Défense", style=discord.ButtonStyle.success)
    async def defense(self, interaction: discord.Interaction, _):
        await interaction.response.send_message(
            "Sélectionne les joueurs",
            view=PlayerSelectView(self.bot, self.screen_msg, "defense"),
            ephemeral=True,
        )


class PlayerSelectView(discord.ui.View):
    def __init__(self, bot, screen_msg, mode):
        super().__init__(timeout=300)
        self.add_item(PlayerSelect(bot, screen_msg, mode))


class PlayerSelect(discord.ui.UserSelect):
    def __init__(self, bot, screen_msg, mode):
        super().__init__(min_values=1, max_values=4)
        self.bot = bot
        self.screen_msg = screen_msg
        self.mode = mode

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "Choisis la configuration",
            view=ConfigView(self.bot, self.mode, self.values),
            ephemeral=True,
        )


class ConfigView(discord.ui.View):
    def __init__(self, bot, mode, players):
        super().__init__(timeout=300)
        self.bot = bot
        self.mode = mode
        self.players = players

        if mode == "attack":
            self.add_item(ConfigButton("4v4 – 0 mort", 6))
            self.add_item(ConfigButton("4v4 – morts", 5))
            self.add_item(ConfigButton("<4v4 victoire", 7))
        else:
            self.add_item(ConfigButton("4v4 – 0 mort", 4))
            self.add_item(ConfigButton("4v4 – morts", 3))
            self.add_item(ConfigButton("<4v4 victoire", 5))

    async def apply(self, interaction: discord.Interaction, points: int):
        data = load_data()
        period = current_period()

        if period not in data:
            data[period] = {}

        for user in self.players:
            uid = str(user.id)
            data[period][uid] = data[period].get(uid, 0) + points

        save_data(data)

        recap = "\n".join(f"{u.mention} +{points} pts" for u in self.players)
        await interaction.channel.send(f"🧾 **Récap Ladder**\n{recap}")

        leaderboard = self.bot.get_cog("LadderLeaderboard")
        if leaderboard:
            await leaderboard.update_leaderboard()

        await interaction.response.send_message("✅ Points attribués", ephemeral=True)


class ConfigButton(discord.ui.Button):
    def __init__(self, label, points):
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self.points = points

    async def callback(self, interaction: discord.Interaction):
        await self.view.apply(interaction, self.points)


class LadderWorkflow(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def start(self, interaction: discord.Interaction, screen_msg):
        # ⚠️ interaction déjà defer → FOLLOWUP OBLIGATOIRE
        await interaction.followup.send(
            "Type de combat ?",
            view=TypeView(self.bot, screen_msg),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(LadderWorkflow(bot))