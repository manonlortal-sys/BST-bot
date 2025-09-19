import os
import random
import asyncio
import sqlite3
import discord
from discord.ext import commands

CROUPIER_ROLE_ID = int(os.getenv("CROUPIER_ROLE_ID", "0"))
SPIN_GIF_URL = os.getenv("SPIN_GIF_URL", "")
COMMISSION_PERCENT = float(os.getenv("COMMISSION_PERCENT", "5.0"))
LEADERBOARD_CHANNEL_ID = int(os.getenv("LEADERBOARD_CHANNEL_ID", "0"))

RED_NUMBERS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
DB_PATH = "roulette.db"

# ---------- Database setup ----------
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
    # Joueurs
    c.execute("SELECT user_id,mises,net,victoires,defaites,commissions FROM stats WHERE guild_id=?", (guild.id,))
    rows = c.fetchall()
    if not rows:
        return
    # Joueurs
    joueur_rows = sorted(rows, key=lambda x: x[1], reverse=True)
    # Croupiers
    croupier_rows = sorted([r for r in rows if r[5]>0], key=lambda x: x[5], reverse=True)
    text = "📊 **Leaderboard joueurs**\n"
    for i,row in enumerate(joueur_rows,1):
        member = guild.get_member(row[0])
        name = member.display_name if member else f"ID:{row[0]}"
        text += f"{i}️⃣ **{name}** — Misé : {row[1]}k | Net : {row[2]}k | Victoires : {row[3]} | Défaites : {row[4]}\n"
    text += "\n📊 **Leaderboard croupiers**\n"
    for i,row in enumerate(croupier_rows,1):
        member = guild.get_member(row[0])
        name = member.display_name if member else f"ID:{row[0]}"
        text += f"{i}️⃣ **{name}** — Commissions : {row[5]}k\n"
    await msg.edit(content=text)

# ---------- Cog ----------
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

        # 1️⃣ Embed principal initial
        main_embed = discord.Embed(
            title="🎰 **Un joueur veut lancer la roulette !**",
            description=f"Créateur : {interaction.user.mention}\nMise : {mise}k\nEn attente du type de duel et du choix du camp…",
            color=discord.Color.orange()
        )
        main_msg = await interaction.response.send_message(embed=main_embed)
        main_msg = await interaction.original_response()

        # 2️⃣ Choix type de duel (ephemeral pour le créateur)
        type_view = discord.ui.View(timeout=120)
        duel_type_result = {}

        async def select_type(inter, t):
            if inter.user.id != interaction.user.id:
                await inter.response.send_message("Seul le créateur peut choisir le type.", ephemeral=True)
                return
            duel_type_result['type'] = t
            type_view.stop()
            await inter.response.defer()  # pas de nouveau message

        for label,t in [("🔴 Rouge / ⚫ Noir","Rouge / Noir"),("⚖️ Pair / Impair","Pair / Impair"),("1️⃣-18 / 19-36","1-18 / 19-36")]:
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.primary)
            btn.callback = lambda inter, t=t: select_type(inter, t)
            type_view.add_item(btn)

        await interaction.user.send("Choisis le type de duel :", view=type_view)
        await type_view.wait()
        if 'type' not in duel_type_result:
            return await main_msg.edit(embed=discord.Embed(title="⏳ Duel annulé", description="Aucun type choisi.", color=discord.Color.red()))

        duel_type = duel_type_result['type']

        # 3️⃣ Choix du camp (ephemeral pour le créateur)
        camp_view = discord.ui.View(timeout=120)
        camp_choice = {}

        async def select_camp(inter, c):
            if inter.user.id != interaction.user.id:
                await inter.response.send_message("Seul le créateur peut choisir le camp.", ephemeral=True)
                return
            camp_choice['camp'] = c
            camp_view.stop()
            await inter.response.defer()

        camp_options = []
        if duel_type=="Rouge / Noir":
            camp_options = [("🔴 Rouge","Rouge"),("⚫ Noir","Noir")]
        elif duel_type=="Pair / Impair":
            camp_options = [("Pair","Pair"),("Impair","Impair")]
        else:
            camp_options = [("1-18","1-18"),("19-36","19-36")]

        for lbl,c in camp_options:
            b = discord.ui.Button(label=lbl, style=discord.ButtonStyle.primary)
            b.callback = lambda inter, c=c: select_camp(inter, c)
            camp_view.add_item(b)

        await interaction.user.send("Choisis ton camp :", view=camp_view)
        await camp_view.wait()
        if 'camp' not in camp_choice:
            return await main_msg.edit(embed=discord.Embed(title="⏳ Duel annulé", description="Aucun camp choisi.", color=discord.Color.red()))

        starter_choice = camp_choice['camp']

        # Mise à jour embed principal
        main_embed.description = f"Créateur : {interaction.user.mention}\nMise : {mise}k\nType de duel : {duel_type}\nCamp du créateur : {starter_choice}\nEn attente d’un adversaire…"
        await main_msg.edit(embed=main_embed)

        # 4️⃣ Attente adversaire avec barre animée
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
        await main_msg.edit(view=join_view)

        bar = ["▯▯▯▯▯","▮▯▯▯▯","▮▮▯▯▯","▮▮▮▯▯","▮▮▮▮▯","▮▮▮▮▮"]
        while not joiner_result.get('user'):
            for b in bar+bar[::-1][1:-1]:  # oscillation
                if joiner_result.get('user'):
                    break
                main_embed.description = f"Créateur : {interaction.user.mention}\nMise : {mise}k\nType de duel : {duel_type}\nCamp du créateur : {starter_choice}\nEn attente d’un adversaire… {b}"
                await main_msg.edit(embed=main_embed)
                await asyncio.sleep(0.5)
        await join_view.wait()
        if 'user' not in joiner_result:
            return await main_msg.edit(embed=discord.Embed(title="⏳ Duel annulé", description="Personne n’a rejoint.", color=discord.Color.red()), view=None)

        joiner = joiner_result['user']

        # 5️⃣ Croupier validation
        if CROUPIER_ROLE_ID:
            croupier_ping = f"<@&{CROUPIER_ROLE_ID}>"
        else:
            croupier_ping = "Croupier requis"

        await interaction.channel.send(f"📢 {croupier_ping}, un croupier doit valider les mises !")

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

        main_embed.description = f"Créateur : {interaction.user.mention} ({starter_choice})\nAdversaire : {joiner.mention}\nMises : {mise}k chacun\nPot total : {pot_total}k\n💰 Commission croupier ({COMMISSION_PERCENT}%): {commission}k\nEn attente de validation du croupier..."
        await main_msg.edit(embed=main_embed, view=val_view)
        await val_view.wait()
        if 'c' not in validated:
            return await main_msg.edit(embed=discord.Embed(title="⏳ Duel annulé", description="Mises non validées par un croupier.", color=discord.Color.red()), view=None)

        croupier_user = validated['c']

        # 6️⃣ Roulette animation
        spin_embed = discord.Embed(title="🎡 La roulette tourne…", description="Bonne chance !", color=discord.Color.orange())
        if SPIN_GIF_URL:
            spin_embed.set_image(url=SPIN_GIF_URL)
        spin_msg = await interaction.channel.send(embed=spin_embed)
        for i in range(5,0,-1):
            spin_embed.description = f"Roulette en cours… {i}"
            await spin_msg.edit(embed=spin_embed)
            await asyncio.sleep(1)
        await spin_msg.delete()  # disparait à la fin

        # 7️⃣ Résultat
        n = random.randint(0,36)
        color = "vert" if n==0 else ("rouge" if n in RED_NUMBERS else "noir")
        parity = "pair" if n!=0 and n%2==0 else "impair"
        interval = "1-18" if 1<=n<=18 else ("19-36" if 19<=n<=36 else "0")

        def starter_wins():
            if duel_type=="Rouge / Noir": return starter_choice.lower() in color.lower()
            if duel_type=="Pair / Impair": return starter_choice.lower() == parity
            if duel_type=="1-18 / 19-36": return starter_choice == interval
            return False

        winner = interaction.user if starter_wins() else joiner
        loser = joiner if winner==interaction.user else interaction.user

        main_embed.title = "✅ Résultat de la roulette"
        main_embed.color = discord.Color.green() if winner==interaction.user else discord.Color.red()
        main_embed.description = f"Nombre tiré : {n} ({color}) — {parity} — {interval}\nGagnant : {winner.mention}\nPerdant : {loser.mention}\nGain net : {gain_net}k\nCommission croupier : {commission}k\nCroupier : {croupier_user.mention}"
        await main_msg.edit(embed=main_embed, view=None)

        # 8️⃣ Stats + leaderboard
        update_stats(guild_id, interaction.user.id, mise=mise, net=(gain_net-mise) if winner==interaction.user else -mise, victoire=(winner==interaction.user))
        update_stats(guild_id, joiner.id, mise=mise, net=(gain_net-mise) if winner==joiner else -mise, victoire=(winner==joiner))
        update_stats(guild_id, croupier_user.id, commission=commission)
        await update_leaderboard(self.bot, interaction.guild)

    @discord.app_commands.command(name="stats", description="Voir vos stats personnelles")
    async def stats_cmd(self, interaction: discord.Interaction):
        c.execute("SELECT mises,net,victoires,defaites,commissions FROM stats WHERE guild_id=? AND user_id=?", (interaction.guild.id,interaction.user.id))
        row = c.fetchone()
        if not row:
            return await interaction.response.send_message("Aucune statistique pour vous.", ephemeral=True)
        embed = discord.Embed(title=f"📊 Stats de {interaction.user.display_name}", color=discord.Color.blurple())
        embed.add_field(name="Mises totales", value=f"{row[0]}k")
        embed.add_field(name="Gains/Pertes", value=f"{row[1]}k")
        embed.add_field(name="Victoires", value=f"{row[2]}")
        embed.add_field(name="Défaites", value=f"{row[3]}")
        embed.add_field(name="Commissions perçues", value=f"{row[4]}k")
        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(Roulette(bot))
