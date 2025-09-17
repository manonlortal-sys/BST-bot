# =========================
#  Roulette à 2 joueurs – Discord (Render Web Service)
# =========================

import os
os.environ.setdefault("MPLBACKEND", "Agg")

import asyncio
import random
import threading
from dataclasses import dataclass
from typing import Optional, Dict, List

import discord
from discord import app_commands
from discord.ext import commands
from flask import Flask
from dotenv import load_dotenv

# ---------- Mini serveur HTTP pour Render ----------
app = Flask(__name__)

@app.route("/")
def home():
    return "Roulette bot actif"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_flask, daemon=True).start()

# ---------- Config ----------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise SystemExit("DISCORD_TOKEN manquant")

SPIN_GIF_URL = os.getenv("SPIN_GIF_URL", "https://media.tenor.com/e3QG3W1u3lAAAAAC/roulette-casino.gif")
THUMB_URL    = os.getenv("THUMB_URL", "")

CROUPIER_ROLE_ID   = int(os.getenv("CROUPIER_ROLE_ID", "0")) or None
CROUPIER_ROLE_NAME = os.getenv("CROUPIER_ROLE_NAME", "CROUPIER")

COLOR_RED   = 0xE74C3C
COLOR_BLACK = 0x2C3E50
COLOR_GREEN = 0x2ECC71
COLOR_GOLD  = 0xF1C40F

RED_NUMBERS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}

intents = discord.Intents.default()
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- Modèle & utils ----------
@dataclass
class RouletteGame:
    channel_id: int
    starter_id: int
    bet: int = 0
    duel_type: Optional[str] = None           # "couleur" | "parité" | "intervalle"
    starter_choice: Optional[str] = None      # camp choisi par le créateur
    joiner_id: Optional[int] = None
    choice_joiner: Optional[str] = None       # camp auto (opposé)
    lobby_msg_id: Optional[int] = None
    spin_msg_id: Optional[int] = None
    lobby_task: Optional[asyncio.Task] = None
    # Animation d'attente
    wait_msg_id: Optional[int] = None
    wait_anim_task: Optional[asyncio.Task] = None

# Boutons pour le duel (labels visibles, valeur logique)
DUEL_LABELS: Dict[str, List[tuple[str, str]]] = {
    "couleur":    [("🔴 Rouge", "rouge"), ("⚫ Noir", "noir")],
    "parité":     [("🟦 Pair", "pair"), ("🟪 Impair", "impair")],
    "intervalle": [("⬇️ 1-18", "1-18"), ("⬆️ 19-36", "19-36")],
}

def duel_human_name(mode: str) -> str:
    # Libellés “humains” en minuscules
    return {
        "couleur":    "rouge/noir",
        "parité":     "pair/impair",
        "intervalle": "1-18/19-36",
    }.get(mode, mode or "?")

def spin_wheel():
    n = random.randint(0, 36)
    if n == 0:
        return n, "vert"
    return n, ("rouge" if n in RED_NUMBERS else "noir")

def color_for_embed(color: str) -> int:
    return COLOR_GREEN if color == "vert" else (COLOR_RED if color == "rouge" else COLOR_BLACK)

def result_label(mode: str, n: int) -> Optional[str]:
    if mode == "couleur":
        if n == 0:
            return None
        return "rouge" if n in RED_NUMBERS else "noir"
    if mode == "parité":
        return "pair" if n % 2 == 0 else "impair"  # fun: 0 = pair
    if mode == "intervalle":
        if 1 <= n <= 18:
            return "1-18"
        if 19 <= n <= 36:
            return "19-36"
        return None
    return None

def opposite_choice(mode: str, choice: str) -> str:
    mapping = {
        ("couleur", "rouge"): "noir",
        ("couleur", "noir"): "rouge",
        ("parité", "pair"): "impair",
        ("parité", "impair"): "pair",
        ("intervalle", "1-18"): "19-36",
        ("intervalle", "19-36"): "1-18",
    }
    return mapping.get((mode, choice), "?")

active_games: Dict[int, List[RouletteGame]] = {}

# ---------- Vues (UI) ----------
class DuelSelectionView(discord.ui.View):
    """Étape 1: le créateur choisit le type de duel (3 boutons)."""
    def __init__(self, game: RouletteGame, *, timeout: float = 300.0):
        super().__init__(timeout=timeout)
        self.game = game

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.game.starter_id:
            await interaction.response.send_message("⛔ Seul le créateur peut choisir le type de duel.", ephemeral=True)
            return False
        return True

    async def on_button(self, interaction: discord.Interaction, duel_type: str):
        self.game.duel_type = duel_type
        # Étape 2: choix du camp par le créateur
        labels = " / ".join(lbl for lbl, _ in DUEL_LABELS.get(duel_type, []))
        embed = discord.Embed(
            title="🎲 Roulette – Choix du camp",
            description=(
                f"Créateur : <@{self.game.starter_id}>\n"
                f"🎮 Duel : **{duel_human_name(duel_type)}** ({labels})\n"
                f"💵 Mise : **{self.game.bet}** kamas\n\n"
                "➡️ Choisis ton **camp** ci-dessous."
            ),
            color=COLOR_GOLD
        )
        if THUMB_URL:
            embed.set_thumbnail(url=THUMB_URL)
        await interaction.response.edit_message(embed=embed, view=CampSelectionView(self.game))

    @discord.ui.button(label="🔴⚫ rouge/noir", style=discord.ButtonStyle.primary, row=0)
    async def _b_couleur(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.on_button(interaction, "couleur")

    @discord.ui.button(label="🟦🟪 pair/impair", style=discord.ButtonStyle.secondary, row=0)
    async def _b_parite(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.on_button(interaction, "parité")

    @discord.ui.button(label="⬇️⬆️ 1-18/19-36", style=discord.ButtonStyle.success, row=0)
    async def _b_intervalle(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.on_button(interaction, "intervalle")

class CampSelectionView(discord.ui.View):
    """Étape 2: le créateur choisit son camp (2 boutons selon le duel)."""
    def __init__(self, game: RouletteGame, *, timeout: float = 300.0):
        super().__init__(timeout=timeout)
        self.game = game
        labels = DUEL_LABELS.get(game.duel_type or "", [])
        if len(labels) != 2:
            labels = [("Option A", "A"), ("Option B", "B")]

        b1 = discord.ui.Button(label=labels[0][0], style=discord.ButtonStyle.primary)
        async def cb1(inter: discord.Interaction):
            await self._resolve(inter, labels[0][1])
        b1.callback = cb1
        self.add_item(b1)

        b2 = discord.ui.Button(label=labels[1][0], style=discord.ButtonStyle.secondary)
        async def cb2(inter: discord.Interaction):
            await self._resolve(inter, labels[1][1])
        b2.callback = cb2
        self.add_item(b2)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.game.starter_id:
            await interaction.response.send_message("⛔ Seul le créateur peut choisir son camp.", ephemeral=True)
            return False
        return True

    async def _resolve(self, interaction: discord.Interaction, starter_choice: str):
        self.game.starter_choice = starter_choice
        opp = opposite_choice(self.game.duel_type or "", starter_choice)

        # --- Embed d'attente + animation aller-retour des points ---
        base_desc = (
            f"👤 Créateur : <@{self.game.starter_id}>\n"
            f"🎮 Duel : **{duel_human_name(self.game.duel_type or '')}**\n"
            f"🧭 Camp créateur : **{starter_choice}** (l'autre joueur sera **{opp}**)\n"
            f"💵 Mise : **{self.game.bet}** kamas\n\n"
            "🕐 En attente d'un second joueur"
        )
        embed = discord.Embed(title="🎲 Lobby ouvert", description=base_desc + "...", color=COLOR_GOLD)
        if THUMB_URL:
            embed.set_thumbnail(url=THUMB_URL)

        await interaction.response.edit_message(embed=embed, view=None)
        msg = interaction.message  # le message qu'on vient d'éditer
        self.game.lobby_msg_id = msg.id
        self.game.wait_msg_id = msg.id

        async def animate_wait():
            sequence = ["", ".", "..", "...", "..", "."]
            idx = 0
            try:
                while self.game.joiner_id is None:
                    trail = sequence[idx]
                    idx = (idx + 1) % len(sequence)
                    embed.description = (
                        f"👤 Créateur : <@{self.game.starter_id}>\n"
                        f"🎮 Duel : **{duel_human_name(self.game.duel_type or '')}**\n"
                        f"🧭 Camp créateur : **{starter_choice}** (l'autre joueur sera **{opp}**)\n"
                        f"💵 Mise : **{self.game.bet}** kamas\n\n"
                        f"🕐 En attente d'un second joueur{trail}"
                    )
                    await msg.edit(embed=embed)
                    await asyncio.sleep(1.2)
            except asyncio.CancelledError:
                pass

        self.game.wait_anim_task = bot.loop.create_task(animate_wait())

        # Timeout lobby (5 min)
        channel = interaction.channel
        async def lobby_timeout():
            await asyncio.sleep(300)
            if self.game.joiner_id is None:
                if self.game.wait_anim_task and not self.game.wait_anim_task.done():
                    self.game.wait_anim_task.cancel()
                await channel.send(f"⏳ Lobby expiré (créé par <@{self.game.starter_id}>).")
                try:
                    active_games[self.game.channel_id].remove(self.game)
                    if not active_games[self.game.channel_id]:
                        active_games.pop(self.game.channel_id, None)
                except Exception:
                    pass

        self.game.lobby_task = bot.loop.create_task(lobby_timeout())

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

# ---------- Spin ----------
async def launch_spin(interaction: discord.Interaction, game: RouletteGame):
    # Stop animation si elle tourne encore
    if game.wait_anim_task and not game.wait_anim_task.done():
        game.wait_anim_task.cancel()

    base = (
        f"🎮 Duel : **{duel_human_name(game.duel_type or '')}**\n"
        f"👥 <@{game.starter_id}> ({game.starter_choice}) vs <@{game.joiner_id}> ({game.choice_joiner})\n"
        f"💵 Mise : **{game.bet}** kamas\n"
    )
    spin = discord.Embed(title="🎰 SPIN EN COURS !", description=base + "⌛ La roue tourne... **5**", color=COLOR_GOLD)
    if THUMB_URL: spin.set_thumbnail(url=THUMB_URL)
    if SPIN_GIF_URL: spin.set_image(url=SPIN_GIF_URL)

    await interaction.response.edit_message(embed=spin, view=None)
    msg = interaction.message
    game.spin_msg_id = msg.id
    channel = interaction.channel

    for t in [4,3,2,1]:
        await asyncio.sleep(1)
        try:
            spin.description = base + f"⌛ La roue tourne... **{t}**"
            await msg.edit(embed=spin)
        except:
            break
    await asyncio.sleep(1)

    # Tente d'éviter 0 pour "couleur" en 3 essais max (sinon neutre)
    attempts = 0
    while True:
        attempts += 1
        n, col = spin_wheel()
        res = result_label(game.duel_type or "", n)
        if res is not None or attempts >= 3:
            break

    # Décide du gagnant selon le camp choisi par le créateur
    if res == (game.starter_choice or ""):
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
            f"🎮 Duel : **{duel_human_name(game.duel_type or '')}**\n"
            f"🏆 Gagnant : <@{winner}>  (+{game.bet} kamas)\n"
            f"💤 Perdant : <@{loser}>   (-{game.bet} kamas)"
        )
        color = color_for_embed(color_for_title)
    else:
        desc = (
            f"🎮 Duel : **{duel_human_name(game.duel_type or '')}**\n"
            f"⚖️ Aucun gagnant (résultat neutre)."
        )
        color = COLOR_GOLD

    result = discord.Embed(title=title, description=desc, color=color)
    if THUMB_URL: result.set_thumbnail(url=THUMB_URL)
    try:
        await msg.edit(embed=result, view=None)
    except:
        await channel.send(embed=result)

    try:
        active_games[game.channel_id].remove(game)
        if not active_games[game.channel_id]:
            active_games.pop(game.channel_id, None)
    except Exception:
        pass

# ---------- Slash /roulette ----------
@bot.tree.command(name="roulette", description="Créer/Rejoindre une roulette (mise en kamas)")
@app_commands.describe(mise="Montant à miser (créateur uniquement)")
async def roulette_cmd(interaction: discord.Interaction, mise: Optional[int] = None):
    # Ack immédiat pour éviter 10062
    await interaction.response.defer(thinking=False)

    channel_id = interaction.channel_id
    user_id = interaction.user.id

    # 1) Rejoindre un lobby prêt (duel & camp du créateur déjà choisis)
    open_ready = [
        g for g in active_games.get(channel_id, [])
        if g.joiner_id is None and g.duel_type is not None and g.starter_choice is not None and g.starter_id != user_id
    ]
    if open_ready:
        game = open_ready[0]
        game.joiner_id = user_id
        game.choice_joiner = opposite_choice(game.duel_type or "", game.starter_choice or "")
        # stop anim & timeout
        if game.wait_anim_task and not game.wait_anim_task.done():
            game.wait_anim_task.cancel()
        if game.lobby_task and not game.lobby_task.done():
            game.lobby_task.cancel()
        # “geler” le message d’attente en “Joueur rejoint”
        try:
            ch = interaction.channel
            if game.wait_msg_id:
                m = await ch.fetch_message(game.wait_msg_id)
                frozen = discord.Embed(
                    title="👥 Joueur rejoint",
                    description=(
                        f"🎮 Duel : **{duel_human_name(game.duel_type or '')}**\n"
                        f"👤 Créateur : <@{game.starter_id}> ({game.starter_choice})\n"
                        f"🧑‍🤝‍🧑 Adversaire : <@{user_id}> ({game.choice_joiner})\n"
                        f"💵 Mise : **{game.bet}** kamas"
                    ),
                    color=COLOR_GOLD
                )
                if THUMB_URL:
                    frozen.set_thumbnail(url=THUMB_URL)
                await m.edit(embed=frozen, view=None)
        except Exception:
            pass

        mention = f"<@&{CROUPIER_ROLE_ID}>" if CROUPIER_ROLE_ID else f"**{CROUPIER_ROLE_NAME}**"
        desc = (
            f"{mention} — merci de **valider les mises**.\n\n"
            f"🎮 Duel : **{duel_human_name(game.duel_type or '')}**\n"
            f"👥 <@{game.starter_id}> → **{game.starter_choice}**  vs  <@{game.joiner_id}> → **{game.choice_joiner}**\n"
            f"💵 Mise : **{game.bet}** kamas (par joueur)\n"
        )
        embed = discord.Embed(title="🎩 Appel CROUPIER", description=desc, color=COLOR_GOLD)
        if THUMB_URL:
            embed.set_thumbnail(url=THUMB_URL)

        await interaction.followup.send(embed=embed, view=CroupierView(game))
        return

    # 2) Un lobby existe mais le créateur n’a pas encore choisi duel/camp
    open_unset = [
        g for g in active_games.get(channel_id, [])
        if g.joiner_id is None and g.starter_id != user_id and (g.duel_type is None or g.starter_choice is None)
    ]
    if open_unset:
        return await interaction.followup.send("⏳ Le créateur configure la partie (duel/camp)… réessaie dans quelques instants.")

    # 3) Créer un lobby (créateur)
    if mise is None or mise <= 0:
        return await interaction.followup.send("Indique une **mise positive** pour créer la partie (ex: /roulette mise:100).")

    game = RouletteGame(channel_id=channel_id, starter_id=user_id, bet=mise)
    active_games.setdefault(channel_id, []).append(game)

    embed = discord.Embed(
        title="🎲 Roulette – Choisis le type de duel",
        description=(
            f"Créateur : <@{user_id}>\n"
            f"💵 Mise : **{mise}** kamas par joueur\n\n"
            "Choisis : **rouge/noir**, **pair/impair**, ou **1-18/19-36**.\n"
            "(Tu as 5 min pour choisir, sinon la partie s'annule)"
        ),
        color=COLOR_GOLD
    )
    if THUMB_URL:
        embed.set_thumbnail(url=THUMB_URL)

    sent = await interaction.followup.send(embed=embed, view=DuelSelectionView(game))
    game.lobby_msg_id = sent.id

    async def duel_timeout():
        await asyncio.sleep(300)
        if (game.duel_type is None or game.starter_choice is None) and game.joiner_id is None:
            channel = interaction.channel
            await channel.send(f"⏳ Temps écoulé — configuration incomplète par <@{user_id}>. Partie annulée.")
            try:
                active_games[channel_id].remove(game)
                if not active_games[channel_id]:
                    active_games.pop(channel_id, None)
            except Exception:
                pass

    bot.loop.create_task(duel_timeout())

# ---------- Démarrage ----------
@bot.event
async def on_ready():
    try:
        await bot.tree.sync()
    except Exception as e:
        print("Sync error:", e)
    print(f"Connecté en tant que {bot.user} (ID: {bot.user.id})")

if __name__ == "__main__":
    bot.run(TOKEN)
