import os
import random
import asyncio
import sqlite3
import discord
from discord.ext import commands

# ===================== CONFIG =====================
CROUPIER_ROLE_ID = int(os.getenv("CROUPIER_ROLE_ID", "0"))
PLAYER_LB_CHANNEL = int(os.getenv("PLAYER_LB_CHANNEL", "0"))  # canal pour leaderboard joueurs
CROUPIER_LB_CHANNEL = int(os.getenv("CROUPIER_LB_CHANNEL", "0"))  # canal pour leaderboard croupiers
SPIN_GIF_URL = os.getenv("SPIN_GIF_URL", "")
COMMISSION_PERCENT = 5.0
MIN_MISE = 1000

RED_NUMBERS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
DB_PATH = "roulette.db"

# ===================== DATABASE =====================
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()
c.execute("""
CREATE TABLE IF NOT EXISTS players (
    user_id INTEGER PRIMARY KEY,
    mises INTEGER DEFAULT 0,
    gains INTEGER DEFAULT 0,
    victoires INTEGER DEFAULT 0,
    defaites INTEGER DEFAULT 0
)
""")
c.execute("""
CREATE TABLE IF NOT EXISTS croupiers (
    user_id INTEGER PRIMARY KEY,
    commissions INTEGER DEFAULT 0
)
""")
conn.commit()

# ===================== HELPERS =====================
def update_player(user_id, mise, gain, win):
    c.execute("INSERT OR IGNORE INTO players (user_id) VALUES (?)", (user_id,))
    c.execute(
        "UPDATE players SET mises = mises + ?, gains = gains + ?, victoires = victoires + ?, defaites = defaites + ? WHERE user_id = ?",
        (mise, gain, 1 if win else 0, 0 if win else 1, user_id)
    )
    conn.commit()

def update_croupier(user_id, commission):
    c.execute("INSERT OR IGNORE INTO croupiers (user_id) VALUES (?)", (user_id,))
    c.execute("UPDATE croupiers SET commissions = commissions + ? WHERE user_id = ?", (commission, user_id))
    conn.commit()

async def update_leaderboard_players(bot):
    if not PLAYER_LB_CHANNEL:
        return
    c.execute("SELECT user_id, mises, gains FROM players ORDER BY mises DESC")
    rows = c.fetchall()
    lines = []
    for uid, mises, gains in rows:
        member = bot.get_user(uid)
        name = member.name if member else f"ID:{uid}"
        lines.append(f"**{name}** — misé: {mises}k | net: {gains}k")
    embed = discord.Embed(title="📊 Leaderboard Joueurs", description="\n".join(lines), color=discord.Color.blurple())
    channel = bot.get_channel(PLAYER_LB_CHANNEL)
    if channel:
        messages = await channel.history(limit=1).flatten()
        if messages:
            await messages[0].edit(embed=embed)
        else:
            await channel.send(embed=embed)

async def update_leaderboard_croupiers(bot):
    if not CROUPIER_LB_CHANNEL:
        return
    c.execute("SELECT user_id, commissions FROM croupiers ORDER BY commissions DESC")
    rows = c.fetchall()
    lines = []
    for uid, commissions in rows:
        member = bot.get_user(uid)
        name = member.name if member else f"ID:{uid}"
        lines.append(f"**{name}** — commissions : {commissions}k")
    embed = discord.Embed(title="📊 Leaderboard Croupiers", description="\n".join(lines), color=discord.Color.gold())
    channel = bot.get_channel(CROUPIER_LB_CHANNEL)
    if channel:
        messages = await channel.history(limit=1).flatten()
        if messages:
            await messages[0].edit(embed=embed)
        else:
            await channel.send(embed=embed)

# ===================== VIEWS =====================
class DuelTypeSelect(discord.ui.View):
    def __init__(self, starter: discord.Member, mise: int, timeout: float = 120):
        super().__init__(timeout=timeout)
        self.starter = starter
        self.mise = mise
        self.duel_type: str | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.starter.id:
            await interaction.response.send_message("Seul le créateur peut choisir le type de duel.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🔴⚫  rouge/noir", style=discord.ButtonStyle.danger)
    async def btn_color(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.duel_type = "couleur"
        await interaction.response.edit_message(view=None)
        self.stop()

    @discord.ui.button(label="⚖️  pair/impair", style=discord.ButtonStyle.primary)
    async def btn_parity(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.duel_type = "parite"
        await interaction.response.edit_message(view=None)
        self.stop()

    @discord.ui.button(label="1️⃣-18 / 19-36", style=discord.ButtonStyle.success)
    async def btn_range(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.duel_type = "intervalle"
        await interaction.response.edit_message(view=None)
        self.stop()

class SideSelect(discord.ui.View):
    def __init__(self, starter: discord.Member, duel_type: str, timeout: float = 120):
        super().__init__(timeout=timeout)
        self.starter = starter
        self.duel_type = duel_type
        self.choice: str | None = None
        if duel_type == "couleur":
            self.add_item(discord.ui.Button(label="🔴 Rouge", style=discord.ButtonStyle.danger, custom_id="c_rouge"))
            self.add_item(discord.ui.Button(label="⚫ Noir", style=discord.ButtonStyle.secondary, custom_id="c_noir"))
        elif duel_type == "parite":
            self.add_item(discord.ui.Button(label="Pair", style=discord.ButtonStyle.primary, custom_id="p_pair"))
            self.add_item(discord.ui.Button(label="Impair", style=discord.ButtonStyle.secondary, custom_id="p_impair"))
        else:
            self.add_item(discord.ui.Button(label="1-18", style=discord.ButtonStyle.success, custom_id="r_1_18"))
            self.add_item(discord.ui.Button(label="19-36", style=discord.ButtonStyle.secondary, custom_id="r_19_36"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.starter.id:
            await interaction.response.send_message("Seul le créateur choisit son camp.", ephemeral=True)
            return False
        mapping = {
            "c_rouge": "rouge", "c_noir": "noir",
            "p_pair": "pair", "p_impair": "impair",
            "r_1_18": "1-18", "r_19_36": "19-36",
        }
        cid = interaction.data.get("custom_id")
        if cid in mapping:
            self.choice = mapping[cid]
            await interaction.response.edit_message(view=None)
            self.stop()
        return False

class JoinAndValidate(discord.ui.View):
    def __init__(self, starter: discord.Member, mise: int, duel_type: str, starter_choice: str, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.starter = starter
        self.mise = mise
        self.duel_type = duel_type
        self.starter_choice = starter_choice
        self.joiner: discord.Member | None = None
        self.validated_by: discord.Member | None = None

    @discord.ui.button(label="🤝 Rejoindre", style=discord.ButtonStyle.primary)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id == self.starter.id:
            return await interaction.response.send_message("Tu es déjà le créateur.", ephemeral=True)
        if self.joiner:
            return await interaction.response.send_message("Un adversaire a déjà rejoint.", ephemeral=True)
        self.joiner = interaction.user
        await interaction.response.send_message(f"{interaction.user.mention} a rejoint la partie !", ephemeral=True)

    @discord.ui.button(label="✅ Valider mises (croupier)", style=discord.ButtonStyle.success)
    async def validate(self, interaction: discord.Interaction, button: discord.ui.Button):
        if CROUPIER_ROLE_ID and not any(r.id == CROUPIER_ROLE_ID for r in interaction.user.roles):
            return await interaction.response.send_message("Réservé au rôle Croupier.", ephemeral=True)
        if not self.joiner:
            return await interaction.response.send_message("Attends qu’un adversaire rejoigne.", ephemeral=True)
        if self.validated_by:
            return await interaction.response.send_message("Déjà validé.", ephemeral=True)
        self.validated_by = interaction.user
        await interaction.response.send_message("Mises validées, la roulette va tourner…", ephemeral=True)
        self.stop()

# ===================== COG =====================
class Roulette(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(name="roulette", description="Lancer une roulette à deux joueurs (avec croupier)")
    @discord.app_commands.describe(mise="Mise en kamas (>=1000)")
    async def roulette_cmd(self, interaction: discord.Interaction, mise: int):
        if mise < MIN_MISE:
            return await interaction.response.send_message(f"La mise doit être au moins **{MIN_MISE}k**.", ephemeral=True)

        # 1️⃣ Choix type duel
        duel_view = DuelTypeSelect(interaction.user, mise)
        duel_embed = discord.Embed(title="🎰 Nouvelle Roulette", description=f"Créateur : {interaction.user.mention}\nMise : **{mise}k**\n\nChoisis le **type de duel** :", color=discord.Color.orange())
        await interaction.response.send_message(embed=duel_embed, view=duel_view)
        await duel_view.wait()
        if not duel_view.duel_type:
            return await interaction.followup.send("⏳ Duel annulé (aucun type choisi).")
        duel_type = duel_view.duel_type

        # 2️⃣ Choix camp créateur
        side_view = SideSelect(interaction.user, duel_type)
        side_embed = discord.Embed(title="🎯 Choisis ton camp", description=f"Type : **{duel_type}**\nClique un bouton ci-dessous.", color=discord.Color.orange())
        msg_side = await interaction.channel.send(embed=side_embed, view=side_view)
        await side_view.wait()
        if not side_view.choice:
            return await msg_side.edit(content="⏳ Duel annulé (aucun camp choisi).", embed=None, view=None)
        starter_choice = side_view.choice

        # 3️⃣ Attente adversaire
        join_view = JoinAndValidate(interaction.user, mise, duel_type, starter_choice)
        join_embed = discord.Embed(title="⏱️ En attente d’un second joueur", description=f"Type : **{duel_type}**\nCamp du créateur : `{starter_choice}`\n\n• Un adversaire clique **Rejoindre**\n• Puis un **Croupier** valide les mises", color=discord.Color.orange())
        msg_join = await interaction.channel.send(embed=join_embed, view=join_view)
        await join_view.wait()
        if not join_view.joiner:
            return await msg_join.edit(content="⏳ Temps écoulé, personne n’a rejoint.", embed=None, view=None)
        if not join_view.validated_by:
            return await msg_join.edit(content="⏳ Temps écoulé, mises non validées par un croupier.", embed=None, view=None)

        # 4️⃣ Spin
        spin_embed = discord.Embed(title="🎡 La roulette tourne…", description="Bonne chance !\nDécompte : 3️⃣ 2️⃣ 1️⃣", color=discord.Color.orange())
        if SPIN_GIF_URL:
            spin_embed.set_image(url=SPIN_GIF_URL)
        spin_msg = await interaction.channel.send(embed=spin_embed)
        await asyncio.sleep(3)

        n = random.randint(0,36)
        color = "vert" if n==0 else ("rouge" if n in RED_NUMBERS else "noir")
        parity = "pair" if n!=0 and n%2==0 else "impair"
        interval = "1-18" if 1<=n<=18 else ("19-36" if 19<=n<=36 else "0")

        def starter_wins():
            if duel_type=="couleur": return starter_choice==color
            if duel_type=="parite": return starter_choice==parity
            if duel_type=="intervalle": return starter_choice==interval
            return False

        winner = interaction.user if starter_wins() else join_view.joiner
        loser = join_view.joiner if winner==interaction.user else interaction.user

        total_pot = mise*2
        commission = int(round(total_pot * (COMMISSION_PERCENT/100.0)))
        gain = total_pot - commission

        # Update DB
        update_player(interaction.user.id, mise, gain-mise if winner==interaction.user else -mise, winner==interaction.user)
        update_player(join_view.joiner.id, mise, gain-mise if winner==join_view.joiner else -mise, winner==join_view.joiner)
        update_croupier(join_view.validated_by.id, commission)

        # Update leaderboards
        await update_leaderboard_players(self.bot)
        await update_leaderboard_croupiers(self.bot)

        # 5️⃣ Résultat
        result_embed = discord.Embed(
            title="✅ Résultat de la roulette",
            description=(
                f"**Nombre :** {n} ({color}) — {parity} — {interval}\n"
                f"**Gagnant :** {winner.mention}\n"
                f"**Gain :** {gain}k 💰\n"
                f"**Commission croupier :** {commission}k 🧾"
            ),
            color=discord.Color.green() if starter_wins() else discord.Color.red()
        )
        await spin_msg.edit(embed=result_embed)

    @discord.app_commands.command(name="stats", description="Voir vos statistiques personnelles")
    async def stats_cmd(self, interaction: discord.Interaction):
        c.execute("SELECT mises, gains, victoires, defaites FROM players WHERE user_id=?", (interaction.user.id,))
        row = c.fetchone()
        if not row:
            return await interaction.response.send_message("Tu n'as encore joué aucune partie.", ephemeral=True)
        mises, gains, victoires, defaites = row
        embed = discord.Embed(
            title=f"📊 Stats de {interaction.user.name}",
            description=(
                f"• Parties jouées : {victoires+defaites}\n"
                f"• Mises totales : {mises}k\n"
                f"• Victoires : {victoires}\n"
                f"• Défaites : {defaites}\n"
                f"• Gains/Pertes : {gains}k"
            ),
            color=discord.Color.blurple()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Roulette(bot))
