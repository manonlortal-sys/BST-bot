from __future__ import annotations
import os
import time
import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Optional, List, Tuple

import discord
from discord import app_commands
from discord.ext import commands

# ---------- ENV ----------
ALERT_CHANNEL_ID = int(os.getenv("ALERT_CHANNEL_ID", "0"))
LEADERBOARD_CHANNEL_ID = int(os.getenv("LEADERBOARD_CHANNEL_ID", "0"))
ROLE_DEF_ID = int(os.getenv("ROLE_DEF_ID", "0"))
ROLE_DEF2_ID = int(os.getenv("ROLE_DEF2_ID", "0"))
ROLE_TEST_ID = int(os.getenv("ROLE_TEST_ID", "0"))

# ---------- Constantes ----------
EMOJI_VICTORY = "🏆"
EMOJI_DEFEAT = "❌"
EMOJI_INCOMP = "😡"
EMOJI_JOIN = "👍"

DB_PATH = "defense_leaderboard.db"

BUCKETS = [
    ("🌅 Matin (6–10)", 6, 10),
    ("🌞 Journée (10–18)", 10, 18),
    ("🌙 Soir (18–00)", 18, 24),
    ("🌌 Nuit (00–6)", 0, 6),
]

def utcnow_i() -> int:
    return int(time.time())

# ---------- DB helpers ----------
def create_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages(
            message_id INTEGER PRIMARY KEY,
            guild_id   INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            created_ts INTEGER NOT NULL,
            outcome    TEXT,
            incomplete INTEGER,
            last_ts    INTEGER NOT NULL,
            creator_id INTEGER
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS participants(
            message_id INTEGER NOT NULL,
            user_id    INTEGER NOT NULL,
            PRIMARY KEY(message_id, user_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS leaderboard_posts(
            guild_id   INTEGER,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            type       TEXT NOT NULL,
            PRIMARY KEY (guild_id, type)
        )
    """)
    con.commit()
    con.close()

def with_db(func):
    def wrapper(*args, **kwargs):
        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row
        try:
            res = func(con, *args, **kwargs)
            con.commit()
            return res
        finally:
            con.close()
    return wrapper

# ---------- DB functions ----------
@with_db
def upsert_message(con: sqlite3.Connection, message: discord.Message, creator_id: Optional[int] = None):
    cur = con.cursor()
    cur.execute("""
        INSERT INTO messages(message_id, guild_id, channel_id, created_ts, outcome, incomplete, last_ts, creator_id)
        VALUES (?,?,?,?,NULL,0,?,?)
        ON CONFLICT(message_id) DO NOTHING
    """, (message.id, message.guild.id, message.channel.id,
          int(message.created_at.replace(tzinfo=timezone.utc).timestamp()), utcnow_i(), creator_id))

@with_db
def get_message_creator(con: sqlite3.Connection, message_id: int) -> Optional[int]:
    cur = con.cursor()
    cur.execute("SELECT creator_id FROM messages WHERE message_id=?", (message_id,))
    row = cur.fetchone()
    return row["creator_id"] if row else None

@with_db
def set_outcome(con: sqlite3.Connection, message_id: int, outcome: Optional[str]):
    cur = con.cursor()
    cur.execute("UPDATE messages SET outcome=?, last_ts=? WHERE message_id=?", (outcome, utcnow_i(), message_id))

@with_db
def set_incomplete(con: sqlite3.Connection, message_id: int, incomplete: bool):
    cur = con.cursor()
    cur.execute("UPDATE messages SET incomplete=?, last_ts=? WHERE message_id=?", (1 if incomplete else 0, utcnow_i(), message_id))

@with_db
def add_participant(con: sqlite3.Connection, message_id: int, user_id: int):
    cur = con.cursor()
    cur.execute("""
        INSERT INTO participants(message_id, user_id) VALUES (?,?)
        ON CONFLICT(message_id, user_id) DO NOTHING
    """, (message_id, user_id))

@with_db
def remove_participant(con: sqlite3.Connection, message_id: int, user_id: int):
    cur = con.cursor()
    cur.execute("DELETE FROM participants WHERE message_id=? AND user_id=?", (message_id, user_id))

@with_db
def get_leaderboard_post(con: sqlite3.Connection, guild_id: int, type_: str) -> Optional[Tuple[int,int]]:
    cur = con.cursor()
    cur.execute("SELECT channel_id, message_id FROM leaderboard_posts WHERE guild_id=? AND type=?", (guild_id, type_))
    row = cur.fetchone()
    return (row["channel_id"], row["message_id"]) if row else None

@with_db
def set_leaderboard_post(con: sqlite3.Connection, guild_id: int, channel_id: int, message_id: int, type_: str):
    cur = con.cursor()
    cur.execute("""
        INSERT INTO leaderboard_posts(guild_id, channel_id, message_id, type)
        VALUES (?,?,?,?)
        ON CONFLICT(guild_id, type) DO UPDATE SET channel_id=excluded.channel_id, message_id=excluded.message_id
    """, (guild_id, channel_id, message_id, type_))

@with_db
def agg_totals_all(con: sqlite3.Connection, guild_id: int) -> Tuple[int,int,int,int]:
    cur = con.cursor()
    cur.execute("""
        SELECT SUM(CASE WHEN outcome='win'  THEN 1 ELSE 0 END),
               SUM(CASE WHEN outcome='loss' THEN 1 ELSE 0 END),
               SUM(CASE WHEN incomplete=1  THEN 1 ELSE 0 END),
               COUNT(*)
        FROM messages
        WHERE guild_id=?
    """, (guild_id,))
    w,l,inc,tot = cur.fetchone()
    return (w or 0, l or 0, inc or 0, tot or 0)

@with_db
def top_defenders(con: sqlite3.Connection, guild_id: int, limit: int = 20) -> List[Tuple[int,int]]:
    cur = con.cursor()
    cur.execute("""
        SELECT p.user_id, COUNT(*) as cnt
        FROM participants p
        JOIN messages m ON m.message_id=p.message_id
        WHERE m.guild_id=?
        GROUP BY p.user_id
        ORDER BY cnt DESC
        LIMIT ?
    """, (guild_id, limit))
    return [(row["user_id"], row["cnt"]) for row in cur.fetchall()]

@with_db
def top_pingeurs(con: sqlite3.Connection, guild_id: int, limit: int = 20) -> List[Tuple[int,int]]:
    cur = con.cursor()
    cur.execute("""
        SELECT creator_id, COUNT(*) as cnt
        FROM messages
        WHERE guild_id=? AND creator_id IS NOT NULL
        GROUP BY creator_id
        ORDER BY cnt DESC
        LIMIT ?
    """, (guild_id, limit))
    return [(row["creator_id"], row["cnt"]) for row in cur.fetchall()]

@with_db
def hourly_split_7d(con: sqlite3.Connection, guild_id: int) -> list[int]:
    since = utcnow_i() - 7*24*3600
    cur = con.cursor()
    cur.execute("SELECT created_ts FROM messages WHERE guild_id=? AND created_ts>=?", (guild_id, since))
    counts = [0,0,0,0]
    for r in cur.fetchall():
        ts = r["created_ts"]
        h_local = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(ZoneInfo("Europe/Paris")).hour
        if 6 <= h_local <10: counts[0]+=1
        elif 10<=h_local<18: counts[1]+=1
        elif 18<=h_local<24: counts[2]+=1
        else: counts[3]+=1
    return counts

# ---------- DB pour /stats ----------
@with_db
def get_player_defenses(con, guild_id: int, user_id: int, limit: int = 3):
    cur = con.cursor()
    cur.execute("""
        SELECT m.message_id, m.channel_id, m.created_ts, m.outcome,
               GROUP_CONCAT(p2.user_id) as participants
        FROM messages m
        JOIN participants p1 ON p1.message_id = m.message_id AND p1.user_id = ?
        LEFT JOIN participants p2 ON p2.message_id = m.message_id
        WHERE m.guild_id = ?
        GROUP BY m.message_id
        ORDER BY m.created_ts DESC
        LIMIT ?
    """, (user_id, guild_id, limit))
    return cur.fetchall()

@with_db
def get_player_totals(con, guild_id:int, user_id:int):
    cur = con.cursor()
    cur.execute("""
        SELECT SUM(CASE WHEN m.outcome='win' THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN m.outcome='loss' THEN 1 ELSE 0 END) as losses,
               COUNT(*) as total
        FROM messages m
        JOIN participants p ON p.message_id = m.message_id
        WHERE m.guild_id=? AND p.user_id=?
    """,(guild_id,user_id))
    return cur.fetchone()

@with_db
def get_last_defeat(con, guild_id:int, user_id:int):
    cur = con.cursor()
    cur.execute("""
        SELECT created_ts FROM messages m
        JOIN participants p ON p.message_id = m.message_id
        WHERE m.guild_id=? AND p.user_id=? AND m.outcome='loss'
        ORDER BY created_ts DESC
        LIMIT 1
    """,(guild_id,user_id))
    row = cur.fetchone()
    return row["created_ts"] if row else None

@with_db
def get_favorite_partner(con, guild_id:int, user_id:int):
    cur = con.cursor()
    cur.execute("""
        SELECT p2.user_id, COUNT(*) as cnt
        FROM participants p1
        JOIN participants p2 ON p1.message_id = p2.message_id
        JOIN messages m ON m.message_id = p1.message_id
        WHERE m.guild_id=? AND p1.user_id=? AND p2.user_id!=?
        GROUP BY p2.user_id
        ORDER BY cnt DESC
        LIMIT 1
    """,(guild_id,user_id,user_id))
    row = cur.fetchone()
    return row["user_id"] if row else None

# ---------- Embed constructeur ----------
async def build_ping_embed(msg: discord.Message) -> discord.Embed:
    creator_id = get_message_creator(msg.id)
    creator_member = msg.guild.get_member(creator_id) if creator_id else None

    reactions = {str(r.emoji): r for r in msg.reactions}
    win  = (EMOJI_VICTORY in reactions and reactions[EMOJI_VICTORY].count > 0)
    loss = (EMOJI_DEFEAT in reactions and reactions[EMOJI_DEFEAT].count > 0)
    incomplete = (EMOJI_INCOMP in reactions and reactions[EMOJI_INCOMP].count > 0)

    if win and not loss:
        color = discord.Color.green()
        etat = f"{EMOJI_VICTORY} **Défense gagnée**"
        if incomplete: etat += f"\n{EMOJI_INCOMP} Défense incomplète"
    elif loss and not win:
        color = discord.Color.red()
        etat = f"{EMOJI_DEFEAT} **Défense perdue**"
        if incomplete: etat += f"\n{EMOJI_INCOMP} Défense incomplète"
    else:
        color = discord.Color.orange()
        etat = "⏳ **En cours / à confirmer**"
        if incomplete: etat += f"\n{EMOJI_INCOMP} Défense incomplète"

    defenders_ids: List[int] = []
    if EMOJI_JOIN in reactions:
        async for u in reactions[EMOJI_JOIN].users():
            if not u.bot:
                defenders_ids.append(u.id)
                add_participant(msg.id,u.id)
    names = [msg.guild.get_member(uid).display_name if msg.guild.get_member(uid) else f"<@{uid}>" for uid in defenders_ids[:20]]
    defenders_block = "• " + "\n• ".join(names) if names else "_Aucun défenseur pour le moment._"

    embed = discord.Embed(title="🛡️ Alerte Percepteur",
                          description="⚠️ **Connectez-vous pour prendre la défense !**",
                          color=color)
    embed.add_field(name="État du combat", value=etat, inline=False)
    embed.add_field(name="Défenseurs (👍)", value=defenders_block, inline=False)
    if creator_member: embed.add_field(name="⚡ Déclenché par", value=creator_member.display_name, inline=False)
    embed.set_footer(text="Ajoutez vos réactions : 🏆 gagné • ❌ perdu • 😡 incomplète • 👍 j'ai participé")
    return embed

# ---------- View boutons ----------
class PingButtonsView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Guilde 1", style=discord.ButtonStyle.primary)
    async def btn_def(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_click(interaction, "Def")

    @discord.ui.button(label="Guilde 2", style=discord.ButtonStyle.danger)
    async def btn_def2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_click(interaction, "Def2")

    @discord.ui.button(label="TEST (Admin)", style=discord.ButtonStyle.secondary)
    async def btn_test(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not any(r.permissions.administrator for r in interaction.user.roles):
            await interaction.response.send_message("Bouton réservé aux admins.", ephemeral=True)
            return
        await self._handle_click(interaction, "Test")

    async def _handle_click(self, interaction: discord.Interaction, side: str):
        await interaction.response.defer(ephemeral=True, thinking=False)
        guild = interaction.guild
        if guild is None or ALERT_CHANNEL_ID == 0: return

        alert_channel = guild.get_channel(ALERT_CHANNEL_ID)
        if not isinstance(alert_channel, discord.TextChannel): return

        role_id = 0
        if side=="Def": role_id=ROLE_DEF_ID
        elif side=="Def2": role_id=ROLE_DEF2_ID
        elif side=="Test": role_id=ROLE_TEST_ID

        role_mention = f"<@&{role_id}>" if role_id!=0 else ""
        content = f"{role_mention} — **Percepteur attaqué !** Merci de vous connecter." if role_mention else "**Percepteur attaqué !** Merci de vous connecter."

        msg = await alert_channel.send(content)
        upsert_message(msg, creator_id=interaction.user.id)
        emb = await build_ping_embed(msg)
        await msg.edit(embed=emb)
        await update_leaderboards(self.bot, guild)
        await interaction.followup.send("✅ Alerte envoyée.", ephemeral=True)

# ---------- Leaderboards ----------
async def update_leaderboards(bot: commands.Bot, guild: discord.Guild):
    channel = bot.get_channel(LEADERBOARD_CHANNEL_ID)
    if channel is None: return

    # Leaderboard Défense
    def_post = get_leaderboard_post(guild.id, "defense")
    if def_post:
        try: msg_def = await channel.fetch_message(def_post[1])
        except discord.NotFound: msg_def = await channel.send("📊 **Leaderboard Défense**"); set_leaderboard_post(guild.id, channel.id, msg_def.id, "defense")
    else: msg_def = await channel.send("📊 **Leaderboard Défense**"); set_leaderboard_post(guild.id, channel.id, msg_def.id, "defense")

    total_w, total_l, total_inc, total_att = agg_totals_all(guild.id)
    top_def = top_defenders(guild.id)
    hourly = hourly_split_7d(guild.id)

    top_block = "\n".join([f"• <@{uid}> : {cnt} défenses" for uid, cnt in top_def]) or "_Aucun défenseur encore_"
    ratio = f"{(total_w/total_att*100):.1f}%" if total_att else "0%"

    embed_def = discord.Embed(title="📊 Leaderboard Défense", color=discord.Color.blue())
    embed_def.add_field(name="Top défenseurs", value=top_block, inline=False)
    embed_def.add_field(name="Stats globales", value=f"Attaques : {total_att}\nVictoire : {total_w}\nDéfaites : {total_l}\nIncomplet : {total_inc}\nRatio victoire : {ratio}", inline=False)
    embed_def.add_field(name="Tranches horaires (7j)", value=f"🌅 Matin : {hourly[0]}\n🌞 Journée : {hourly[1]}\n🌙 Soir : {hourly[2]}\n🌌 Nuit : {hourly[3]}", inline=False)
    await msg_def.edit(embed=embed_def)

    # Leaderboard Pingeurs
    ping_post = get_leaderboard_post(guild.id, "pingeur")
    if ping_post:
        try: msg_ping = await channel.fetch_message(ping_post[1])
        except discord.NotFound: msg_ping = await channel.send("📊 **Leaderboard Pingeurs**"); set_leaderboard_post(guild.id, channel.id, msg_ping.id, "pingeur")
    else: msg_ping = await channel.send("📊 **Leaderboard Pingeurs**"); set_leaderboard_post(guild.id, channel.id, msg_ping.id, "pingeur")

    top_ping = top_pingeurs(guild.id)
    ping_block = "\n".join([f"• <@{uid}> : {cnt} pings" for uid, cnt in top_ping]) or "_Aucun pingeur encore_"
    embed_ping = discord.Embed(title="📊 Leaderboard Pingeurs", color=discord.Color.gold())
    embed_ping.add_field(name="Top Pingeurs", value=ping_block, inline=False)
    await msg_ping.edit(embed=embed_ping)

# ---------- Cog principal ----------
class PingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        create_db()

    @app_commands.command(name="pingpanel", description="Publier le panneau de ping des percepteurs (défenses)")
    async def pingpanel(self, interaction: discord.Interaction):
        view = PingButtonsView(self.bot)
        embed = discord.Embed(title="🛡️ Panneau de défense",
                              description="Cliquez sur les boutons ci-dessous pour déclencher une alerte.",
                              color=discord.Color.blue())
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

    # ---------- Commande /stats ----------
    @app_commands.command(name="stats", description="Afficher les stats de défense d'un joueur")
    @app_commands.describe(member="Le joueur dont vous voulez voir les stats (optionnel)")
    async def stats(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("Erreur : pas de guild.", ephemeral=True)
            return
    
        defenses = get_player_defenses(guild.id, target.id, limit=3)
        if not defenses:
            await interaction.response.send_message(f"{target.display_name} n'a aucune défense enregistrée.", ephemeral=False)
            return
    
        totals = get_player_totals(guild.id, target.id)
        total_def, total_wins, total_losses = totals["total"], totals["wins"], totals["losses"]
    
        partner_id = get_favorite_partner(guild.id, target.id)
        partner_text = f"<@{partner_id}>" if partner_id else "Personne"
    
        hourly_counts = hourly_split_7d(guild.id)
        top_bucket = hourly_counts.index(max(hourly_counts)) if sum(hourly_counts) > 0 else 1
        bucket_messages = [
            "🌅 Défenseur du Matin: Mini défend les percepteurs avant son café, prenez exemple !",
            "🌞 Défenseur de la Journée: Chômage, télétravail, flemme au bureau, Mini gère vos percos !",
            "🌙 Défenseur du Soir: Donnez à bouffer à vos gosses, Mini tient la baraque !",
            "🌌 Défenseur de la Nuit: Dormir c'est pour les faibles, Mini gère la garde de nuit"
        ]
        bucket_text = bucket_messages[top_bucket]
    
        # Construire les 3 dernières défenses avec emoji
        recent_blocks = []
        for d in defenses:
            date_str = datetime.fromtimestamp(d["created_ts"], tz=timezone.utc).astimezone(ZoneInfo("Europe/Paris")).strftime("%d/%m/%Y %H:%M")
            outcome = d["outcome"]
            if outcome == "win":
                outcome_text = f"Victoire"
            elif outcome == "loss":
                outcome_text = f"Défaite"
            else:
                outcome_text = f"En cours"
        
            other_users = ", ".join([f"<@{int(uid)}>" for uid in d["participants"].split(",") if uid]) if d["participants"] else "_Aucun autre défenseur_"
            recent_blocks.append(f"{outcome_text} le {date_str} avec {other_users}")

    
            other_users = ", ".join([f"<@{int(uid)}>" for uid in d["participants"].split(",") if uid]) if d["participants"] else "_Aucun autre défenseur_"
            recent_blocks.append(f"{emoji} {outcome_text} le {date_str} avec {other_users}")
    
        recent_text = "\n".join(recent_blocks)
    
        # Construction de l'embed
        embed = discord.Embed(
            title=f"📊 Stats de défense de {target.display_name}",
            color=discord.Color.orange()
        )
        embed.add_field(name="Stats générales", value=f"Total défenses : {total_def}\n🏆 Victoires : {total_wins}\n❌ Défaites : {total_losses}", inline=False)
        embed.add_field(name="3 dernières défenses", value=recent_text, inline=False)
        embed.add_field(name="Infos personnelles 😉",
                        value=f"{bucket_text}\n\n🛡️ Collègue de défenses 🛡️\nMini toujours en défense avec {partner_text}, prenez une chambre !",
                        inline=False)
    
        await interaction.response.send_message(embed=embed, ephemeral=False)
    
    # ---------- Autocomplétion ----------
    @stats.autocomplete("member")
    async def stats_autocomplete(interaction: discord.Interaction, current: str):
        guild = interaction.guild
        if not guild: return []
        return [
            app_commands.Choice(name=m.display_name, value=m.id)
            for m in guild.members if current.lower() in m.display_name.lower()
        ][:25]


    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User):
        if user.bot: return
        msg = reaction.message
        if msg.guild is None: return
        if str(reaction.emoji) in (EMOJI_VICTORY, EMOJI_DEFEAT, EMOJI_INCOMP, EMOJI_JOIN):
            if str(reaction.emoji)==EMOJI_JOIN: add_participant(msg.id,user.id)
            elif str(reaction.emoji)==EMOJI_VICTORY: set_outcome(msg.id,"win")
            elif str(reaction.emoji)==EMOJI_DEFEAT: set_outcome(msg.id,"loss")
            elif str(reaction.emoji)==EMOJI_INCOMP: set_incomplete(msg.id,True)
            emb = await build_ping_embed(msg)
            await msg.edit(embed=emb)
            await update_leaderboards(self.bot, msg.guild)

    @commands.Cog.listener()
    async def on_reaction_remove(self, reaction: discord.Reaction, user: discord.User):
        if user.bot: return
        msg = reaction.message
        if msg.guild is None: return
        if str(reaction.emoji) in (EMOJI_VICTORY, EMOJI_DEFEAT, EMOJI_INCOMP, EMOJI_JOIN):
            if str(reaction.emoji)==EMOJI_JOIN: remove_participant(msg.id,user.id)
            elif str(reaction.emoji)==EMOJI_VICTORY: set_outcome(msg.id,None)
            elif str(reaction.emoji)==EMOJI_DEFEAT: set_outcome(msg.id,None)
            elif str(reaction.emoji)==EMOJI_INCOMP: set_incomplete(msg.id,False)
            emb = await build_ping_embed(msg)
            await msg.edit(embed=emb)
            await update_leaderboards(self.bot, msg.guild)

    async def cog_load(self):
        print(f"{self.__class__.__name__} chargé")

# ---------- Setup ----------
async def setup(bot: commands.Bot):
    cog = PingCog(bot)
    await bot.add_cog(cog)

    TEST_GUILD_ID = 1280234399610179634
    test_guild = discord.Object(id=TEST_GUILD_ID)

    # Ajouter manuellement les commandes au tree pour la guild de test
    bot.tree.add_command(cog.pingpanel, guild=test_guild)
    bot.tree.add_command(cog.stats, guild=test_guild)

    await bot.tree.sync(guild=test_guild)


