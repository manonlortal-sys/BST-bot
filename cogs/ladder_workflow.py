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
    async def attack(self, interaction, _):
        await interaction.response.send_message(
            "Sélectionne les joueurs",
            view=PlayerSelectView(self.bot, self.screen_msg, "attack"),
            ephemeral=True,
        )

    @discord.ui.button(label="Défense", style=discord.ButtonStyle.success)
    async def defense(self, interaction, _):
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

    async def callback(self, interaction):
        players = self.values
        await interaction.response.send_message(
            "Choisis la configuration",
            view=ConfigView(self.bot, self.screen_msg, self.mode, players),
            ephemeral=True,
        )

class ConfigView(discord.ui.View):
    def __init__(self, bot, screen_msg, mode, players):
        super().__init__(timeout=300)
        self.bot = bot
        self.screen_msg = screen_msg
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

    async def apply(self, interaction, points):
        data = load_data()
        period = current_period()
        if period not in data:
            data = {period: {}}

        for u in self.players:
            uid = str(u.id)
            data[period][uid] = data[period].get(uid, 0) + points

        save_data(data)

        lines = [f"{u.mention} +{points} pts" for u in self.players]
        await interaction.channel.send(
            "🧾 **Récap Ladder**\n" + "\n".join(lines)
        )

        leaderboard = self.bot.get_cog("LadderLeaderboard")
        if leaderboard:
            await leaderboard.update_leaderboard()

        await interaction.response.send_message("Validé", ephemeral=True)

class ConfigButton(discord.ui.Button):
    def __init__(self, label, points):
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self.points = points

    async def callback(self, interaction):
        await self.view.apply(interaction, self.points)

class LadderWorkflow(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def start(self, interaction, screen_msg):
        await interaction.response.send_message(
            "Type de combat ?",
            view=TypeView(self.bot, screen_msg),
            ephemeral=True,
        )

async def setup(bot):
    await bot.add_cog(LadderWorkflow(bot))