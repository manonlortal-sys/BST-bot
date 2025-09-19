import os
import random
import asyncio
import sqlite3
import discord
from discord.ext import commands

# ================= CONFIG =================
CROUPIER_ROLE_ID = int(os.getenv("CROUPIER_ROLE_ID", "0"))
SPIN_GIF_URL = os.getenv("SPIN_GIF_URL", "")
MIN_MISE = 1000
COMMISSION_PERCENT = 5.0

RED_NUMBERS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}

DB_PATH = "roulette.db"

# ================= SQLITE =================
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()
# Joueurs
c.execute("""
CREATE TABLE IF NOT EXISTS players (
    guild_id INTEGER,
    user_id INTEGER,
    mise_total INTEGER DEFAULT 0,
    gains INTEGER DEFAULT 0,
    victoires INTEGER DEFAULT 0,
    defaites INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
)
""")
# Croupiers
c.execute("""
CREATE TABLE IF NOT EXISTS croupiers (
    guild_id INTEGER,
    user_id INTEGER,
    commissions INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
)
""")
# Messages leaderboard
c.execute("""
CREATE TABLE IF NOT EXISTS leaderboard_messages (
    guild_id INTEGER,
    type TEXT,
    channel_id INTEGER,
    message_id INTEGER,
    PRIMARY KEY(guild_id, type)
)
""")
conn.commit()

# ================= VUES =================
class DuelTypeSelect(discord.ui.View):
    def __init__(self, starter: discord.Member):
        super().__init__(timeout=120)
        self.starter = starter
        self.duel_type: str | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.starter.id:
            await interaction.response.send_message("Seul le créateur peut choisir.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🔴⚫ Rouge/Noir", style=discord.ButtonStyle.danger)
    async def btn_color(self, interaction: discord.Interaction, button):
        self.duel_type = "couleur"
        self.stop()
        await interaction.response.edit_message(view=None)

    @discord.ui.button(label="⚖️ Pair/Impair", style=discord.ButtonStyle.primary)
    async def btn_parity(self, interaction: discord.Interaction, button):
        self.duel_type = "parite"
        self.stop()
        await interaction.response.edit_message(view=None)

    @discord.ui.button(label="1️⃣-18 / 19-36", style=discord.ButtonStyle.success)
    async def btn_range(self, interaction: discord.Interaction, button):
        self.duel_type = "intervalle"
        self.stop()
        await interaction.response.edit_message(view=None)

class SideSelect(discord.ui.View):
    def __init__(self, starter: discord.Member, duel_type: str):
        super().__init__(timeout=120)
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
            await interaction.response.send_message("Seul le créateur peut choisir.", ephemeral=True)
            return False
        mapping = {
            "c_rouge":"rouge","c_noir":"noir",
            "p_pair":"pair","p_impair":"impair",
            "r_1_18":"1-18","r_19_36":"19-36"
        }
        cid = interaction.data.get("custom_id")
        if cid in mapping:
            self.choice = mapping[cid]
            await interaction.response.edit_message(view=None)
            self.stop()
        return False

class JoinValidateView(discord.ui.View):
    def __init__(self, starter: discord.Member, mise: int, duel_type: str, starter_choice: str):
        super().__init__(timeout=300)
        self.starter = starter
        self.mise = mise
        self.duel_type = duel_type
        self.starter_choice = starter_choice
        self.joiner: discord.Member | None = None
        self.joiner_choice: str | None = None
        self.validated_by: discord.Member | None = None

    @discord.ui.button(label="🤝 Rejoindre", style=discord.ButtonStyle.primary)
    async def join(self, interaction: discord.Interaction, button):
        if interaction.user.id == self.starter.id:
            return await interaction.response.send_message("Tu es déjà le créateur.", ephemeral=True)
        if self.joiner is not None:
            return await interaction.response.send_message("Un adversaire a déjà rejoint.", ephemeral=True)
        self.joiner = interaction.user
        await interaction.response.send_message(f"{interaction.user.mention} a rejoint !", ephemeral=True)

    @discord.ui.button(label="✅ Valider mises", style=discord.ButtonStyle.success)
    async def validate(self, interaction: discord.Interaction, button):
        if CROUPIER_ROLE_ID and not any(r.id==CROUPIER_ROLE_ID for r in interaction.user.roles):
            return await interaction.response.send_message("Réservé au rôle Croupier.", ephemeral=True)
        if self.joiner is None:
            return await interaction.response.send_message("Attends qu’un adversaire rejoigne.", ephemeral=True)
        if self.validated_by:
            return await interaction.response.send_message("Déjà validé.", ephemeral=True)
        self.validated_by = interaction.user
        await interaction.response.send_message("Mises validées ! La roulette va tourner...", ephemeral=True)
        self.stop()

# ================= COG =================
class Roulette(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.guild_lb_cache = {}  # cache des messages leaderboard

    async def get_lb_msg(self, guild_id: int, lb_type: str, channel: discord.TextChannel):
        c.execute("SELECT message_id FROM leaderboard_messages WHERE guild_id=? AND type=?", (guild_id, lb_type))
        row = c.fetchone()
        if row:
            try:
                return await channel.fetch_message(row[0])
            except:
                return None
        return None

    async def update_leaderboard(self, guild_id: int):
        # Joueurs
        channel_id = int(os.getenv("LB_PLAYERS_CHANNEL", "0"))
        if channel_id == 0:
            return
        channel = self.bot.get_channel(channel_id)
        if not channel:
            return
        msg = await self.get_lb_msg(guild_id, "players", channel)
        c.execute("SELECT user_id, mise_total, gains, victoires, defaites FROM players WHERE guild_id=? ORDER BY mise_total DESC", (guild_id,))
        rows = c.fetchall()
        desc = "\n".join([f"<@{r[0]}> — mise: {r[1]}k | gains: {r[2]}k | victoires: {r[3]} | défaites: {r[4]}" for r in rows])
        embed = discord.Embed(title="📊 Leaderboard Joueurs", description=desc or "Pas encore de joueurs", color=discord.Color.blurple())
        if msg:
            await msg.edit(embed=embed)
        else:
            m = await channel.send(embed=embed)
            c.execute("INSERT OR REPLACE INTO leaderboard_messages (guild_id,type,channel_id,message_id) VALUES (?,?,?,?,?)", (guild_id,"players",channel_id,m.id))
            conn.commit()

        # Croupiers
        channel_id = int(os.getenv("LB_CROUPIERS_CHANNEL", "0"))
        if channel_id == 0:
            return
        channel = self.bot.get_channel(channel_id)
        if not channel:
            return
        msg = await self.get_lb_msg(guild_id, "croupiers", channel)
        c.execute("SELECT user_id, commissions FROM croupiers WHERE guild_id=? ORDER BY commissions DESC", (guild_id,))
        rows = c.fetchall()
        desc = "\n".join([f"<@{r[0]}> — commissions: {r[1]}k" for r in rows])
        embed = discord.Embed(title="💰 Leaderboard Croupiers", description=desc or "Pas encore de croupiers", color=discord.Color.gold())
        if msg:
            await msg.edit(embed=embed)
        else:
            m = await channel.send(embed=embed)
            c.execute("INSERT OR REPLACE INTO leaderboard_messages (guild_id,type,channel_id,message_id) VALUES (?,?,?,?,?)", (guild_id,"croupiers",channel_id,m.id))
            conn.commit()

    def update_player_stats(self, guild_id:int,user_id:int,mise:int,gain:int,won:bool):
        c.execute("INSERT OR IGNORE INTO players (guild_id,user_id) VALUES (?,?)",(guild_id,user_id))
        if won:
            c.execute("UPDATE players SET mise_total=mise_total+?, gains=gains+?, victoires=victoires+1 WHERE guild_id=? AND user_id=?",(mise,gain,guild_id,user_id))
        else:
            c.execute("UPDATE players SET mise_total=mise_total+?, gains=gains-?, defaites=defaites+1 WHERE guild_id=? AND user_id=?",(mise,gain,guild_id,user_id))
        conn.commit()

    def update_croupier_stats(self,guild_id:int,user_id:int,commission:int):
        c.execute("INSERT OR IGNORE INTO croupiers (guild_id,user_id) VALUES (?,?)",(guild_id,user_id))
        c.execute("UPDATE croupiers SET commissions=commissions+? WHERE guild_id=? AND user_id=?",(commission,guild_id,user_id))
        conn.commit()

    # ================= COMMANDES =================
    @commands.hybrid_command(name="roulette", description="Lancer une roulette à deux joueurs")
    async def roulette_cmd(self, ctx, mise: int):
        if mise < MIN_MISE:
            return await ctx.send(f"💥 Minimum de mise : {MIN_MISE}k", ephemeral=True)

        # 1) Choix type duel
        duel_view = DuelTypeSelect(ctx.author)
        duel_embed = discord.Embed(title="🎰 Nouvelle Roulette", description=f"Créateur : {ctx.author.mention}\nMise : **{mise}k**\nChoisis le type de duel :", color=discord.Color.orange())
        msg = await ctx.send(embed=duel_embed, view=duel_view)
        await duel_view.wait()
        if not duel_view.duel_type:
            return await msg.edit(content="⏳ Duel annulé (aucun type choisi).", embed=None, view=None)
        duel_type = duel_view.duel_type

        # 2) Choix camp créateur
        side_view = SideSelect(ctx.author, duel_type)
        side_embed = discord.Embed(title="🎯 Choisis ton camp", description=f"Type : **{duel_type}**\nClique un bouton ci-dessous.", color=discord.Color.orange())
        msg2 = await ctx.send(embed=side_embed, view=side_view)
        await side_view.wait()
        if not side_view.choice:
            return await msg2.edit(content="⏳ Duel annulé (aucun camp choisi).", embed=None, view=None)
        starter_choice = side_view.choice

        # 3) Attente adversaire + validation
        join_view = JoinValidateView(ctx.author, mise, duel_type, starter_choice)
        join_embed = discord.Embed(title="⏱️ En attente d’un adversaire", description=f"Type : **{duel_type}**\nCamp du créateur : {starter_choice}\nMise : {mise}k\nUn adversaire doit rejoindre…", color=discord.Color.orange())
        msg3 = await ctx.send(embed=join_embed, view=join_view)
        await join_view.wait()
        if not join_view.joiner:
            return await msg3.edit(content="⏳ Temps écoulé, personne n’a rejoint.", embed=None, view=None)
        if not join_view.validated_by:
            return await msg3.edit(content="⏳ Mises non validées par le croupier.", embed=None, view=None)

        # 4) Spin
        spin_embed = discord.Embed(title="🎡 La roulette tourne…", description=f"Pot total : {mise*2}k\nMises : {ctx.author.display_name} {mise}k, {join_view.joiner.display_name} {mise}k\nCommission à venir : {int(mise*2*COMMISSION_PERCENT/100)}k", color=discord.Color.orange())
        if SPIN_GIF_URL:
            spin_embed.set_image(url=SPIN_GIF_URL)
        spin_msg = await ctx.send(embed=spin_embed)
        await asyncio.sleep(3)

        # Résultat
        n = random.randint(0,36)
        color = "vert" if n==0 else ("rouge" if n in RED_NUMBERS else "noir")
        parity = "pair" if n!=0 and n%2==0 else "impair"
        interval = "1-18" if 1<=n<=18 else ("19-36" if 19<=n<=36 else "0")
        def starter_wins(): 
            if duel_type=="couleur": return starter_choice==color
            if duel_type=="parite": return starter_choice==parity
            if duel_type=="intervalle": return starter_choice==interval
            return False
        winner = ctx.author if starter_wins() else join_view.joiner
        loser = join_view.joiner if winner==ctx.author else ctx.author

        total_pot = mise*2
        commission = int(round(total_pot*COMMISSION_PERCENT/100))
        gain = total_pot - commission

        # 5) Mise à jour stats
        self.update_player_stats(ctx.guild.id, ctx.author.id, mise, gain if winner==ctx.author else 0, winner==ctx.author)
        self.update_player_stats(ctx.guild.id, join_view.joiner.id, mise, gain if winner==join_view.joiner else 0, winner==join_view.joiner)
        self.update_croupier_stats(ctx.guild.id, join_view.validated_by.id, commission)
        await self.update_leaderboard(ctx.guild.id)

        # 6) Embed résultat
        res_embed = discord.Embed(title="✅ Résultat de la roulette", color=discord.Color.green())
        res_embed.add_field(name="Gagnant", value=f"{winner.mention}", inline=True)
        res_embed.add_field(name="Perdant", value=f"{loser.mention}", inline=True)
        res_embed.add_field(name="Nombre", value=f"{n} ({color}) — {parity} — {interval}", inline=False)
        res_embed.add_field(name="Pot total", value=f"{total_pot}k", inline=True)
        res_embed.add_field(name="Gain", value=f"{gain}k", inline=True)
        res_embed.add_field(name="Commission croupier", value=f"{commission}k par {join_view.validated_by.display_name}", inline=False)
        await spin_msg.edit(embed=res_embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(Roulette(bot))
