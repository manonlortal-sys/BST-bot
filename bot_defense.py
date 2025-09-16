# =========================
#  Bot Unifié – Défense + Roulette (Render Web Service)
#  Fichier: bot_defense.py
#  - Préfixe: !defstats, !liste, !alliance, !alliances7j, !graphic
#  - Slash:   /roulette [mise] (kamas)
#  - Multi-lobbies autorisés par salon (roulette)
#  - Compte à rebours 5→1 avec GIF de spin
# =========================

# --- Réglages pour Render/Matplotlib (headless) ---
import os
os.environ.setdefault("MPLBACKEND", "Agg")

# --- Imports standard ---
import io
import threading
import random
import asyncio
import re
from dataclasses import dataclass
from typing import Optional, Dict, List, Tuple
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# --- Discord & Flask ---
import discord
from discord import app_commands
from discord.ext import commands
from flask import Flask

# --- Matplotlib (pour les graphs) ---
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# --- Env ---
from dotenv import load_dotenv
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# =========================
#  Mini serveur HTTP (Web Service) – occupe le port $PORT exigé par Render
# =========================
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot Discord actif"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_flask, daemon=True).start()

# =========================
#  Constantes / Intents
# =========================
CHANNEL_ID = 1327548733398843413  # <-- remplace si besoin
LOCAL_TZ = "Europe/Paris"

# Intents: commandes préfixées nécessitent message_content=True
intents = discord.Intents.default()
intents.guilds = True
intents.reactions = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# =========================
#  CONFIG visuelle Roulette
# =========================
SPIN_GIF_URL = os.getenv("SPIN_GIF_URL", "https://media.tenor.com/e3QG3W1u3lAAAAAC/roulette-casino.gif")
THUMB_URL = os.getenv("THUMB_URL", "")  # optionnel

COLOR_RED = 0xE74C3C
COLOR_BLACK = 0x2C3E50
COLOR_GREEN = 0x2ECC71
COLOR_GOLD = 0xF1C40F

# Numéros rouges (roulette européenne)
RED_NUMBERS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}

# =========================
#  Aide: détection mention @Def / @Def2
# =========================
def message_mentionne_def(message: discord.Message) -> bool:
    def_roles = {"Def", "Def2"}
    for role in message.role_mentions:
        if role.name in def_roles:
            return True
    for embed in message.embeds:
        if embed.description and ("@def" in embed.description.lower() or "@def2" in embed.description.lower()):
            return True
        if embed.title and ("@def" in embed.title.lower() or "@def2" in embed.title.lower()):
            return True
    content_lower = (message.content or "").lower()
    if "@def" in content_lower or "@def2" in content_lower:
        return True
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
#  Commandes Défense (préfixe)
# =========================
@bot.command()
async def defstats(ctx: commands.Context):
    now = datetime.now(ZoneInfo(LOCAL_TZ))
    one_week_ago = now - timedelta(days=7)
    channel = bot.get_channel(CHANNEL_ID)
    if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.ForumChannel)):
        await ctx.send("Channel introuvable ou non textuel.")
        return

    victory_emoji, defeat_emoji, rage_emoji, thumbsup_emoji = "🏆", "❌", "😡", "👍"
    victory_count = defeat_count = rage_count = checked_messages = def1_count = def2_count = simultaneous_count = 0
    thumbsup_stats: Dict[int, Dict[str, object]] = defaultdict(lambda: {"count": 0, "name": ""})
    attaque_par_alliance: Dict[str, int] = defaultdict(int)

    alliances = ["La Bande", "Ateam", "Intmi", "Clan Oshimo", "Ivory", "La Secte", "Gueux randoms"]
    last_ping_time: Optional[datetime] = None

    async for message in channel.history(limit=None, after=one_week_ago, oldest_first=True):
        if message.author != bot.user and message_mentionne_def(message):
            if last_ping_time and (message.created_at - last_ping_time).total_seconds() < 15:
                continue
            last_ping_time = message.created_at

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

            utilisateurs_comptes: set[int] = set()
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
                            thumbsup_stats[user_react.id]["count"] = int(thumbsup_stats[user_react.id]["count"]) + 1
                            thumbsup_stats[user_react.id]["name"] = name

            for member in message.mentions:
                if not member.bot and member.id not in utilisateurs_comptes:
                    utilisateurs_comptes.add(member.id)
                    thumbsup_stats[member.id]["count"] = int(thumbsup_stats[member.id]["count"]) + 1
                    thumbsup_stats[member.id]["name"] = member.display_name

            for a in alliances:
                if a.lower() in content_lower:
                    attaque_par_alliance[a] += 1
                for embed in message.embeds:
                    if embed.description and a.lower() in (embed.description or "").lower():
                        attaque_par_alliance[a] += 1
                    if embed.title and a.lower() in (embed.title or "").lower():
                        attaque_par_alliance[a] += 1

    embed_color = 0x2ecc71 if victory_count >= defeat_count and victory_count >= rage_count else (0xe67e22 if defeat_count >= rage_count else 0xe74c3c)
    embed = discord.Embed(title="📊 Statistiques des Défenses – 7 derniers jours", description="Résumé des attaques sur les percepteurs avec participation des défenseurs.", color=embed_color)
    embed.add_field(name="📍 Défenses détectées", value=f"`{checked_messages}`", inline=True)
    embed.add_field(name="🏰 Attaques sur Guilde 1", value=f"`{def1_count}`", inline=True)
    embed.add_field(name="🗼 Attaques sur Guilde 2", value=f"`{def2_count}`", inline=True)
    embed.add_field(name="🌿 Simultanées", value=f"`{simultaneous_count}`", inline=True)
    embed.add_field(name="\u200B", value="**🎯 Résultats des combats**", inline=False)
    embed.add_field(name="🏆 Victoires", value=f"`{victory_count}`", inline=True)
    embed.add_field(name="❌ Défaites", value=f"`{defeat_count}`", inline=True)
    embed.add_field(name="😡 Incomplètes", value=f"`{rage_count}`", inline=True)

    if thumbsup_stats:
        alias_mapping: Dict[int, int] = {1383914690270466048: 994240541585854574}
        fusion_stats: Dict[int, Dict[str, object]] = defaultdict(lambda: {"count": 0, "name": ""})
        for user_id, data in thumbsup_stats.items():
            mapped = alias_mapping.get(user_id, user_id)
            fusion_stats[mapped]["count"] = int(fusion_stats[mapped]["count"]) + int(data["count"])  # type: ignore
            if not fusion_stats[mapped]["name"] or user_id == mapped:
                fusion_stats[mapped]["name"] = data["name"]
        sorted_defenders = sorted(fusion_stats.values(), key=lambda x: int(x["count"]), reverse=True)
        lines = [f"{u['name']:<40} | {u['count']}" for u in sorted_defenders]
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


@bot.command()
async def liste(ctx: commands.Context):
    now = datetime.now(ZoneInfo(LOCAL_TZ))
    one_week_ago = now - timedelta(days=7)
    channel = bot.get_channel(CHANNEL_ID)
    if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.ForumChannel)):
        await ctx.send("Channel introuvable ou non textuel.")
        return
    thumbsup_stats: Dict[int, Dict[str, object]] = defaultdict(lambda: {"count": 0, "name": ""})
    async for message in channel.history(limit=None, after=one_week_ago, oldest_first=True):
        if message_mentionne_def(message):
            utilisateurs_comptes: set[int] = set()
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
                            thumbsup_stats[user_react.id]["count"] = int(thumbsup_stats[user_react.id]["count"]) + 1
                            thumbsup_stats[user_react.id]["name"] = name
            for member in message.mentions:
                if not member.bot and member.id not in utilisateurs_comptes:
                    utilisateurs_comptes.add(member.id)
                    thumbsup_stats[member.id]["count"] = int(thumbsup_stats[member.id]["count"]) + 1
                    thumbsup_stats[member.id]["name"] = member.display_name
    if thumbsup_stats:
        sorted_defenders = sorted(thumbsup_stats.values(), key=lambda x: int(x["count"]), reverse=True)
        lines = [f"{u['name']} : {u['count']} def" for u in sorted_defenders]
        await ctx.send("\n".join(lines))
    else:
        await ctx.send("Aucun défenseur détecté dans les dernières 24h.")


@bot.command()
async def alliance(ctx: commands.Context):
    now = datetime.now(ZoneInfo(LOCAL_TZ))
    one_week_ago = now - timedelta(days=7)
    channel = bot.get_channel(CHANNEL_ID)
    if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.ForumChannel)):
        await ctx.send("Channel introuvable ou non textuel.")
        return
    attaques: List[int] = []
    async for message in channel.history(limit=None, after=one_week_ago, oldest_first=True):
        content_lower = (message.content or "").lower()
        for embed in message.embeds:
            content_lower += f" {(embed.title or '')} {(embed.description or '')}".lower()
        if any(a.lower() in content_lower for a in [
            "Vae Victis", "Horizon", "Eclipse", "New Era",
            "Autre alliance, merci de préciser la guilde", "Destin"
        ]):
            local_time = message.created_at.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo(LOCAL_TZ))
            attaques.append(local_time.hour)
    if not attaques:
        await ctx.send("Aucune attaque détectée dans les 7 derniers jours.")
        return
    tranches = [f"{h:02d}h-{(h+2)%24:02d}h" for h in range(0, 24, 2)]
    compteur = [0] * 12
    for heure in attaques:
        compteur[heure // 2] += 1
    plt.figure(figsize=(6, 6))
    plt.pie(compteur, labels=tranches, autopct=lambda p: f'{int(round(p*sum(compteur)/100))}' if p>0 else '', startangle=90)
    plt.title("Répartition des attaques par tranches horaires (7 jours)")
    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight")
    buf.seek(0)
    plt.close()
    await ctx.send(file=discord.File(buf, filename="attaques.png"))


@bot.command(name="alliances7j")
async def alliances7j(ctx: commands.Context):
    tz = ZoneInfo(LOCAL_TZ)
    now = datetime.now(tz)
    since = now - timedelta(days=7)
    ALLIANCES_MAP: Dict[str, str] = {
        "vae victis": "Vae Victis",
        "horizon": "Horizon",
        "eclipse": "Eclipse",
        "new era": "New Era",
        "destin": "Destin",
        "autre alliance, merci de préciser la guilde": "Autre alliance (à préciser)",
    }
    channel = bot.get_channel(CHANNEL_ID)
    if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.ForumChannel)):
        await ctx.send("Channel introuvable ou non textuel.")
        return
    def detect_alliance(text_lower: str) -> Optional[str]:
        for key, label in ALLIANCES_MAP.items():
            if key in text_lower:
                return label
        return None
    entries: List[Tuple[datetime, str, str]] = []
    async for message in channel.history(limit=None, after=since, oldest_first=True):
        parts = [(message.content or "")]
        for e in message.embeds:
            parts.append(e.title or ""); parts.append(e.description or "")
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
    entries.sort(key=lambda x: x[0])
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


@bot.command()
async def graphic(ctx: commands.Context):
    channel = bot.get_channel(CHANNEL_ID)
    if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.ForumChannel)):
        await ctx.send("Channel introuvable ou non textuel.")
        return
    messages: List[discord.Message] = []
    async for message in channel.history(limit=5000):
        if message.author == bot.user and message.embeds:
            messages.append(message)
        if len(messages) >= 10:
            break
    messages = sorted(messages, key=lambda m: m.created_at)
    if not messages:
        await ctx.send("Aucun message de statistiques trouvé.")
        return
    dates: List[datetime] = []
    victories: List[int] = []
    defeats: List[int] = []
    incompletes: List[int] = []
    totals: List[int] = []
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
        vic_n = int(vic.group(1)); defe_n = int(defe.group(1)); inc_n = int(inc.group(1)); tot_n = int(tot.group(1))
        if tot_n == 0:
            continue
        dates.append(msg.created_at.replace(tzinfo=timezone.utc))
        victories.append(vic_n); defeats.append(defe_n); incompletes.append(inc_n); totals.append(tot_n)
    if not dates:
        await ctx.send("Pas assez de données exploitables pour créer un graphique.")
        return
    victories_pct = [v / t * 100 for v, t in zip(victories, totals)]
    defeats_pct = [d / t * 100 for d, t in zip(defeats, totals)]
    incompletes_pct = [i / t * 100 for i, t in zip(incompletes, totals)]
    plt.figure(figsize=(10, 6))
    plt.plot(dates, victories_pct, label="🏆 Victoires (%)", color="green", marker='o')
    plt.plot(dates, defeats_pct, label="❌ Défaites (%)", color="red", marker='o')
    plt.plot(dates, incompletes_pct, label="😡 Incomplètes (%)", color="orange", marker='o')
    plt.title("Évolution des Pourcentages de Défenses")
    plt.xlabel("Date"); plt.ylabel("Pourcentage (%)")
    plt.ylim(0, 100); plt.grid(True, linestyle='--', alpha=0.5); plt.legend()
    plt.gcf().autofmt_xdate(); plt.gca().xaxis.set_major_locator(mdates.AutoDateLocator()); plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%d/%m %H:%M'))
    plt.tight_layout(); buf1 = io.BytesIO(); plt.savefig(buf1, format='png', dpi=150); plt.close()
    plt.figure(figsize=(10, 6))
    plt.plot(dates, victories, label="🏆 Victoires", color="green", marker='o')
    plt.plot(dates, defeats, label="❌ Défaites", color="red", marker='o')
    plt.plot(dates, incompletes, label="😡 Incomplètes", color="orange", marker='o')
    plt.plot(dates, totals, label="📍 Défenses détectées", color="blue", marker='o')
    plt.title("Évolution des Nombres Absolus de Défenses")
    plt.xlabel("Date"); plt.ylabel("Nombre")
    plt.grid(True, linestyle='--', alpha=0.5); plt.legend()
    plt.gcf().autofmt_xdate(); plt.gca().xaxis.set_major_locator(mdates.AutoDateLocator()); plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%d/%m %H:%M'))
    plt.tight_layout(); buf2 = io.BytesIO(); plt.savefig(buf2, format='png', dpi=150); plt.close()
    buf1.seek(0); buf2.seek(0)
    await ctx.send(file=discord.File(fp=buf1, filename="defenses_pourcentages.png"))
    await ctx.send(file=discord.File(fp=buf2, filename="defenses_valeurs.png"))

# =========================
#  Roulette (slash command) – multi-lobbies par salon
# =========================
@dataclass
class RouletteGame:
    channel_id: int
    starter_id: int
    bet: int = 0
    joiner_id: Optional[int] = None
    choice: Optional[str] = None  # "rouge" | "noir"
    lobby_msg_id: Optional[int] = None
    spin_msg_id: Optional[int] = None

active_games: Dict[int, List[RouletteGame]] = {}

def spin_wheel() -> Tuple[int, str]:
    n = random.randint(0, 36)
    if n == 0:
        return n, "vert"
    return n, ("rouge" if n in RED_NUMBERS else "noir")

def color_for_embed(color: str) -> int:
    return COLOR_GREEN if color == "vert" else (COLOR_RED if color == "rouge" else COLOR_BLACK)

def add_game(game: RouletteGame) -> None:
    active_games.setdefault(game.channel_id, []).append(game)

def remove_game(game: RouletteGame) -> None:
    lst = active_games.get(game.channel_id, [])
    if game in lst:
        lst.remove(game)
    if not lst:
        active_games.pop(game.channel_id, None)

class ChoiceView(discord.ui.View):
    def __init__(self, game: RouletteGame, *, timeout: float = 45.0):
        super().__init__(timeout=timeout)
        self.game = game

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.game.starter_id:
            await interaction.response.send_message("Seul le **créateur** de la partie peut choisir la couleur.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Rouge", style=discord.ButtonStyle.danger, emoji="🔴")
    async def btn_rouge(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.resolve(interaction, "rouge")

    @discord.ui.button(label="Noir", style=discord.ButtonStyle.secondary, emoji="⚫")
    async def btn_noir(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.resolve(interaction, "noir")

    async def on_timeout(self) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        try:
            channel = bot.get_channel(self.game.channel_id)
            if self.game.lobby_msg_id:
                msg = await channel.fetch_message(self.game.lobby_msg_id)
                await msg.edit(view=self)
            await channel.send("⏳ **Temps écoulé** – partie annulée.")
        except Exception:
            pass
        remove_game(self.game)

    async def resolve(self, interaction: discord.Interaction, choice: str):
        self.game.choice = choice
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

        title = f"🎰 **SPIN EN COURS !**"
        desc_base = (
            f"**👥 Joueurs** : <@{self.game.starter_id}> vs <@{self.game.joiner_id}>\n"
            f"**🎯 Choix du lanceur** : **{choice.upper()}** {'🔴' if choice=='rouge' else '⚫'}\n"
            f"**💵 Mise** : **{self.game.bet} kamas**\n\n"
            f"⌛ *La roue tourne...* *cling* *cling* *cling*\n"
        )
        spin_embed = discord.Embed(title=title, description=desc_base + "**Compte à rebours : 5**", color=COLOR_GOLD)
        if THUMB_URL:
            spin_embed.set_thumbnail(url=THUMB_URL)
        if SPIN_GIF_URL:
            spin_embed.set_image(url=SPIN_GIF_URL)
        spin_embed.set_footer(text="Casino Cartoon • Bonne chance ! ✨")

        await interaction.response.edit_message(content=None, embed=spin_embed, view=self)
        sent = await interaction.original_response()
        self.game.spin_msg_id = sent.id

        channel = interaction.channel
        for t in [4,3,2,1]:
            await asyncio.sleep(1.0)
            try:
                msg = await channel.fetch_message(self.game.spin_msg_id)
                spin_embed.description = desc_base + f"**Compte à rebours : {t}**"
                await msg.edit(embed=spin_embed, view=self)
            except Exception:
                break
        await asyncio.sleep(1.0)

        n, color = spin_wheel()
        winner = self.game.starter_id if color == choice else self.game.joiner_id
        loser = self.game.joiner_id if winner == self.game.starter_id else self.game.starter_id
        color_emoji = "🔴" if color == "rouge" else ("⚫" if color == "noir" else "🟢")

        title_res = f"🏁 **RÉSULTAT : {n} {color_emoji} ({color.upper()})**"
        if winner and loser:
            desc_res = (
                f"**🏆 Gagnant** : <@{winner}>  **+{self.game.bet}** kamas 💰\n"
                f"**💤 Perdant** : <@{loser}>  **-{self.game.bet}** kamas 🪙\n\n"
                f"🎯 *Choix du lanceur* : **{choice.upper()}**\n"
                f"🎡 *Merci d'avoir joué ! Rejouez avec* **/roulette**"
            )
        else:
            desc_res = "❗ Erreur : la partie n'avait pas 2 joueurs."

        result_embed = discord.Embed(title=title_res, description=desc_res, color=color_for_embed(color))
        if THUMB_URL:
            result_embed.set_thumbnail(url=THUMB_URL)
        result_embed.set_footer(text="Casino Cartoon • Jouez responsablement 🎲")

        try:
            msg = await channel.fetch_message(self.game.spin_msg_id)
            await msg.edit(embed=result_embed, view=self)
        except Exception:
            await interaction.followup.send(embed=result_embed)

        remove_game(self.game)

# Slash: créer/rejoindre
@bot.tree.command(name="roulette", description="Créer/Rejoindre une roulette à 2 joueurs (mise en kamas)")
@app_commands.describe(mise="Montant virtuel à miser (en kamas, optionnel)")
async def roulette_cmd(interaction: discord.Interaction, mise: Optional[int] = 0):
    if mise is None:
        mise = 0
    if mise < 0:
        return await interaction.response.send_message("La mise ne peut pas être négative.", ephemeral=True)

    channel_id = interaction.channel_id
    user_id = interaction.user.id

    # Chercher un lobby ouvert (non plein) dans CE salon, créé par un autre joueur
    open_lobbies = [g for g in active_games.get(channel_id, []) if g.joiner_id is None and g.starter_id != user_id]

    if open_lobbies:
        game = open_lobbies[0]
        game.joiner_id = user_id
        view = ChoiceView(game)

        title = "👥 **JOUEUR REJOINT !**"
        desc = (
            f"**Joueurs** : <@{game.starter_id}> **vs** <@{game.joiner_id}>\n"
            f"**💵 Mise** : **{game.bet} kamas**\n\n"
            f"<@{game.starter_id}>, choisis ta couleur : **ROUGE** 🔴 ou **NOIR** ⚫."
        )
        embed = discord.Embed(title=title, description=desc, color=COLOR_GOLD)
        if THUMB_URL:
            embed.set_thumbnail(url=THUMB_URL)
        embed.set_footer(text="Casino Cartoon • Choix du lanceur 🎯")

        try:
            channel = interaction.channel
            msg = await channel.fetch_message(game.lobby_msg_id) if game.lobby_msg_id else None
            if msg:
                await msg.edit(embed=embed, view=view)
                await interaction.response.send_message("Tu as rejoint la partie !", ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, view=view)
                sent = await interaction.original_response()
                game.lobby_msg_id = sent.id
        except Exception:
            await interaction.response.send_message(embed=embed, view=view)
            sent = await interaction.original_response()
            game.lobby_msg_id = sent.id
        return

    # Sinon: créer un NOUVEAU lobby (on autorise plusieurs lobbies par salon)
    game = RouletteGame(channel_id=channel_id, starter_id=user_id, bet=mise)
    add_game(game)

    title = "🎲 **ROULETTE – LOBBY OUVERT**"
    desc = (
        f"**Créateur** : <@{user_id}>\n"
        f"**💵 Mise** : **{mise} kamas**\n\n"
        f"➡️ *Un second joueur tape* **/roulette** *dans les 5 minutes pour rejoindre.*\n"
        f"Le créateur choisira ensuite **ROUGE** ou **NOIR**."
    )
    embed = discord.Embed(title=title, description=desc, color=COLOR_GOLD)
    if THUMB_URL:
        embed.set_thumbnail(url=THUMB_URL)
    embed.set_footer(text="Casino Cartoon • Attente d'un adversaire ⏳")

    await interaction.response.send_message(embed=embed)
    sent = await interaction.original_response()
    game.lobby_msg_id = sent.id

    # Timeout de lobby (5 minutes)
    async def lobby_timeout():
        await asyncio.sleep(300)
        for g in list(active_games.get(channel_id, [])):
            if g is game and g.joiner_id is None:
                try:
                    channel = interaction.channel
                    msg = await channel.fetch_message(g.lobby_msg_id) if g.lobby_msg_id else None
                    if msg:
                        try:
                            await msg.edit(view=None)
                        except Exception:
                            pass
                    await channel.send(f"⏳ **Lobby expiré** (créé par <@{g.starter_id}>).")
                except Exception:
                    pass
                remove_game(g)
                break
    bot.loop.create_task(lobby_timeout())

# =========================
#  Sync & Run
# =========================
@bot.event
async def on_ready():
    try:
        await bot.tree.sync()
    except Exception as e:
        print("Sync error:", e)
    print(f"Connecté en tant que {bot.user} (ID: {bot.user.id})")

if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN manquant (fichier .env)")
    bot.run(TOKEN)
