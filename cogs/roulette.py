import os
import random
import asyncio
import sqlite3
import discord
from discord.ext import commands

# ---------- CONFIG ----------
CROUPIER_ROLE_ID = int(os.getenv("CROUPIER_ROLE_ID", "0"))
SPIN_GIF_URL = os.getenv("SPIN_GIF_URL", "")
COMMISSION_PERCENT = float(os.getenv("COMMISSION_PERCENT", "5.0"))
LEADERBOARD_CHANNEL_ID = int(os.getenv("LEADERBOARD_CHANNEL_ID", "0"))
RED_NUMBERS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
DB_PATH = "roulette.db"

# ---------- DATABASE ----------
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()
c.execute("""
CREATE TABLE IF NOT EXISTS stats (
    guild_id INTEGER,
    user_id INTEGER,
    mises INTEGER DEFAULT 0,
    net INTEGER DEFAULT 0,
    victoires INTEGER DEFAULT 0,
    defaites INTEGER DEFAULT 0,
    commissions INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
)
""")
c.execute("""
CREATE TABLE IF NOT EXISTS leaderboard_msg (
    guild_id INTEGER PRIMARY KEY,
    message_id INTEGER
)
""")
conn.commit()

def update_stats(guild_id, user_id, mise=0, net=0, victoire=False, commission=0):
    c.execute("SELECT * FROM stats WHERE guild_id=? AND user_id=?", (guild_id, user_id))
    row = c.fetchone()
    if row:
        mises_total = row[2] + mise
        net_total = row[3] + net
        victoires_total = row[4] + (1 if victoire else 0)
        defaites_total = row[5] + (0 if victoire else 1)
        commissions_total = row[6] + commission
        c.execute("""
        UPDATE stats SET mises=?, net=?, victoires=?, defaites=?, commissions=? 
        WHERE guild_id=? AND user_id=?
        """, (mises_total, net_total, victoires_total, defaites_total, commissions_total, guild_id, user_id))
    else:
        c.execute("""
        INSERT INTO stats(guild_id,user_id,mises,net,victoires,defaites,commissions)
        VALUES(?,?,?,?,?,?,?)
        """, (guild_id,user_id,mise,net,(1 if victoire else 0),(0 if victoire else 1), commission))
    conn.commit()

async def get_or_create_leaderboard_message(bot, guild):
    c.execute("SELECT message_id FROM leaderboard_msg WHERE guild_id=?", (guild.id,))
    row = c.fetchone()
    channel = guild.get_channel(LEADERBOARD_CHANNEL_ID)
    if not channel:
        return None
    if row:
        try:
            msg = await channel.fetch_message(row[0])
            return msg
        except:
            pass
    # create new message
    msg = await channel.send("📊 Leaderboard en cours de chargement…")
    c.execute("INSERT OR REPLACE INTO leaderboard_msg(guild_id,message_id) VALUES(?,?)", (guild.id,msg.id))
    conn.commit()
    return msg

async def update_leaderboard(bot, guild):
    msg = await get_or_create_leaderboard_message(bot, guild)
    if not msg:
        return
    c.execute("SELECT user_id,mises,net,victoires,defaites,commissions FROM stats WHERE guild_id=?", (guild.id,))
    rows = c.fetchall()
    if not rows:
        return
    # Tri joueurs
    rows.sort(key=lambda x: x[1], reverse=True)
    text = "📊 **Leaderboard joueurs**\n"
    for i,row in enumerate(rows,1):
        member = guild.get_member(row[0])
        name = member.display_name if member else f"ID:{row[0]}"
        text += f"{i}️⃣ **{name}** — Misé : {row[1]}k | Net : {row[2]}k | Victoires : {row[3]} | Défaites : {row[4]}\n"
    # Tri croupiers
    text += "\n📊 **Leaderboard croupiers**\n"
    croupiers = [row for row in rows if row[5] > 0]
    croupiers.sort(key=lambda x: x[5], reverse=True)
    for i,row in enumerate(croupiers,1):
        member = guild.get_member(row[0])
        name = member.display_name if member else f"ID:{row[0]}"
        text += f"{i}️⃣ **{name}** — Commissions : {row[5]}k\n"
    await msg.edit(content=text)

# ---------- COG ----------
class Roulette(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_duels = {}  # guild_id -> duel en cours

    @discord.app_commands.command(name="roulette", description="Lancer une roulette à deux joueurs (avec croupier)")
    @discord.app_commands.describe(mise="Mise en kamas (entier positif, minimum 1000)")
    async def roulette_cmd(self, interaction: discord.Interaction, mise: int):
        if mise < 1000:
            return await interaction.response.send_message("💸 La mise minimale est de **1000k**.", ephemeral=True)
        guild_id = interaction.guild.id

        # ---------- Embed principal initial ----------
        embed_main = discord.Embed(
            title="🎰 **Un joueur veut lancer la roulette !**",
            description=f"💠 **Joueur créateur :** {interaction.user.mention}\n💰 **Mise :** {mise}k",
            color=discord.Color.gold()
        )
        embed_main.set_footer(text="⌛ En attente du type de duel et du choix du camp…")
        await interaction.response.send_message(embed=embed_main)
        main_msg = await interaction.original_response()

        # ---------- Choix type duel ----------
        type_view = discord.ui.View(timeout=120)
        duel_type_result = {}

        async def select_type(inter2: discord.Interaction, t: str):
            duel_type_result['type'] = t
            type_view.stop()
            await inter2.response.defer()  # répond pour éviter timeout

        for label,t in [("🔴⚫ Rouge / Noir","couleur"),("⚖️ Pair / Impair","parite"),("1️⃣-18 / 19-36","intervalle")]:
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.primary)
            btn.callback = lambda inter, t=t: asyncio.create_task(select_type(inter, t))
            type_view.add_item(btn)

        embed_type = discord.Embed(
            title="🎯 Choisis le type de duel",
            description="Clique sur un bouton ci-dessous pour choisir le type de défi !",
            color=discord.Color.orange()
        )
        await interaction.channel.send(embed=embed_type, view=type_view)
        await type_view.wait()
        if 'type' not in duel_type_result:
            return await main_msg.edit(content="⏳ Duel annulé (aucun type choisi).", embed=None, view=None)

        duel_type = duel_type_result['type']

        # ---------- Choix camp ----------
        camp_view = discord.ui.View(timeout=120)
        camp_choice = {}

        async def select_camp(inter2: discord.Interaction, c: str):
            camp_choice['camp'] = c
            camp_view.stop()
            await inter2.response.defer()

        if duel_type=="couleur":
            options = [("🔴 Rouge","rouge"),("⚫ Noir","noir")]
        elif duel_type=="parite":
            options = [("Pair","pair"),("Impair","impair")]
        else:
            options = [("1-18","1-18"),("19-36","19-36")]

        for lbl,c in options:
            b = discord.ui.Button(label=lbl, style=discord.ButtonStyle.primary)
            b.callback = lambda inter, c=c: asyncio.create_task(select_camp(inter, c))
            camp_view.add_item(b)

        embed_camp = discord.Embed(
            title="🎯 Choisis ton camp",
            description="Clique sur un bouton ci-dessous pour sélectionner ton camp.",
            color=discord.Color.orange()
        )
        await interaction.channel.send(embed=embed_camp, view=camp_view)
        await camp_view.wait()
        if 'camp' not in camp_choice:
            return await main_msg.edit(content="⏳ Duel annulé (aucun camp choisi).", embed=None, view=None)

        starter_choice = camp_choice['camp']

        # ---------- Mise à jour embed principal ----------
        embed_main.add_field(name="🎲 Type de duel", value=duel_type.capitalize(), inline=True)
        embed_main.add_field(name="🏳️ Camp choisi", value=starter_choice.capitalize(), inline=True)
        embed_main.add_field(name="⏳ Statut", value="En attente d’un adversaire…", inline=False)
        await main_msg.edit(embed=embed_main)

        # ---------- Attente second joueur ----------
        join_view = discord.ui.View(timeout=300)
        joiner_result = {}

        async def join_callback(inter2: discord.Interaction):
            if inter2.user.id==interaction.user.id:
                await inter2.response.send_message("Tu es déjà le créateur.", ephemeral=True)
                return
            if joiner_result.get('user'):
                await inter2.response.send_message("Un adversaire a déjà rejoint.", ephemeral=True)
                return
            joiner_result['user']=inter2.user
            await inter2.response.send_message(f"{inter2.user.mention} a rejoint !", ephemeral=True)
            join_view.stop()

        btn_join = discord.ui.Button(label="🤝 Rejoindre", style=discord.ButtonStyle.success)
        btn_join.callback = join_callback
        join_view.add_item(btn_join)
        await main_msg.edit(embed=embed_main, view=join_view)

        # Barre animée
        bar = ["▯","▮▯","▮▮▯","▮▮▮▯","▮▮▮▮▯","▮▮▮▮▮"]
        for b in bar:
            if joiner_result.get('user'):
                break
            embed_main.set_field_at(2, name="⏳ Statut", value=f"En attente d’un adversaire… {b}", inline=False)
            await main_msg.edit(embed=embed_main)
            await asyncio.sleep(1)
        await join_view.wait()
        if 'user' not in joiner_result:
            return await main_msg.edit(content="⏳ Temps écoulé, personne n’a rejoint.", embed=None, view=None)

        joiner = joiner_result['user']

        # ---------- Validation croupier ----------
        val_view = discord.ui.View(timeout=120)
        validated = {}

        async def val_callback(inter2: discord.Interaction):
            if CROUPIER_ROLE_ID and not any(r.id==CROUPIER_ROLE_ID for r in inter2.user.roles):
                await inter2.response.send_message("Réservé au croupier.", ephemeral=True)
                return
            validated['c'] = inter2.user
            await inter2.response.send_message(f"Mises validées par {inter2.user.mention}", ephemeral=True)
            val_view.stop()

        btn_val = discord.ui.Button(label="✅ Valider mises", style=discord.ButtonStyle.success)
        btn_val.callback = val_callback
        val_view.add_item(btn_val)

        pot_total = mise*2
        commission = int(round(pot_total*(COMMISSION_PERCENT/100.0)))
        gain_net = pot_total - commission

        embed_main.add_field(name="👤 Joueurs", value=f"Créateur : {interaction.user.mention}\nAdversaire : {joiner.mention}", inline=False)
        embed_main.add_field(name="💰 Commission croupier", value=f"{commission}k", inline=True)
        embed_main.add_field(name="💸 Gain potentiel", value=f"{gain_net}k", inline=True)
        await interaction.channel.send(f"📢 {discord.Object(id=CROUPIER_ROLE_ID).mention} un croupier doit valider les mises !")
        await main_msg.edit(embed=embed_main, view=val_view)
        await val_view.wait()
        if 'c' not in validated:
            return await main_msg.edit(content="⏳ Temps écoulé, mises non validées par un croupier.", embed=None, view=None)

        croupier_user = validated['c']

        # ---------- Spin roulette ----------
        spin_embed = discord.Embed(title="🎡 La roulette tourne…", description="Bonne chance !", color=discord.Color.green())
        if SPIN_GIF_URL:
            spin_embed.set_image(url=SPIN_GIF_URL)
        spin_msg = await interaction.channel.send(embed=spin_embed)
        for i in range(5,0,-1):
            await spin_msg.edit(content=f"🎰 Roulettes en cours… {i}")
            await asyncio.sleep(1)

        n = random.randint(0,36)
        color = "vert" if n==0 else ("rouge" if n in RED_NUMBERS else "noir")
        parity = "pair" if n!=0 and n%2==0 else "impair"
        interval = "1-18" if 1<=n<=18 else ("19-36" if 19<=n<=36 else "0")

        def starter_wins():
            if duel_type=="couleur": return starter_choice==color
            if duel_type=="parite": return starter_choice==parity
            if duel_type=="intervalle": return starter_choice==interval
            return False

        winner = interaction.user if starter_wins() else joiner
        loser = joiner if winner==interaction.user else interaction.user

        # ---------- Résultat final ----------
        embed_main.clear_fields()
        embed_main.title = "✅ **Résultat de la roulette**"
        embed_main.color = discord.Color.green() if winner==interaction.user else discord.Color.red()
        embed_main.add_field(name="🎯 Nombre tiré", value=f"{n} ({color}) — {parity} — {interval}", inline=False)
        embed_main.add_field(name="🏆 Gagnant", value=winner.mention, inline=True)
        embed_main.add_field(name="💸 Gain net", value=f"{gain_net}k", inline=True)
        embed_main.add_field(name="💰 Commission croupier", value=f"{commission}k", inline=False)
        embed_main.add_field(name="👤 Joueurs", value=f"Créateur : {interaction.user.mention} ({starter_choice})\nAdversaire : {joiner.mention}", inline=False)
        embed_main.add_field(name="🎩 Croupier", value=croupier_user.mention, inline=True)
        await main_msg.edit(embed=embed_main, view=None)

        # ---------- Update stats + leaderboard ----------
        update_stats(guild_id, interaction.user.id, mise=mise, net=(gain_net-mise) if winner==interaction.user else -mise, victoire=(winner==interaction.user))
        update_stats(guild_id, joiner.id, mise=mise, net=(gain_net-mise) if winner==joiner else -mise, victoire=(winner==joiner))
        update_stats(guild_id, croupier_user.id, commission=commission)
        await update_leaderboard(self.bot, interaction.guild)

# ---------- Setup ----------
async def setup(bot: commands.Bot):
    await bot.add_cog(Roulette(bot))
