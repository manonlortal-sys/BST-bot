# =========================
#  Bot Défense – Discord
#  (Render Web Service)
# =========================

# --- Réglages pour Render/Matplotlib (headless) ---
import os
os.environ.setdefault("MPLBACKEND", "Agg")

# --- Imports standard ---
import io
import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# --- Discord & Flask ---
import discord
from discord.ext import commands
from flask import Flask

# --- Matplotlib (pour les graphs) ---
import matplotlib.pyplot as plt


# =========================
#  Mini serveur HTTP (Web Service)
#  -> occupe le port $PORT exigé par Render
# =========================
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot Discord actif"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# Lance Flask en arrière-plan
threading.Thread(target=run_flask, daemon=True).start()


# =========================
#  Constantes / Intents
# =========================
CHANNEL_ID = 1327548733398843413  # <-- remplace si besoin
LOCAL_TZ = "Europe/Paris"

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.reactions = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)
occurences = defaultdict(int)


# =========================
#  Aide: détection mention @Def / @Def2
# =========================
def message_mentionne_def(message: discord.Message) -> bool:
    def_roles = {"Def", "Def2"}

    # Mentions de rôles
    for role in message.role_mentions:
        if role.name in def_roles:
            return True

    # Mentions textuelles dans embeds
    for embed in message.embeds:
        if embed.description and ("@def" in embed.description.lower() or "@def2" in embed.description.lower()):
            return True
        if embed.title and ("@def" in embed.title.lower() or "@def2" in embed.title.lower()):
            return True

    # Mentions textuelles dans le contenu
    content_lower = (message.content or "").lower()
    if "@def" in content_lower or "@def2" in content_lower:
        return True

    # Messages de bots (ex: webhooks)
    if message.author.bot:
        if "@def" in content_lower or "@def2" in content_lower:
            return True
        for embed in message.embeds:
            if embed.description and ("@def" in embed.description.lower() or "@def2" in embed.description.lower()):
                return True
            if embed.title and ("@def" in embed.title.lower() or "@def2" in embed.title.lower()):
                return True

    return False


# =========================
#  Commande: !defstats
# =========================
@bot.command()
async def defstats(ctx: commands.Context):
    now = datetime.now(ZoneInfo(LOCAL_TZ))
    one_week_ago = now - timedelta(days=7)
    channel = bot.get_channel(CHANNEL_ID)

    victory_emoji = "🏆"
    defeat_emoji = "❌"
    rage_emoji = "😡"
    thumbsup_emoji = "👍"

    victory_count = 0
    defeat_count = 0
    rage_count = 0
    checked_messages = 0
    def1_count = 0
    def2_count = 0
    simultaneous_count = 0
    thumbsup_stats = defaultdict(lambda: {"count": 0, "name": ""})
    attaque_par_alliance = defaultdict(int)

    alliances = ["La Bande", "Ateam", "Intmi", "Clan Oshimo", "Ivory", "La Secte", "Gueux randoms"]
    last_ping_time = None

    async for message in channel.history(limit=None, after=one_week_ago, oldest_first=True):
        if message.author != bot.user and message_mentionne_def(message):
            # anti-doublons trop rapprochés
            if last_ping_time and (message.created_at - last_ping_time).total_seconds() < 15:
                continue
            last_ping_time = message.created_at

            # Détection Def / Def2
            mentions_def1 = any(role.name.lower() == "def" for role in message.role_mentions)
            mentions_def2 = any(role.name.lower() == "def2" for role in message.role_mentions)

            for embed in message.embeds:
                if embed.description:
                    desc = embed.description.lower()
                    mentions_def1 |= "@def" in desc
                    mentions_def2 |= "@def2" in desc
                if embed.title:
                    title = embed.title.lower()
                    mentions_def1 |= "@def" in title
                    mentions_def2 |= "@def2" in title

            content_lower = (message.content or "").lower()
            mentions_def1 |= "@def" in content_lower
            mentions_def2 |= "@def2" in content_lower

            checked_messages += 1
            if mentions_def1 and mentions_def2:
                simultaneous_count += 1
            elif mentions_def1:
                def1_count += 1
            elif mentions_def2:
                def2_count += 1

            # Réactions utiles
            utilisateurs_comptes = set()
            for reaction in message.reactions:
                if str(reaction.emoji) == victory_emoji:
                    victory_count += 1
                elif str(reaction.emoji) == defeat_emoji:
                    defeat_count += 1
                elif str(reaction.emoji) == rage_emoji:
                    rage_count += 1
                elif str(reaction.emoji) == thumbsup_emoji:
                    async for user_react in reaction.users():
                        if not user_react.bot and user_react.id not in utilisateurs_comptes:
                            utilisateurs_comptes.add(user_react.id)
                            try:
                                member = await ctx.guild.fetch_member(user_react.id)
                                name = member.display_name
                            except Exception:
                                name = user_react.name
                            thumbsup_stats[user_react.id]["count"] += 1
                            thumbsup_stats[user_react.id]["name"] = name

            # Mentions directes (compte la participation)
            for member in message.mentions:
                if not member.bot and member.id not in utilisateurs_comptes:
                    utilisateurs_comptes.add(member.id)
                    thumbsup_stats[member.id]["count"] += 1
                    thumbsup_stats[member.id]["name"] = member.display_name

            # Comptage par alliances
            for alliance in alliances:
                if alliance.lower() in content_lower:
                    attaque_par_alliance[alliance] += 1
                for embed in message.embeds:
                    if embed.description and alliance.lower() in (embed.description or "").lower():
                        attaque_par_alliance[alliance] += 1
                    if embed.title and alliance.lower() in (embed.title or "").lower():
                        attaque_par_alliance[alliance] += 1

    # Couleur de l'embed selon le score dominant
    embed_color = 0x2ecc71 if victory_count >= defeat_count and victory_count >= rage_count \
        else (0xe67e22 if defeat_count >= rage_count else 0xe74c3c)

    embed = discord.Embed(
        title="📊 Statistiques des Défenses – 7 derniers jours",
        description="Résumé des attaques sur les percepteurs avec participation des défenseurs.",
        color=embed_color
    )
    embed.add_field(name="📍 Défenses détectées", value=f"`{checked_messages}`", inline=True)
    embed.add_field(name="🏰 Attaques sur Guilde 1", value=f"`{def1_count}`", inline=True)
    embed.add_field(name="🗼 Attaques sur Guilde 2", value=f"`{def2_count}`", inline=True)
    embed.add_field(name="🌿 Simultanées", value=f"`{simultaneous_count}`", inline=True)
    embed.add_field(name="\u200B", value="**🎯 Résultats des combats**", inline=False)
    embed.add_field(name="🏆 Victoires", value=f"`{victory_count}`", inline=True)
    embed.add_field(name="❌ Défaites", value=f"`{defeat_count}`", inline=True)
    embed.add_field(name="😡 Incomplètes", value=f"`{rage_count}`", inline=True)

    # Top défenseurs (👍 + mentions)
    if thumbsup_stats:
        # Fusion d'alias éventuels (IDs → IDs)
        alias_mapping_raw = {
            "1383914690270466048": "994240541585854574",
        }
        alias_mapping: dict[int, int] = {}
        for k, v in alias_mapping_raw.items():
            if k.isdigit() and v.isdigit():
                alias_mapping[int(k)] = int(v)

        fusion_stats = defaultdict(lambda: {"count": 0, "name": ""})
        for user_id, data in thumbsup_stats.items():
            mapped = alias_mapping.get(user_id, user_id)
            fusion_stats[mapped]["count"] += data["count"]
            if not fusion_stats[mapped]["name"] or user_id == mapped:
                fusion_stats[mapped]["name"] = data["name"]

        sorted_defenders = sorted(fusion_stats.values(), key=lambda x: x["count"], reverse=True)
        lines = [f"{user['name']:<40} | {user['count']}" for user in sorted_defenders]
        header = f"{'Défenseur':<40} | Def\n{'-'*40} | ----"

        chunks = [header]
        for line in lines:
            if len(chunks[-1]) + len(line) + 1 > 950:
                chunks.append(header)
            chunks[-1] += f"\n{line}"

        for i, chunk in enumerate(chunks):
            title = "🧙 Top Défenseurs" if i == 0 else f"⬇️ Suite ({i+1})"
            embed.add_field(name=title, value=f"```{chunk}```", inline=False)
    else:
        embed.add_field(name="🧙 Top Défenseurs", value="Aucun défenseur cette dernière journée 😴", inline=False)

    embed.set_footer(text=f"Mise à jour : {datetime.utcnow().strftime('%d/%m/%Y à %H:%M UTC')}")
    await ctx.send(embed=embed)


# =========================
#  Commande: !liste
# =========================
@bot.command()
async def liste(ctx: commands.Context):
    now = datetime.now(ZoneInfo(LOCAL_TZ))
    one_week_ago = now - timedelta(days=7)
    channel = bot.get_channel(CHANNEL_ID)
    thumbsup_stats = defaultdict(lambda: {"count": 0, "name": ""})

    async for message in channel.history(limit=None, after=one_week_ago, oldest_first=True):
        if message_mentionne_def(message):
            utilisateurs_comptes = set()
            for reaction in message.reactions:
                if str(reaction.emoji) == "👍":
                    async for user_react in reaction.users():
                        if not user_react.bot and user_react.id not in utilisateurs_comptes:
                            utilisateurs_comptes.add(user_react.id)
                            try:
                                member = await ctx.guild.fetch_member(user_react.id)
                                name = member.display_name
                            except Exception:
                                name = user_react.name
                            thumbsup_stats[user_react.id]["count"] += 1
                            thumbsup_stats[user_react.id]["name"] = name

            for member in message.mentions:
                if not member.bot and member.id not in utilisateurs_comptes:
                    utilisateurs_comptes.add(member.id)
                    thumbsup_stats[member.id]["count"] += 1
                    thumbsup_stats[member.id]["name"] = member.display_name

    if thumbsup_stats:
        sorted_defenders = sorted(thumbsup_stats.values(), key=lambda x: x["count"], reverse=True)
        lines = [f"{user['name']} : {user['count']} def" for user in sorted_defenders]
        await ctx.send("\n".join(lines))
    else:
        await ctx.send("Aucun défenseur détecté dans les dernières 24h.")


# =========================
#  Commande: !alliance
#   (répartition horaire par 2h sur 7 jours)
# =========================
@bot.command()
async def alliance(ctx: commands.Context):
    now = datetime.now(ZoneInfo(LOCAL_TZ))
    one_week_ago = now - timedelta(days=7)
    channel = bot.get_channel(CHANNEL_ID)

    attaques = []

    async for message in channel.history(limit=None, after=one_week_ago, oldest_first=True):
        content_lower = (message.content or "").lower()
        for embed in message.embeds:
            content_lower += f" {(embed.title or '')} {(embed.description or '')}".lower()

        if any(alliance.lower() in content_lower for alliance in [
            "Vae Victis", "Horizon", "Eclipse", "New Era",
            "Autre alliance, merci de préciser la guilde", "Destin"
        ]):
            local_time = message.created_at.replace(
                tzinfo=ZoneInfo("UTC")
            ).astimezone(ZoneInfo(LOCAL_TZ))
            attaques.append(local_time.hour)

    if not attaques:
        await ctx.send("Aucune attaque détectée dans les 7 derniers jours.")
        return

    # Comptage par tranches de 2 heures
    tranches = [f"{h:02d}h-{(h+2)%24:02d}h" for h in range(0, 24, 2)]
    compteur = [0] * 12

    for heure in attaques:
        index = heure // 2
        compteur[index] += 1

    # Camembert
    plt.figure(figsize=(6, 6))
    plt.pie(
        compteur,
        labels=tranches,
        autopct=lambda p: f'{int(round(p*sum(compteur)/100))}' if p > 0 else '',
        startangle=90
    )
    plt.title("Répartition des attaques par tranches horaires (7 jours)")

    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight")
    buf.seek(0)
    plt.close()

    file = discord.File(buf, filename="attaques.png")
    await ctx.send(file=file)


# =========================
#  Commande: !alliances7j
#   (liste chronologique avec liens)
# =========================
@bot.command(name="alliances7j")
async def alliances7j(ctx: commands.Context):
    tz = ZoneInfo(LOCAL_TZ)
    now = datetime.now(tz)
    since = now - timedelta(days=7)

    ALLIANCES_MAP = {
        "vae victis": "Vae Victis",
        "horizon": "Horizon",
        "eclipse": "Eclipse",
        "new era": "New Era",
        "destin": "Destin",
        "autre alliance, merci de préciser la guilde": "Autre alliance (à préciser)",
        # "clan oshimo": "Clan Oshimo",
        # "ivory": "Ivory",
        # "la secte": "La Secte",
        # "ateam": "ATeam",
        # "la bande": "La Bande",
        # "intmi": "INTMI",
        # "gueux randoms": "Gueux randoms",
    }

    channel = bot.get_channel(CHANNEL_ID)
    if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.ForumChannel)):
        await ctx.send("Channel introuvable ou non textuel.")
        return

    def detect_alliance(text_lower: str) -> str | None:
        for key, label in ALLIANCES_MAP.items():
            if key in text_lower:
                return label
        return None

    entries: list[tuple[datetime, str, str]] = []  # (datetime_local, alliance_label, jump_url)

    async for message in channel.history(limit=None, after=since, oldest_first=True):
        parts = [(message.content or "")]
        for e in message.embeds:
            parts.append(e.title or "")
            parts.append(e.description or "")
        text_lower = " ".join(parts).lower()

        alliance = detect_alliance(text_lower)
        if alliance:
            created_utc = message.created_at
            if created_utc.tzinfo is None:
                created_utc = created_utc.replace(tzinfo=timezone.utc)
            dt_local = created_utc.astimezone(tz)
            entries.append((dt_local, alliance, message.jump_url))

    if not entries:
        await ctx.send("Aucune attaque détectée dans les **48 dernières heures**.")
        return

    # Tri chrono
    entries.sort(key=lambda x: x[0])

    # Envoi en plusieurs messages si nécessaire
    def fmt_line(dt: datetime, alliance: str, url: str) -> str:
        return f"{dt.strftime('%d/%m %H:%M')} — {alliance} — {url}"

    header = "📅 **Attaques détectées sur 7 jours (heure locale)**\n"
    block = header
    for dt_local, alliance, url in entries:
        line = fmt_line(dt_local, alliance, url) + "\n"
        if len(block) + len(line) > 1800:
            await ctx.send(block)
            block = ""
        block += line

    if block:
        await ctx.send(block)


# =========================
#  Commande: !graphic
#   (génère 2 graphs à partir des embeds postés par le bot)
# =========================
@bot.command()
async def graphic(ctx: commands.Context):
    channel = bot.get_channel(CHANNEL_ID)
    messages = []
    async for message in channel.history(limit=5000):
        if message.author == bot.user and message.embeds:
            messages.append(message)
        if len(messages) >= 10:
            break
    messages = sorted(messages, key=lambda m: m.created_at)  # Chrono

    if not messages:
        await ctx.send("Aucun message de statistiques trouvé.")
        return

    import re
    import matplotlib.dates as mdates

    dates = []
    victories = []
    defeats = []
    incompletes = []
    totals = []

    # Regex patterns
    regex_vic = re.compile(r"🏆 Victoires\s*`(\d+)`", re.IGNORECASE)
    regex_def = re.compile(r"❌ Défaites\s*`(\d+)`", re.IGNORECASE)
    regex_inc = re.compile(r"😡 Incomplètes\s*`(\d+)`", re.IGNORECASE)
    regex_tot = re.compile(r"📍 Défenses détectées\s*`(\d+)`", re.IGNORECASE)

    for msg in messages:
        embed = msg.embeds[0]
        text_to_search = (embed.description or "") + "\n"
        for field in embed.fields:
            text_to_search += field.name + "\n" + (field.value or "") + "\n"

        vic = regex_vic.search(text_to_search)
        defe = regex_def.search(text_to_search)
        inc = regex_inc.search(text_to_search)
        tot = regex_tot.search(text_to_search)

        if not (vic and defe and inc and tot):
            continue

        vic_n = int(vic.group(1))
        defe_n = int(defe.group(1))
        inc_n = int(inc.group(1))
        tot_n = int(tot.group(1))
        if tot_n == 0:
            continue

        dates.append(msg.created_at.replace(tzinfo=timezone.utc))
        victories.append(vic_n)
        defeats.append(defe_n)
        incompletes.append(inc_n)
        totals.append(tot_n)

    if not dates:
        await ctx.send("Pas assez de données exploitables pour créer un graphique.")
        return

    # Calcul pourcentages
    victories_pct = [v / t * 100 for v, t in zip(victories, totals)]
    defeats_pct = [d / t * 100 for d, t in zip(defeats, totals)]
    incompletes_pct = [i / t * 100 for i, t in zip(incompletes, totals)]

    # Graphique 1 : Pourcentages
    plt.figure(figsize=(10, 6))
    plt.plot(dates, victories_pct, label="🏆 Victoires (%)", color="green", marker='o')
    plt.plot(dates, defeats_pct, label="❌ Défaites (%)", color="red", marker='o')
    plt.plot(dates, incompletes_pct, label="😡 Incomplètes (%)", color="orange", marker='o')
    plt.title("Évolution des Pourcentages de Défenses")
    plt.xlabel("Date")
    plt.ylabel("Pourcentage (%)")
    plt.ylim(0, 100)
    plt.grid(True, linestyle='--', alpha=0.5)
    plt.legend()
    plt.gcf().autofmt_xdate()
    plt.gca().xaxis.set_major_locator(mdates.AutoDateLocator())
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%d/%m %H:%M'))
    plt.tight_layout()
    buf1 = io.BytesIO()
    plt.savefig(buf1, format='png', dpi=150)
    plt.close()

    # Graphique 2 : Valeurs absolues
    plt.figure(figsize=(10, 6))
    plt.plot(dates, victories, label="🏆 Victoires", color="green", marker='o')
    plt.plot(dates, defeats, label="❌ Défaites", color="red", marker='o')
    plt.plot(dates, incompletes, label="😡 Incomplètes", color="orange", marker='o')
    plt.plot(dates, totals, label="📍 Défenses détectées", color="blue", marker='o')
    plt.title("Évolution des Nombres Absolus de Défenses")
    plt.xlabel("Date")
    plt.ylabel("Nombre")
    plt.grid(True, linestyle='--', alpha=0.5)
    plt.legend()
    plt.gcf().autofmt_xdate()
    plt.gca().xaxis.set_major_locator(mdates.AutoDateLocator())
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%d/%m %H:%M'))
    plt.tight_layout()
    buf2 = io.BytesIO()
    plt.savefig(buf2, format='png', dpi=150)
    plt.close()

    buf1.seek(0)
    buf2.seek(0)

    await ctx.send(file=discord.File(fp=buf1, filename="defenses_pourcentages.png"))
    await ctx.send(file=discord.File(fp=buf2, filename="defenses_valeurs.png"))


# =========================
#  Démarrage du bot
# =========================
@bot.event
async def on_ready():
    print(f"Bot connecté: {bot.user} (ID: {bot.user.id})")

"""
Discord Casino Bot
- Python 3.10+
- Libraries: discord.py, aiosqlite, python-dotenv

Features
- Virtual currency (no real money!).
- /balance, /daily, /leaderboard
- /coinflip, /roulette, /slots, /blackjack
- Admin: /casino give, /casino set

IMPORTANT: Check your local laws and Discord ToS. This bot is for **virtual fun only**.
"""
import asyncio
import os
import random
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

DB_PATH = "casino.db"
START_BALANCE = 1000
DAILY_REWARD = 250
DAILY_COOLDOWN_HOURS = 20
MIN_BET = 10
MAX_BET = 100_000

# Odds / payouts
ROULETTE_RED_BLACK_PAYOUT = 2  # 1:1 + stake (i.e., double)
ROULETTE_GREEN_PAYOUT = 15     # 14:1 simplified for fun (actual single-zero is 35:1)
ROULETTE_NUMBER_PAYOUT = 36    # 35:1 typical; we add stake by multiplying by 36 total

SLOTS_REELS = [
    ["🍒", "🍋", "🍇", "🔔", "⭐", "7️⃣"],
    ["🍒", "🍋", "🍇", "🔔", "⭐", "7️⃣"],
    ["🍒", "🍋", "🍇", "🔔", "⭐", "7️⃣"],
]
SLOTS_PAYOUTS = {
    ("7️⃣", "7️⃣", "7️⃣"): 20,  # 19:1 profit
    ("⭐", "⭐", "⭐"): 10,
    ("🔔", "🔔", "🔔"): 7,
    ("🍇", "🍇", "🍇"): 5,
    ("🍋", "🍋", "🍋"): 3,
    ("🍒", "🍒", "🍒"): 2,
}

BLACKJACK_DECK = [
    "A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"
] * 4

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN", "PLEASE_SET_TOKEN")
GUILD_IDS = os.getenv("GUILD_IDS", "").strip()
if GUILD_IDS:
    GUILD_IDS = [int(x) for x in GUILD_IDS.split(",") if x.strip().isdigit()]
else:
    GUILD_IDS = None

intents = discord.Intents.default()
intents.members = False
intents.message_content = False

bot = commands.Bot(command_prefix="!", intents=intents)

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

async def db_init():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS users(
                user_id INTEGER PRIMARY KEY,
                balance INTEGER NOT NULL,
                last_daily INTEGER
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                change INTEGER NOT NULL,
                reason TEXT,
                ts INTEGER NOT NULL
            )
            """
        )
        await db.commit()

async def get_balance(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if row is None:
            await db.execute("INSERT INTO users(user_id, balance, last_daily) VALUES(?,?,?)",
                             (user_id, START_BALANCE, None))
            await db.commit()
            return START_BALANCE
        return int(row[0])

async def set_balance(user_id: int, new_balance: int, reason: str | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO users(user_id, balance) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET balance=excluded.balance",
                         (user_id, new_balance))
        await db.execute("INSERT INTO transactions(user_id, change, reason, ts) VALUES(?,?,?,?)",
                         (user_id, 0, f"set -> {new_balance} ({reason or 'n/a'})", int(time.time())))
        await db.commit()

async def add_balance(user_id: int, delta: int, reason: str):
    bal = await get_balance(user_id)
    new_bal = max(0, bal + delta)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO users(user_id, balance) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET balance=?",
                         (user_id, new_bal, new_bal))
        await db.execute("INSERT INTO transactions(user_id, change, reason, ts) VALUES(?,?,?,?)",
                         (user_id, delta, reason, int(time.time())))
        await db.commit()
    return new_bal

async def get_last_daily(user_id: int) -> int | None:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT last_daily FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return None if row is None or row[0] is None else int(row[0])

async def set_last_daily(user_id: int, ts: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO users(user_id, balance, last_daily) VALUES(?,?,?) \n             ON CONFLICT(user_id) DO UPDATE SET last_daily=excluded.last_daily",
            (user_id, START_BALANCE, ts),
        )
        await db.commit()

# ---------- Utilities ----------

def check_bet(amount: int) -> str | None:
    if amount < MIN_BET:
        return f"Mise minimale: {MIN_BET}."
    if amount > MAX_BET:
        return f"Mise maximale: {MAX_BET}."
    return None

async def ensure_funds(user_id: int, amount: int) -> bool:
    return (await get_balance(user_id)) >= amount

# ---------- Bot lifecycle ----------
@bot.event
async def on_ready():
    await db_init()
    try:
        if GUILD_IDS:
            for gid in GUILD_IDS:
                guild = discord.Object(id=gid)
                await bot.tree.sync(guild=guild)
        else:
            await bot.tree.sync()
    except Exception as e:
        print("Sync error:", e)
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

# ---------- Core commands ----------
@bot.tree.command(name="balance", description="Voir ton solde")
async def balance_cmd(interaction: discord.Interaction):
    bal = await get_balance(interaction.user.id)
    await interaction.response.send_message(f"💰 **Solde:** {bal}")

@bot.tree.command(name="daily", description="Réclamer la récompense quotidienne")
async def daily_cmd(interaction: discord.Interaction):
    uid = interaction.user.id
    last = await get_last_daily(uid)
    now_ts = int(time.time())
    if last is not None and now_ts - last < DAILY_COOLDOWN_HOURS * 3600:
        remaining = DAILY_COOLDOWN_HOURS * 3600 - (now_ts - last)
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        return await interaction.response.send_message(
            f"⏳ Reviens dans **{hours}h {minutes}m** pour la prochaine daily.")
    await add_balance(uid, DAILY_REWARD, "daily")
    await set_last_daily(uid, now_ts)
    await interaction.response.send_message(
        f"🎁 Tu gagnes **{DAILY_REWARD}** pièces !")

@bot.tree.command(name="leaderboard", description="Top joueurs par solde")
async def leaderboard_cmd(interaction: discord.Interaction):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id, balance FROM users ORDER BY balance DESC LIMIT 10")
        rows = await cur.fetchall()
    lines = []
    for i, (uid, bal) in enumerate(rows, start=1):
        member = interaction.guild.get_member(uid)
        name = member.display_name if member else f"<@{uid}>"
        lines.append(f"**{i}.** {name} — {bal}")
    if not lines:
        lines = ["Personne encore. Joue pour apparaître ici!"]
    await interaction.response.send_message("🏆 **Leaderboard**\n" + "\n".join(lines))

# ---------- Games ----------
@bot.tree.command(name="coinflip", description="Pile ou face")
@app_commands.describe(amount="Montant à miser", side="pile ou face")
async def coinflip_cmd(interaction: discord.Interaction, amount: int, side: str):
    side = side.lower().strip()
    if side not in {"pile", "face"}:
        return await interaction.response.send_message("Choisis 'pile' ou 'face'.")
    msg = check_bet(amount)
    if msg:
        return await interaction.response.send_message(msg)
    uid = interaction.user.id
    if not await ensure_funds(uid, amount):
        return await interaction.response.send_message("Solde insuffisant.")
    result = "pile" if secrets.randbelow(2) == 0 else "face"
    if result == side:
        new_bal = await add_balance(uid, amount, f"coinflip win ({result})")
        await interaction.response.send_message(f"🪙 C'est **{result}** ! Tu **gagnes {amount}**. Nouveau solde: {new_bal}")
    else:
        new_bal = await add_balance(uid, -amount, f"coinflip loss ({result})")
        await interaction.response.send_message(f"🪙 C'est **{result}** ! Tu **perds {amount}**. Nouveau solde: {new_bal}")

@bot.tree.command(name="roulette", description="Roulette: rouge/noir/vert ou nombre 0-36")
@app_commands.describe(amount="Montant", bet="'rouge', 'noir', 'vert' ou un nombre 0-36")
async def roulette_cmd(interaction: discord.Interaction, amount: int, bet: str):
    msg = check_bet(amount)
    if msg:
        return await interaction.response.send_message(msg)
    uid = interaction.user.id
    if not await ensure_funds(uid, amount):
        return await interaction.response.send_message("Solde insuffisant.")

    bet_l = bet.lower().strip()
    number_bet: int | None = None
    color_bet: str | None = None

    if bet_l in {"rouge", "noir", "vert"}:
        color_bet = bet_l
    else:
        if bet_l.isdigit():
            n = int(bet_l)
            if 0 <= n <= 36:
                number_bet = n
            else:
                return await interaction.response.send_message("Le nombre doit être entre 0 et 36.")
        else:
            return await interaction.response.send_message("Pari invalide.")

    wheel = list(range(37))
    result = secrets.choice(wheel)

    # Determine color (single-zero wheel approximation)
    if result == 0:
        color = "vert"
    else:
        # Simple mapping: even=rouge, odd=noir (not realistic table, but fine for fun)
        color = "rouge" if result % 2 == 0 else "noir"

    win = False
    payout = 0
    if number_bet is not None:
        if result == number_bet:
            win = True
            payout = amount * ROULETTE_NUMBER_PAYOUT
    else:
        if color_bet == color:
            win = True
            if color_bet in {"rouge", "noir"}:
                payout = amount * ROULETTE_RED_BLACK_PAYOUT
            elif color_bet == "vert":
                payout = amount * ROULETTE_GREEN_PAYOUT

    if win:
        delta = payout - amount  # net profit
        new_bal = await add_balance(uid, delta, f"roulette win ({result} {color})")
        await interaction.response.send_message(
            f"🎡 Résultat: **{result}** ({color}). Tu gagnes **{payout}** (profit +{delta}).\nNouveau solde: {new_bal}")
    else:
        new_bal = await add_balance(uid, -amount, f"roulette loss ({result} {color})")
        await interaction.response.send_message(
            f"🎡 Résultat: **{result}** ({color}). Tu perds **{amount}**.\nNouveau solde: {new_bal}")

@bot.tree.command(name="slots", description="Machine à sous 3x1")
@app_commands.describe(amount="Montant à miser")
async def slots_cmd(interaction: discord.Interaction, amount: int):
    msg = check_bet(amount)
    if msg:
        return await interaction.response.send_message(msg)
    uid = interaction.user.id
    if not await ensure_funds(uid, amount):
        return await interaction.response.send_message("Solde insuffisant.")

    spin = [secrets.choice(reel) for reel in SLOTS_REELS]
    key = tuple(spin)

    if key in SLOTS_PAYOUTS:
        mult = SLOTS_PAYOUTS[key]
        payout = amount * mult
        delta = payout - amount
        new_bal = await add_balance(uid, delta, f"slots win {''.join(spin)}")
        await interaction.response.send_message(
            f"🎰 | {' '.join(spin)} | **Gagné {payout}** (profit +{delta}). Nouveau solde: {new_bal}")
    else:
        new_bal = await add_balance(uid, -amount, f"slots loss {''.join(spin)}")
        await interaction.response.send_message(
            f"🎰 | {' '.join(spin)} | **Perdu {amount}**. Nouveau solde: {new_bal}")

# --- Simple one-hand blackjack (auto-resolve) ---

def bj_value(hand: list[str]) -> int:
    total = 0
    aces = 0
    for c in hand:
        if c in {"J", "Q", "K"}:
            total += 10
        elif c == "A":
            aces += 1
            total += 11
        else:
            total += int(c)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total

@bot.tree.command(name="blackjack", description="Blackjack (résolution auto)")
@app_commands.describe(amount="Montant à miser")
async def blackjack_cmd(interaction: discord.Interaction, amount: int):
    msg = check_bet(amount)
    if msg:
        return await interaction.response.send_message(msg)
    uid = interaction.user.id
    if not await ensure_funds(uid, amount):
        return await interaction.response.send_message("Solde insuffisant.")

    deck = BLACKJACK_DECK.copy()
    secrets.SystemRandom().shuffle(deck)

    player = [deck.pop(), deck.pop()]
    dealer = [deck.pop(), deck.pop()]

    # Simple strategy: player hits until 17+
    while bj_value(player) < 17:
        player.append(deck.pop())
    while bj_value(dealer) < 17:
        dealer.append(deck.pop())

    pv = bj_value(player)
    dv = bj_value(dealer)

    if pv > 21:
        new_bal = await add_balance(uid, -amount, f"blackjack bust {pv} vs {dv}")
        return await interaction.response.send_message(
            f"🃏 Tes cartes: {player} ({pv}) | Croupier: {dealer} ({dv})\n**BUST !** Tu perds {amount}. Solde: {new_bal}")
    if dv > 21 or pv > dv:
        # 1:1 payout
        new_bal = await add_balance(uid, amount, f"blackjack win {pv} vs {dv}")
        return await interaction.response.send_message(
            f"🃏 Tes cartes: {player} ({pv}) | Croupier: {dealer} ({dv})\n**Gagné !** +{amount}. Solde: {new_bal}")
    if pv == dv:
        # push
        bal = await get_balance(uid)
        return await interaction.response.send_message(
            f"🃏 Tes cartes: {player} ({pv}) | Croupier: {dealer} ({dv})\n**Égalité.** Mise rendue. Solde: {bal}")

    new_bal = await add_balance(uid, -amount, f"blackjack loss {pv} vs {dv}")
    await interaction.response.send_message(
        f"🃏 Tes cartes: {player} ({pv}) | Croupier: {dealer} ({dv})\n**Perdu.** -{amount}. Solde: {new_bal}")

# ---------- Admin group ----------
class CasinoAdmin(commands.GroupCog, name="casino"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__()

    @app_commands.command(name="give", description="Ajouter des pièces à un joueur (admin)")
    @app_commands.describe(user="Membre", amount="Montant")
    async def give(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Réservé aux admins.")
        new_bal = await add_balance(user.id, amount, f"admin give by {interaction.user.id}")
        await interaction.response.send_message(f"✅ {user.mention} reçoit **{amount}**. Solde: {new_bal}")

    @app_commands.command(name="set", description="Définir le solde d'un joueur (admin)")
    @app_commands.describe(user="Membre", amount="Nouveau solde")
    async def set_(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Réservé aux admins.")
        await set_balance(user.id, amount, reason=f"admin set by {interaction.user.id}")
        await interaction.response.send_message(f"✅ Solde de {user.mention} défini à **{amount}**.")

async def setup_group():
    await bot.add_cog(CasinoAdmin(bot))

@bot.event
async def setup_hook():
    await setup_group()

if __name__ == "__main__":
    if TOKEN == "PLEASE_SET_TOKEN":
        print("\n[!] Set DISCORD_TOKEN in your .env file.\n")
    bot.run(TOKEN)


token = os.getenv("DISCORD_TOKEN")
if not token:
    raise SystemExit("DISCORD_TOKEN manquant")

bot.run(token)
