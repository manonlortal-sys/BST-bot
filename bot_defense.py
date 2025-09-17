# =========================
#  Bot Défense + Roulette – Discord (Render Web Service)
# =========================

# --- Réglages pour Render/Matplotlib (headless) ---
import os
os.environ.setdefault("MPLBACKEND", "Agg")

# --- Imports standard ---
import io
import threading
import random
import asyncio
from dataclasses import dataclass
from typing import Optional, Dict, List
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# --- Discord, Flask, Matplotlib, dotenv ---
import discord
from discord import app_commands
from discord.ext import commands
from flask import Flask
import matplotlib.pyplot as plt
from dotenv import load_dotenv

# =========================
#  Mini serveur HTTP pour Render (occupe $PORT)
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
#  Config générale
# =========================
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise SystemExit("DISCORD_TOKEN manquant dans les variables d'environnement")

CHANNEL_ID = int(os.getenv("DEF_CHANNEL_ID", "1327548733398843413"))  # canal pour les stats défense
LOCAL_TZ = os.getenv("LOCAL_TZ", "Europe/Paris")

# Intents (préfixe "!" -> message_content True)
intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.reactions = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# =========================
#  Config visuelle Roulette
# =========================
SPIN_GIF_URL = os.getenv(
    "SPIN_GIF_URL",
    "https://media.tenor.com/e3QG3W1u3lAAAAAC/roulette-casino.gif"
)
THUMB_URL = os.getenv("THUMB_URL", "")  # optionnel: logo

# Ping du croupier
CROUPIER_ROLE_ID = int(os.getenv("CROUPIER_ROLE_ID", "0")) or None
CROUPIER_ROLE_NAME = os.getenv("CROUPIER_ROLE_NAME", "CROUPIER")

# Couleurs
COLOR_RED   = 0xE74C3C
COLOR_BLACK = 0x2C3E50
COLOR_GREEN = 0x2ECC71
COLOR_GOLD  = 0xF1C40F

# Numéros rouges roulette (européenne)
RED_NUMBERS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}

# =========================
#  Roulette – Modèle et utilitaires
# =========================
@dataclass
class RouletteGame:
    channel_id: int
    starter_id: int
    bet: int = 0
    joiner_id: Optional[int] = None
    duel_type: Optional[str] = None           # "couleur" | "parité" | "intervalle"
    choice_joiner: Optional[str] = None       # camp choisi par le joiner
    lobby_msg_id: Optional[int] = None
    spin_msg_id: Optional[int] = None
    lobby_task: Optional[asyncio.Task] = None

# Boutons selon duel
DUEL_LABELS: Dict[str, List[tuple[str, str]]] = {
    "couleur":    [("🔴 Rouge", "rouge"), ("⚫ Noir", "noir")],
    "parité":     [("🟦 Pair", "pair"), ("🟪 Impair", "impair")],
    "intervalle": [("⬇️ 1–18", "1-18"), ("⬆️ 19–36", "19-36")],
}

def duel_human_name(mode: str) -> str:
    return {
        "couleur":    "Couleur (Rouge/Noir)",
        "parité":     "Pair/Impair",
        "intervalle": "1–18 / 19–36",
    }.get(mode, mode or "?")

def spin_wheel():
    n = random.randint(0, 36)
    if n == 0:
        return n, "vert"
    return n, ("rouge" if n in RED_NUMBERS else "noir")

def color_for_embed(color: str) -> int:
    return COLOR_GREEN if color == "vert" else (COLOR_RED if color == "rouge" else COLOR_BLACK)

def result_label(mode: str, n: int) -> Optional[str]:
    """Retourne l'étiquette gagnante selon le mode (ou None si neutre)."""
    if mode == "couleur":
        if n == 0:
            return None
        return "rouge" if n in RED_NUMBERS else "noir"
    if mode == "parité":
        # 0 est pair ici -> avantage parité, mais ça reste fun-mode
        return "pair" if n % 2 == 0 else "impair"
    if mode == "intervalle":
        if 1 <= n <= 18:
            return "1-18"
        if 19 <= n <= 36:
            return "19-36"
        return None
    return None

active_games: Dict[int, List[RouletteGame]] = {}

# =========================
#  Roulette – Vues (UI)
# =========================
class DuelSelectionView(discord.ui.View):
    """Le créateur choisit le type de duel via 3 boutons."""
    def __init__(self, game: RouletteGame, *, timeout: float = 300.0):
        super().__init__(timeout=timeout)
        self.game = game

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.game.starter_id:
            await interaction.response.send_message("⛔ Seul le créateur peut choisir le type de duel.", ephemeral=True)
            return False
        return True

    async def on_button(self, interaction: discord.Interaction, duel_type: str):
        # Fixe le duel et désactive les boutons
        self.game.duel_type = duel_type
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

        labels = " / ".join(lbl for lbl, _ in DUEL_LABELS.get(duel_type, []))
        embed = discord.Embed(
            title="🎲 Roulette – Lobby ouvert",
            description=f"""Créateur : <@{self.game.starter_id}>
🎮 Duel : **{duel_human_name(duel_type)}** ({labels})
💵 Mise : **{self.game.bet}** kamas

➡️ Un joueur a **5 minutes** pour rejoindre ici avec **/roulette**.""",
            color=COLOR_GOLD
        )
        if THUMB_URL:
            embed.set_thumbnail(url=THUMB_URL)

        await interaction.response.edit_message(embed=embed, view=self)

        # Timeout de lobby (5 min pour qu'un joueur rejoigne)
        channel = interaction.channel

        async def lobby_timeout():
            await asyncio.sleep(300)
            if self.game.joiner_id is None:
                await channel.send(f"⏳ Lobby expiré (créé par <@{self.game.starter_id}>).")
                try:
                    active_games[self.game.channel_id].remove(self.game)
                    if not active_games[self.game.channel_id]:
                        active_games.pop(self.game.channel_id, None)
                except Exception:
                    pass

        self.game.lobby_task = bot.loop.create_task(lobby_timeout())

    @discord.ui.button(label="Couleur (Rouge/Noir)", style=discord.ButtonStyle.primary, row=0)
    async def _b_couleur(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.on_button(interaction, "couleur")

    @discord.ui.button(label="Pair / Impair", style=discord.ButtonStyle.secondary, row=0)
    async def _b_parite(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.on_button(interaction, "parité")

    @discord.ui.button(label="1–18 / 19–36", style=discord.ButtonStyle.success, row=0)
    async def _b_intervalle(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.on_button(interaction, "intervalle")

class SideChoiceView(discord.ui.View):
    """Le 2e joueur choisit son camp selon le duel choisi par le créateur."""
    def __init__(self, game: RouletteGame, *, timeout: float = 120.0):
        super().__init__(timeout=timeout)
        self.game = game
        labels = DUEL_LABELS.get(game.duel_type or "", [])
        if len(labels) != 2:
            labels = [("Option A","A"), ("Option B","B")]
        # bouton 1
        b1 = discord.ui.Button(label=labels[0][0], style=discord.ButtonStyle.primary)
        async def cb1(inter: discord.Interaction):
            await self._resolve(inter, labels[0][1])
        b1.callback = cb1
        self.add_item(b1)
        # bouton 2
        b2 = discord.ui.Button(label=labels[1][0], style=discord.ButtonStyle.secondary)
        async def cb2(inter: discord.Interaction):
            await self._resolve(inter, labels[1][1])
        b2.callback = cb2
        self.add_item(b2)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.game.joiner_id:
            await interaction.response.send_message("⛔ Seul le second joueur peut choisir.", ephemeral=True)
            return False
        return True

    async def _resolve(self, interaction: discord.Interaction, choice_joiner: str):
        self.game.choice_joiner = choice_joiner

        # Déterminer le camp du créateur (opposé)
        starter_choice = {
            ("couleur","rouge"): "noir",
            ("couleur","noir"): "rouge",
            ("parité","pair"): "impair",
            ("parité","impair"): "pair",
            ("intervalle","1-18"): "19-36",
            ("intervalle","19-36"): "1-18",
        }.get((self.game.duel_type, choice_joiner), "?")

        # Ping CROUPIER pour valider les mises
        mention = f"<@&{CROUPIER_ROLE_ID}>" if CROUPIER_ROLE_ID else f"**{CROUPIER_ROLE_NAME}**"

        desc = f"""\
{mention} — merci de **valider les mises**.

🎮 Duel : **{duel_human_name(self.game.duel_type)}**
👥 <@{self.game.starter_id}> → **{starter_choice}**  vs  <@{self.game.joiner_id}> → **{self.game.choice_joiner}**
💵 Mise : **{self.game.bet}** kamas (par joueur)
"""

        embed = discord.Embed(title="🎩 Appel CROUPIER", description=desc, color=COLOR_GOLD)
        if THUMB_URL:
            embed.set_thumbnail(url=THUMB_URL)

        await interaction.response.edit_message(embed=embed, view=CroupierView(self.game))

class CroupierView(discord.ui.View):
    """Validation des mises par le rôle CROUPIER, puis lancement du spin."""
    def __init__(self, game: RouletteGame, *, timeout: float = 300.0):
        super().__init__(timeout=timeout)
        self.game = game

    async def _is_croupier(self, interaction: discord.Interaction) -> bool:
        member: discord.Member = interaction.user  # type: ignore
        if CROUPIER_ROLE_ID and any(r.id == CROUPIER_ROLE_ID for r in member.roles):
            return True
        if any(r.name.upper() == CROUPIER_ROLE_NAME.upper() for r in member.roles):
            return True
        await interaction.response.send_message("⛔ Réservé au rôle **CROUPIER**.", ephemeral=True)
        return False

    @discord.ui.button(label="✅ Mises récupérées", style=discord.ButtonStyle.success, emoji="💰")
    async def btn_valider(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._is_croupier(interaction):
            return
        await launch_spin(interaction, self.game)

    @discord.ui.button(label="❌ Annuler", style=discord.ButtonStyle.danger)
    async def btn_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._is_croupier(interaction):
            return
        try:
            active_games[self.game.channel_id].remove(self.game)
            if not active_games[self.game.channel_id]:
                active_games.pop(self.game.channel_id, None)
        except Exception:
            pass
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="🛑 Partie annulée par le CROUPIER",
                description=f"Créateur : <@{self.game.starter_id}> — Mise : {self.game.bet} kamas",
                color=COLOR_RED,
            ),
            view=None
        )

async def launch_spin(interaction: discord.Interaction, game: RouletteGame):
    base = (
        f"🎮 Duel : **{duel_human_name(game.duel_type)}**\n"
        f"👥 <@{game.starter_id}> vs <@{game.joiner_id}>\n"
        f"💵 Mise : **{game.bet}** kamas\n"
    )
    spin = discord.Embed(title="🎰 SPIN EN COURS !", description=base + "⌛ La roue tourne... **5**", color=COLOR_GOLD)
    if THUMB_URL: spin.set_thumbnail(url=THUMB_URL)
    if SPIN_GIF_URL: spin.set_image(url=SPIN_GIF_URL)

    await interaction.response.edit_message(embed=spin, view=None)
    msg = await interaction.original_response()
    game.spin_msg_id = msg.id
    channel = interaction.channel

    for t in [4,3,2,1]:
        await asyncio.sleep(1)
        try:
            m = await channel.fetch_message(game.spin_msg_id)
            spin.description = base + f"⌛ La roue tourne... **{t}**"
            await m.edit(embed=spin)
        except:
            break
    await asyncio.sleep(1)

    # Tire jusqu'à 3 fois pour éviter 0 en "couleur" (sinon neutre)
    attempts = 0
    while True:
        attempts += 1
        n, col = spin_wheel()
        res = result_label(game.duel_type, n)
        if res is not None or attempts >= 3:
            break

    # Déduit le camp du créateur (opposé du choix du joiner)
    starter_choice = {
        ("couleur","rouge"): "noir",
        ("couleur","noir"): "rouge",
        ("parité","pair"): "impair",
        ("parité","impair"): "pair",
        ("intervalle","1-18"): "19-36",
        ("intervalle","19-36"): "1-18",
    }.get((game.duel_type, game.choice_joiner or ""), "?")

    if res == starter_choice:
        winner, loser = game.starter_id, game.joiner_id
    elif res == (game.choice_joiner or ""):
        winner, loser = game.joiner_id, game.starter_id
    else:
        winner = loser = None

    color_for_title = col if game.duel_type == "couleur" else ("vert" if n == 0 else ("rouge" if n in RED_NUMBERS else "noir"))
    color_emoji = "🔴" if color_for_title == "rouge" else ("⚫" if color_for_title == "noir" else "🟢" if n == 0 else "")
    title = f"🏁 Résultat : {n} {color_emoji}"

    if winner:
        desc = (
            f"🎮 Duel : **{duel_human_name(game.duel_type)}**\n"
            f"🏆 Gagnant : <@{winner}>  (+{game.bet} kamas)\n"
            f"💤 Perdant : <@{loser}>   (-{game.bet} kamas)"
        )
        color = color_for_embed(color_for_title)
    else:
        desc = (
            f"🎮 Duel : **{duel_human_name(game.duel_type)}**\n"
            f"⚖️ Aucun gagnant (résultat neutre)."
        )
        color = COLOR_GOLD

    result = discord.Embed(title=title, description=desc, color=color)
    if THUMB_URL: result.set_thumbnail(url=THUMB_URL)
    try:
        m = await channel.fetch_message(game.spin_msg_id)
        await m.edit(embed=result, view=None)
    except:
        await channel.send(embed=result)

    try:
        active_games[game.channel_id].remove(game)
        if not active_games[game.channel_id]:
            active_games.pop(game.channel_id, None)
    except Exception:
        pass

# =========================
#  Slash command /roulette (duel via boutons)
# =========================
@bot.tree.command(name="roulette", description="Créer/Rejoindre une roulette (mise en kamas)")
@app_commands.describe(mise="Montant à miser (créateur uniquement)")
async def roulette_cmd(interaction: discord.Interaction, mise: Optional[int] = None):
    channel_id = interaction.channel_id
    user_id = interaction.user.id

    # 1) Rejoindre un lobby prêt (duel déjà choisi)
    open_ready = [g for g in active_games.get(channel_id, []) if g.joiner_id is None and g.duel_type is not None and g.starter_id != user_id]
    if open_ready:
        game = open_ready[0]
        game.joiner_id = user_id
        # annuler le timeout lobby si existant
        if game.lobby_task and not game.lobby_task.done():
            game.lobby_task.cancel()
        labels = " / ".join(lbl for lbl, _ in DUEL_LABELS.get(game.duel_type, []))
        embed = discord.Embed(
            title="👥 Joueur rejoint !",
            description=(
                f"🎮 Duel : **{duel_human_name(game.duel_type)}** ({labels})\n"
                f"💵 Mise : **{game.bet}** kamas\n\n"
                f"<@{user_id}>, choisis ton camp :"
            ),
            color=COLOR_GOLD
        )
        if THUMB_URL: embed.set_thumbnail(url=THUMB_URL)
        await interaction.response.send_message(embed=embed, view=SideChoiceView(game))
        sent = await interaction.original_response()
        game.lobby_msg_id = sent.id
        return

    # 2) Un lobby existe mais le duel n'est pas encore choisi (attendre)
    open_unset = [g for g in active_games.get(channel_id, []) if g.joiner_id is None and g.duel_type is None and g.starter_id != user_id]
    if open_unset:
        return await interaction.response.send_message("⏳ Le créateur est en train de choisir le **type de duel**… Réessaie dans quelques secondes.", ephemeral=True)

    # 3) Créer un lobby (créateur)
    if mise is None or mise <= 0:
        return await interaction.response.send_message("Indique une **mise positive** pour créer la partie (ex: /roulette mise:100).", ephemeral=True)

    game = RouletteGame(channel_id=channel_id, starter_id=user_id, bet=mise, duel_type=None)
    active_games.setdefault(channel_id, []).append(game)

    embed = discord.Embed(
        title="🎲 Roulette – Choisis le type de duel",
        description=f"""Créateur : <@{user_id}>
💵 Mise : **{mise}** kamas par joueur

Choisis ci-dessous : **Couleur**, **Pair/Impair**, ou **1–18 / 19–36**.
(Tu as 5 min pour choisir, sinon la partie s'annule)""",
        color=COLOR_GOLD
    )
    if THUMB_URL: embed.set_thumbnail(url=THUMB_URL)

    view = DuelSelectionView(game)
    await interaction.response.send_message(embed=embed, view=view)
    sent = await interaction.original_response()
    game.lobby_msg_id = sent.id

    # Timeout si le créateur ne choisit pas de duel dans les 5 min
    async def duel_timeout():
        await asyncio.sleep(300)
        if game.duel_type is None and game.joiner_id is None:
            channel = interaction.channel
            await channel.send(f"⏳ Temps écoulé — duel non choisi par <@{user_id}>. Partie annulée.")
            try:
                active_games[channel_id].remove(game)
                if not active_games[channel_id]:
                    active_games.pop(channel_id, None)
            except Exception:
                pass

    bot.loop.create_task(duel_timeout())

# =========================
#  Fonctions Défense (tes anciennes commandes)
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

            for member in message.mentions:
                if not member.bot and member.id not in utilisateurs_comptes:
                    utilisateurs_comptes.add(member.id)
                    thumbsup_stats[member.id]["count"] += 1
                    thumbsup_stats[member.id]["name"] = member.display_name

            for alliance in alliances:
                if alliance.lower() in content_lower:
                    attaque_par_alliance[alliance] += 1
                for embed in message.embeds:
                    if embed.description and alliance.lower() in (embed.description or "").lower():
                        attaque_par_alliance[alliance] += 1
                    if embed.title and alliance.lower() in (embed.title or "").lower():
                        attaque_par_alliance[alliance] += 1

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

    if thumbsup_stats:
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

    tranches = [f"{h:02d}h-{(h+2)%24:02d}h" for h in range(0, 24, 2)]
    compteur = [0] * 12

    for heure in attaques:
        index = heure // 2
        compteur[index] += 1

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

    entries: List[tuple[datetime, str, str]] = []

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
    messages = []
    async for message in channel.history(limit=5000):
        if message.author == bot.user and message.embeds:
            messages.append(message)
        if len(messages) >= 10:
            break
    messages = sorted(messages, key=lambda m: m.created_at)

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

    victories_pct = [v / t * 100 for v, t in zip(victories, totals)]
    defeats_pct = [d / t * 100 for d, t in zip(defeats, totals)]
    incompletes_pct = [i / t * 100 for i, t in zip(incompletes, totals)]

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
#  Démarrage / Sync slash
# =========================
@bot.event
async def on_ready():
    try:
        await bot.tree.sync()
    except Exception as e:
        print("Sync error:", e)
    print(f"Connecté en tant que {bot.user} (ID: {bot.user.id})")

if __name__ == "__main__":
    bot.run(TOKEN)
