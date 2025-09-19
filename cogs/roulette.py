import os
import random
import asyncio
import sqlite3
from datetime import datetime
import discord
from discord.ext import commands

# ========= Config =========
SPIN_GIF_URL = os.getenv("SPIN_GIF_URL", "")
CROUPIER_ROLE_ID = int(os.getenv("CROUPIER_ROLE_ID", "0"))
COMMISSION_PERCENT = 5.0
MIN_MISE = 1000
PLAYER_LEADERBOARD_CHANNEL_ID = int(os.getenv("PLAYER_LEADERBOARD_CHANNEL_ID", "0"))
CROUPIER_LEADERBOARD_CHANNEL_ID = int(os.getenv("CROUPIER_LEADERBOARD_CHANNEL_ID", "0"))
RED_NUMBERS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}

# ========= SQLite setup =========
DB_PATH = "roulette.db"
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()
c.execute("""CREATE TABLE IF NOT EXISTS players (
    user_id INTEGER PRIMARY KEY,
    mises INTEGER DEFAULT 0,
    gains INTEGER DEFAULT 0,
    victoires INTEGER DEFAULT 0,
    defaites INTEGER DEFAULT 0,
    parties INTEGER DEFAULT 0
)""")
c.execute("""CREATE TABLE IF NOT EXISTS croupiers (
    user_id INTEGER PRIMARY KEY,
    commissions INTEGER DEFAULT 0,
    parties_valides INTEGER DEFAULT 0
)""")
conn.commit()

# ========= Helpers =========
def update_player(user_id: int, mise: int, gain: int, victoire: bool):
    c.execute("INSERT OR IGNORE INTO players(user_id) VALUES (?)", (user_id,))
    c.execute("UPDATE players SET mises = mises + ?, gains = gains + ?, parties = parties + 1 WHERE user_id = ?",
              (mise, gain - mise, user_id))
    if victoire:
        c.execute("UPDATE players SET victoires = victoires + 1 WHERE user_id = ?", (user_id,))
    else:
        c.execute("UPDATE players SET defaites = defaites + 1 WHERE user_id = ?", (user_id,))
    conn.commit()

def update_croupier(user_id: int, commission: int):
    c.execute("INSERT OR IGNORE INTO croupiers(user_id) VALUES (?)", (user_id,))
    c.execute("UPDATE croupiers SET commissions = commissions + ?, parties_valides = parties_valides + 1 WHERE user_id = ?",
              (commission, user_id))
    conn.commit()

async def update_leaderboard(bot: commands.Bot):
    # Joueurs
    if PLAYER_LEADERBOARD_CHANNEL_ID:
        channel = bot.get_channel(PLAYER_LEADERBOARD_CHANNEL_ID)
        if channel:
            c.execute("SELECT * FROM players ORDER BY mises DESC")
            rows = c.fetchall()
            lines = []
            for r in rows:
                user = await bot.fetch_user(r[0])
                lines.append(f"**{user.display_name}** — Mises: {r[1]}k | Gains/Pertes: {r[2]}k | Victoires: {r[3]} | Défaites: {r[4]}")
            embed = discord.Embed(title="📊 Leaderboard Joueurs", description="\n".join(lines), color=discord.Color.blurple())
            msgs = await channel.history(limit=1).flatten()
            if msgs:
                await msgs[0].edit(embed=embed)
            else:
                await channel.send(embed=embed)

    # Croupiers
    if CROUPIER_LEADERBOARD_CHANNEL_ID:
        channel = bot.get_channel(CROUPIER_LEADERBOARD_CHANNEL_ID)
        if channel:
            c.execute("SELECT * FROM croupiers ORDER BY commissions DESC")
            rows = c.fetchall()
            lines = []
            for r in rows:
                user = await bot.fetch_user(r[0])
                lines.append(f"**{user.display_name}** — Commissions: {r[1]}k | Parties validées: {r[2]}")
            embed = discord.Embed(title="💰 Leaderboard Croupiers", description="\n".join(lines), color=discord.Color.gold())
            msgs = await channel.history(limit=1).flatten()
            if msgs:
                await msgs[0].edit(embed=embed)
            else:
                await channel.send(embed=embed)

# ========= Views =========
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

    @discord.ui.button(label="🔴⚫ Rouge/Noir", style=discord.ButtonStyle.danger)
    async def btn_color(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.duel_type = "couleur"
        self.stop()
        await interaction.response.edit_message(view=None)

    @discord.ui.button(label="⚖️ Pair/Impair", style=discord.ButtonStyle.primary)
    async def btn_parity(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.duel_type = "parite"
        self.stop()
        await interaction.response.edit_message(view=None)

    @discord.ui.button(label="1️⃣-18 / 19-36", style=discord.ButtonStyle.success)
    async def btn_range(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.duel_type = "intervalle"
        self.stop()
        await interaction.response.edit_message(view=None)

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
        return True

    async def on_timeout(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

    async def callback(self, interaction: discord.Interaction, custom_id: str):
        mapping = {"c_rouge": "rouge", "c_noir": "noir", "p_pair": "pair", "p_impair": "impair", "r_1_18": "1-18", "r_19_36": "19-36"}
        if custom_id in mapping:
            self.choice = mapping[custom_id]
            await interaction.response.edit_message(view=None)
            self.stop()

    async def interaction_check_and_route(self, interaction: discord.Interaction):
        if await self.interaction_check(interaction):
            await self.callback(interaction, interaction.data.get("custom_id"))

# ========= Join & Validation =========
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
            return await interaction.response.send_message("Tu es déjà le créateur de la partie.", ephemeral=True)
        if self.joiner:
            return await interaction.response.send_message("Un adversaire a déjà rejoint.", ephemeral=True)
        self.joiner = interaction.user
        button.disabled = True
        await interaction.response.edit_message(content=f"{interaction.user.mention} a rejoint la partie !", view=self)
    
    @discord.ui.button(label="✅ Valider mises (croupier)", style=discord.ButtonStyle.success)
    async def validate(self, interaction: discord.Interaction, button: discord.ui.Button):
        if CROUPIER_ROLE_ID and not any(r.id == CROUPIER_ROLE_ID for r in interaction.user.roles):
            return await interaction.response.send_message("Réservé au rôle Croupier.", ephemeral=True)
        if self.joiner is None:
            return await interaction.response.send_message("Attends qu’un adversaire rejoigne.", ephemeral=True)
        self.validated_by = interaction.user
        button.disabled = True
        await interaction.response.edit_message(content="Mises validées ✅ La roulette va tourner…", view=self)
        self.stop()

# ========= Cog =========
class Roulette(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(name="roulette", description="Lancer une roulette à deux joueurs (avec croupier)")
    @discord.app_commands.describe(mise="Mise en kamas (entier positif, min 1000)")
    async def roulette_cmd(self, interaction: discord.Interaction, mise: int):
        if mise < MIN_MISE:
            return await interaction.response.send_message(f"La mise minimale est de {MIN_MISE}k.", ephemeral=True)

        # --- Étape 1 : Choix type duel ---
        duel_view = DuelTypeSelect(starter=interaction.user, mise=mise)
        duel_embed = discord.Embed(title="🎰 Nouvelle Roulette", description=f"Créateur : {interaction.user.mention}\nMise : **{mise}k**\n\nChoisis le type de duel :", color=discord.Color.orange())
        await interaction.response.send_message(embed=duel_embed, view=duel_view)
        await duel_view.wait()
        if not duel_view.duel_type:
            return await interaction.edit_original_response(content="⏳ Duel annulé (aucun type choisi).", embed=None, view=None)
        duel_type = duel_view.duel_type

        # --- Étape 2 : Choix du camp ---
        side_view = SideSelect(starter=interaction.user, duel_type=duel_type)
        side_embed = discord.Embed(title="🎯 Choisis ton camp", description=f"Type : {duel_type}\nClique un bouton ci-dessous.", color=discord.Color.orange())
        msg2 = await interaction.channel.send(embed=side_embed, view=side_view)
        await side_view.wait()
        if not side_view.choice:
            return await msg2.edit(content="⏳ Duel annulé (aucun camp choisi).", embed=None, view=None)
        starter_choice = side_view.choice

        # --- Étape 3 & 4 : Attente adversaire + validation ---
        wait_embed = discord.Embed(title="⏳ En attente d’un adversaire", description=f"Type : {duel_type}\nCamp du créateur : {starter_choice}\nCliquez sur 🤝 pour rejoindre.", color=discord.Color.orange())
        join_view = JoinAndValidate(starter=interaction.user, mise=mise, duel_type=duel_type, starter_choice=starter_choice)
        msg3 = await interaction.channel.send(embed=wait_embed, view=join_view)

        # Barre de progression animée
        progress = ["[■□□□□□□□□□]", "[■■□□□□□□□□]", "[■■■□□□□□□□]", "[■■■■□□□□□□]", "[■■■■■□□□□□]", "[■■■■■■□□□□]", "[■■■■■■■□□□]", "[■■■■■■■■□□]", "[■■■■■■■■■□]", "[■■■■■■■■■■]"]
        for bar in progress:
            if join_view.joiner:
                break
            embed = discord.Embed(title="⏳ En attente d’un adversaire", description=f"{bar} Attente d’un adversaire…", color=discord.Color.orange())
            await msg3.edit(embed=embed, view=join_view)
            await asyncio.sleep(1)

        await join_view.wait()
        if not join_view.joiner:
            return await msg3.edit(content="⏳ Temps écoulé, personne n’a rejoint.", embed=None, view=None)
        if not join_view.validated_by:
            return await msg3.edit(content="⏳ Temps écoulé, mises non validées par un croupier.", embed=None, view=None)

        # --- Étape 5 : Spin ---
        spin_embed = discord.Embed(title="🎡 La roulette tourne…", description="Préparez-vous !", color=discord.Color.orange())
        if SPIN_GIF_URL:
            spin_embed.set_image(url=SPIN_GIF_URL)
        spin_msg = await interaction.channel.send(embed=spin_embed)
        for i in [3,2,1]:
            await spin_msg.edit(embed=discord.Embed(title=f"🎡 La roulette tourne… {i}", color=discord.Color.orange()))
            await asyncio.sleep(1)

        n = random.randint(0,36)
        color = "vert" if n==0 else ("rouge" if n in RED_NUMBERS else "noir")
        parity = "pair" if n!=0 and n%2==0 else "impair"
        interval = "1-18" if 1<=n<=18 else ("19-36" if 19<=n<=36 else "0")
        starter_wins = (starter_choice == (color if duel_type=="couleur" else parity if duel_type=="parite" else interval))
        winner = interaction.user if starter_wins else join_view.joiner
        loser = join_view.joiner if winner==interaction.user else interaction.user
        total_pot = mise*2
        commission = int(round(total_pot*(COMMISSION_PERCENT/100)))
        gain = total_pot - commission

        # --- Étape 6 : Résultat ---
        result_embed = discord.Embed(title="✅ Résultat de la roulette", color=discord.Color.green() if winner==interaction.user else discord.Color.red())
        result_embed.add_field(name="🎲 Nombre tiré", value=f"{n} ({color}) — {parity} — {interval}", inline=False)
        result_embed.add_field(name="💰 Gagnant", value=f"{winner.mention}", inline=True)
        result_embed.add_field(name="💸 Gain net", value=f"{gain}k", inline=True)
        result_embed.add_field(name="🪙 Commission croupier", value=f"{commission}k", inline=False)
        result_embed.add_field(name="👤 Joueurs", value=f"{interaction.user.mention} ({starter_choice}) vs {join_view.joiner.mention}", inline=False)
        result_embed.add_field(name="🎰 Mise par joueur", value=f"{mise}k chacun", inline=False)
        await spin_msg.edit(embed=result_embed)

        # --- Mise à jour stats ---
        update_player(interaction.user.id, mise, gain if starter_wins else 0, starter_wins)
        update_player(join_view.joiner.id, mise, gain if not starter_wins else 0, not starter_wins)
        update_croupier(join_view.validated_by.id, commission)
        await update_leaderboard(self.bot)

    @discord.app_commands.command(name="stats", description="Afficher vos stats personnelles")
    async def stats_cmd(self, interaction: discord.Interaction):
        c.execute("SELECT * FROM players WHERE user_id=?", (interaction.user.id,))
        row = c.fetchone()
        if not row:
            return await interaction.response.send_message("Aucune statistique trouvée.", ephemeral=True)
        embed = discord.Embed(title=f"📊 Stats de {interaction.user.display_name}", color=discord.Color.blurple())
        embed.add_field(name="Parties jouées", value=row[5])
        embed.add_field(name="Mises totales", value=row[1])
        embed.add_field(name="Gains/Pertes", value=row[2])
        embed.add_field(name="Victoires", value=row[3])
        embed.add_field(name="Défaites", value=row[4])
        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(Roulette(bot))
