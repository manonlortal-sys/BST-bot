import os
import random
import asyncio
from datetime import datetime, timedelta, timezone
from collections import defaultdict

import discord
from discord.ext import commands, tasks

TOKEN = os.getenv("DISCORD_TOKEN")
CROUPIER_ROLE_ID = int(os.getenv("CROUPIER_ROLE_ID", "0"))
LEADERBOARD_CHANNEL_ID = int(os.getenv("LEADERBOARD_CHANNEL_ID", "0"))
SPIN_GIF_URL = os.getenv("SPIN_GIF_URL", "https://media.discordapp.net/.../roulette.gif")

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- Données ---
RED_NUMBERS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
BLACK_NUMBERS = set(range(1, 37)) - RED_NUMBERS
roulette_games = {}  # guild_id -> game
leaderboard_data = defaultdict(lambda: defaultdict(int))  # guild_id -> {user_id: {...}}


# --- Classes ---
class RouletteGame:
    def __init__(self, starter_id, duel_type, choice, bet):
        self.starter_id = starter_id
        self.duel_type = duel_type
        self.choice = choice
        self.bet = bet
        self.joiner_id = None
        self.joiner_choice = None
        self.validated = False


class DuelSelectView(discord.ui.View):
    def __init__(self, starter_id, bet):
        super().__init__(timeout=180)
        self.starter_id = starter_id
        self.bet = bet

    async def _set(self, inter, duel_type, choice_label, opposite_label):
        if inter.user.id != self.starter_id:
            await inter.response.send_message("Tu n'es pas le créateur.", ephemeral=True)
            return

        game = RouletteGame(self.starter_id, duel_type, choice_label, self.bet)
        roulette_games[inter.guild.id] = game

        embed = discord.Embed(
            title="🎲 Défi Roulette créé !",
            description=(
                f"**Mise :** {self.bet}\n"
                f"**Défi choisi :** {duel_type}\n"
                f"**Choix du créateur :** {choice_label}\n\n"
                "➡️ Un joueur peut rejoindre avec `/roulette`."
            ),
            color=discord.Color.red()
        )
        await inter.response.edit_message(embed=embed, view=None)

    # Boutons pour choix
    @discord.ui.button(label="🔴⚫ Rouge/Noir", style=discord.ButtonStyle.danger)
    async def b_color(self, inter, _):
        await self._set(inter, "couleur", "rouge", "noir")

    @discord.ui.button(label="⚖️ Pair/Impair", style=discord.ButtonStyle.primary)
    async def b_parity(self, inter, _):
        await self._set(inter, "parité", "pair", "impair")

    @discord.ui.button(label="🔢 1-18 / 19-36", style=discord.ButtonStyle.success)
    async def b_half(self, inter, _):
        await self._set(inter, "moitié", "1-18", "19-36")


class ValidateView(discord.ui.View):
    def __init__(self, guild_id):
        super().__init__(timeout=180)
        self.guild_id = guild_id

    @discord.ui.button(label="✅ Valider les mises", style=discord.ButtonStyle.success)
    async def validate(self, inter, _):
        game = roulette_games.get(self.guild_id)
        if not game:
            await inter.response.send_message("Pas de partie active.", ephemeral=True)
            return
        if game.validated:
            await inter.response.send_message("Les mises ont déjà été validées.", ephemeral=True)
            return
        if not any(role.id == CROUPIER_ROLE_ID for role in inter.user.roles):
            await inter.response.send_message("Tu n'es pas croupier.", ephemeral=True)
            return

        game.validated = True
        await inter.response.defer(ephemeral=True)
        await run_spin(inter.channel, inter.guild.id)


# --- Fonctions ---
async def run_spin(channel, guild_id):
    game = roulette_games[guild_id]

    # GIF embed
    embed = discord.Embed(title="🎰 Roulette en cours...", color=discord.Color.orange())
    embed.set_image(url=SPIN_GIF_URL)
    msg = await channel.send(embed=embed)

    await asyncio.sleep(4)

    n = random.randint(0, 36)
    col = "vert" if n == 0 else ("rouge" if n in RED_NUMBERS else "noir")
    result_text = f"🎯 Résultat : {n} ({col})"

    def is_win(choice, duel_type):
        if duel_type == "couleur":
            return (choice == "rouge" and n in RED_NUMBERS) or (choice == "noir" and n in BLACK_NUMBERS)
        if duel_type == "parité":
            return (choice == "pair" and n % 2 == 0 and n != 0) or (choice == "impair" and n % 2 == 1)
        if duel_type == "moitié":
            return (choice == "1-18" and 1 <= n <= 18) or (choice == "19-36" and 19 <= n <= 36)
        return False

    winner, loser = None, None
    if is_win(game.choice, game.duel_type):
        winner, loser = game.starter_id, game.joiner_id
    elif is_win(game.joiner_choice, game.duel_type):
        winner, loser = game.joiner_id, game.starter_id

    pot = game.bet * 2
    commission = int(pot * 0.05)
    gain = pot - commission

    lines = [result_text]
    if winner:
        lines.append(f"🏆 <@{winner}> gagne **{gain}k**")
        lines.append(f"💸 Commission croupier : {commission}k")
    else:
        lines.append("❌ Aucun gagnant, la banque garde la mise.")

    res = discord.Embed(
        title="🎲 Résultat Roulette",
        description="\n".join(lines),
        color=discord.Color.green() if winner else discord.Color.red()
    )
    await msg.edit(embed=res)

    # maj leaderboard
    data = leaderboard_data[guild_id]
    data[game.starter_id]["mises"] += game.bet
    data[game.joiner_id]["mises"] += game.bet
    if winner:
        data[winner]["net"] += gain - game.bet
        data[loser]["net"] -= game.bet
        data[winner]["wins"] += 1
        data[loser]["losses"] += 1
        data[winner]["best"] = max(data[winner].get("best", 0), gain)
    roulette_games.pop(guild_id, None)


def format_leaderboard(guild_id):
    data = leaderboard_data[guild_id]
    if not data:
        return "Aucune donnée."
    sorted_players = sorted(data.items(), key=lambda x: x[1]["mises"], reverse=True)

    lines = []
    total = sum(p["mises"] for p in data.values())
    for uid, stats in sorted_players:
        lines.append(f"<@{uid}> — Misé: {stats['mises']}k | Net: {stats['net']}k")
    lines.append(f"\n**Total misé : {total}k**")
    return "\n".join(lines)


# --- Commandes ---
@bot.tree.command(name="roulette", description="Lancer ou rejoindre une roulette")
async def roulette_cmd(inter, mise: int = 1000):
    guild_id = inter.guild.id
    game = roulette_games.get(guild_id)

    if not game:
        view = DuelSelectView(inter.user.id, mise)
        embed = discord.Embed(
            title="🎲 Crée ta partie de roulette",
            description="Choisis ton type de défi pour commencer.",
            color=discord.Color.blurple()
        )
        await inter.response.send_message(embed=embed, view=view)
    else:
        if game.joiner_id:
            await inter.response.send_message("Une partie est déjà complète.", ephemeral=True)
            return
        if inter.user.id == game.starter_id:
            await inter.response.send_message("Tu es déjà dans la partie.", ephemeral=True)
            return

        game.joiner_id = inter.user.id
        game.joiner_choice = (
            "noir" if game.choice == "rouge"
            else "rouge" if game.choice == "noir"
            else "impair" if game.choice == "pair"
            else "pair" if game.choice == "impair"
            else "19-36" if game.choice == "1-18"
            else "1-18"
        )

        mention = f"<@&{CROUPIER_ROLE_ID}>" if CROUPIER_ROLE_ID else "croupier"
        embed = discord.Embed(
            title="💰 Mise à valider",
            description=(
                f"Créateur : <@{game.starter_id}> ({game.choice})\n"
                f"Adversaire : <@{game.joiner_id}> ({game.joiner_choice})\n"
                f"Mise : {game.bet}k chacun\n\n"
                f"{mention}, merci de valider les mises."
            ),
            color=discord.Color.gold()
        )
        await inter.response.send_message(embed=embed, view=ValidateView(guild_id))


@bot.tree.command(name="leaderboard", description="Voir le leaderboard")
async def leaderboard_cmd(inter):
    txt = format_leaderboard(inter.guild.id)
    embed = discord.Embed(title="🏅 Leaderboard", description=txt, color=discord.Color.purple())
    await inter.response.send_message(embed=embed)


@bot.tree.command(name="profil", description="Voir ton profil roulette")
async def profil_cmd(inter):
    stats = leaderboard_data[inter.guild.id][inter.user.id]
    embed = discord.Embed(
        title=f"👤 Profil de {inter.user.display_name}",
        description=(
            f"Total misé : {stats['mises']}k\n"
            f"Gains nets : {stats['net']}k\n"
            f"Victoires : {stats['wins']}\n"
            f"Défaites : {stats['losses']}\n"
            f"Plus gros gain : {stats.get('best',0)}k"
        ),
        color=discord.Color.blue()
    )
    await inter.response.send_message(embed=embed)


# --- Auto leaderboard hebdo ---
@tasks.loop(hours=1)
async def weekly_lb():
    now = datetime.now(timezone.utc)
    if now.weekday() == 4 and now.hour == 16:  # vendredi 18h Paris (16h UTC)
        for guild in bot.guilds:
            channel = guild.get_channel(LEADERBOARD_CHANNEL_ID)
            if channel:
                txt = format_leaderboard(guild.id)
                embed = discord.Embed(title="🏅 Leaderboard hebdomadaire", description=txt, color=discord.Color.purple())
                await channel.send(embed=embed)


@bot.event
async def on_ready():
    await bot.tree.sync()
    weekly_lb.start()
    print(f"{bot.user} prêt.")


bot.run(TOKEN)
