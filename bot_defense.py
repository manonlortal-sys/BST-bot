# bot_roulette.py
# Bot Roulette – Discord
# - Slash /roulette pour lancer une partie
# - Créateur choisit le type de duel via boutons (Rouge/Noir, Pair/Impair, 1-18/19-36)
# - Créateur choisit son camp
# - Un second joueur rejoint
# - Le bot ping le rôle CROUPIER pour valider les mises, le croupier clique "Valider"
# - Spin avec GIF (optionnel via SPIN_GIF_URL)
# - Commission croupier: 5% du pot (configurable)
# - Leaderboard "sticky" par serveur : posté une fois puis édité après chaque partie
#
# ENV à définir (Render / .env):
#   DISCORD_TOKEN=...
#   ROLE_CROUPIER_ID=123456789012345678
#   LEADERBOARD_CHANNEL_ID=123456789012345678
#   COMMISSION_PERCENT=5
#   SPIN_GIF_URL=https://...gif (optionnel)
#   PORT=10000  (Render)
#
# requirements.txt:
#   discord.py
#   Flask
#   aiosqlite

import os
import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Optional, Dict

import discord
from discord import app_commands
from discord.ext import commands
import aiosqlite

# --- Keep-alive (Render) ---
from flask import Flask
from threading import Thread

app = Flask(__name__)
@app.route("/")
def home():
    return "Roulette bot up"
def _run_flask():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
Thread(target=_run_flask, daemon=True).start()

# --- Config ---
TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
ROLE_CROUPIER_ID = int(os.getenv("ROLE_CROUPIER_ID", "0"))
LEADERBOARD_CHANNEL_ID = int(os.getenv("LEADERBOARD_CHANNEL_ID", "0"))
COMMISSION_PERCENT = int(os.getenv("COMMISSION_PERCENT", "5"))
SPIN_GIF_URL = os.getenv("SPIN_GIF_URL", "").strip()

DB_PATH = os.getenv("DB_PATH", "roulette.db")

INTENTS = discord.Intents.default()
INTENTS.guilds = True
INTENTS.messages = True
INTENTS.message_content = False  # on utilise des slash commands
bot = commands.Bot(command_prefix="!", intents=INTENTS)

RED_NUMBERS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}

# ========== Data ==========
@dataclass
class Game:
    guild_id: int
    channel_id: int
    starter_id: int
    stake: int
    duel_type: Optional[str] = None   # "couleur" | "pairimpair" | "manque_passe"
    starter_choice: Optional[str] = None  # "rouge"/"noir" | "pair"/"impair" | "1-18"/"19-36"
    joiner_id: Optional[int] = None
    message_id: Optional[int] = None
    state: str = "choosing_duel"  # choosing_duel -> choosing_side -> waiting_opponent -> awaiting_croupier -> spinning -> done
    croupier_validated: bool = False
    validation_message_id: Optional[int] = None

# active games by message id (main UI message)
ACTIVE_GAMES: Dict[int, Game] = {}
# lock for leaderboard update per guild
LB_LOCKS: Dict[int, asyncio.Lock] = {}

# ========== DB ==========
INIT_SQL = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS sticky_messages(
  guild_id INTEGER PRIMARY KEY,
  leaderboard_msg_id INTEGER,
  channel_id INTEGER
);

CREATE TABLE IF NOT EXISTS stats_players(
  guild_id INTEGER,
  user_id INTEGER,
  total_wager INTEGER DEFAULT 0,  -- total misé (tous duels)
  net INTEGER DEFAULT 0,          -- gains - pertes (commission exclue)
  wins INTEGER DEFAULT 0,
  losses INTEGER DEFAULT 0,
  biggest_win INTEGER DEFAULT 0,
  streak_win INTEGER DEFAULT 0,
  streak_loss INTEGER DEFAULT 0,
  PRIMARY KEY(guild_id, user_id)
);

-- Historique minimal par partie (utile si besoin d'auditer)
CREATE TABLE IF NOT EXISTS games(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  guild_id INTEGER,
  channel_id INTEGER,
  starter_id INTEGER,
  joiner_id INTEGER,
  stake INTEGER,
  duel_type TEXT,
  starter_choice TEXT,
  winner_id INTEGER,
  loser_id INTEGER,
  result_number INTEGER,
  result_color TEXT,
  commission INTEGER,
  ts INTEGER
);
"""

async def db_init():
    async with aiosqlite.connect(DB_PATH) as db:
        for stmt in INIT_SQL.strip().split(";"):
            s = stmt.strip()
            if s:
                await db.execute(s)
        await db.commit()

async def _get_lb_msg_id(guild_id: int) -> Optional[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT leaderboard_msg_id FROM sticky_messages WHERE guild_id=?", (guild_id,))
        row = await cur.fetchone()
        return row[0] if row and row[0] else None

async def _set_lb_msg_id(guild_id: int, channel_id: int, msg_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO sticky_messages(guild_id, leaderboard_msg_id, channel_id)
            VALUES(?,?,?)
            ON CONFLICT(guild_id) DO UPDATE SET leaderboard_msg_id=excluded.leaderboard_msg_id, channel_id=excluded.channel_id
        """, (guild_id, msg_id, channel_id))
        await db.commit()

async def record_game_and_update_stats(
    g: Game,
    winner_id: int,
    loser_id: int,
    result_number: int,
    result_color: str,
    commission: int
):
    pot = g.stake * 2
    net_gain_winner = pot - commission  # net reçu par gagnant
    # net gagné par rapport à sa mise = +stake (duel équitable), mais on enregistre le net global côté leaderboard comme (gain - perte).
    # Pour représenter les flux: gagnant + (pot - commission - stake) = stake - commission ; perdant -stake
    # MAIS on t'avait demandé: "leaderboard n'affiche pas la commission". Donc on crédite gagnant +stake et débite perdant -stake.
    # La commission n'apparaît pas chez les joueurs.

    async with aiosqlite.connect(DB_PATH) as db:
        ts = int(time.time())
        await db.execute("""
            INSERT INTO games(guild_id, channel_id, starter_id, joiner_id, stake, duel_type, starter_choice,
                              winner_id, loser_id, result_number, result_color, commission, ts)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (g.guild_id, g.channel_id, g.starter_id, g.joiner_id, g.stake, g.duel_type, g.starter_choice,
              winner_id, loser_id, result_number, result_color, commission, ts))

        # total_wager : chaque joueur a misé "stake"
        for uid in (g.starter_id, g.joiner_id):
            await db.execute("""
                INSERT INTO stats_players(guild_id, user_id, total_wager, net, wins, losses, biggest_win, streak_win, streak_loss)
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(guild_id, user_id) DO NOTHING
            """, (g.guild_id, uid, 0, 0, 0, 0, 0, 0, 0))
            await db.execute("UPDATE stats_players SET total_wager = total_wager + ? WHERE guild_id=? AND user_id=?", (g.stake, g.guild_id, uid))

        # net: gagnant +stake, perdant -stake (commission ignorée ici)
        await db.execute("UPDATE stats_players SET net = net + ?, wins = wins + 1 WHERE guild_id=? AND user_id=?", (g.stake, g.guild_id, winner_id))
        await db.execute("UPDATE stats_players SET net = net - ?, losses = losses + 1 WHERE guild_id=? AND user_id=?", (g.stake, g.guild_id, loser_id))

        # biggest_win
        await db.execute("""
            UPDATE stats_players
            SET biggest_win = CASE WHEN ? > biggest_win THEN ? ELSE biggest_win END
            WHERE guild_id=? AND user_id=?
        """, (g.stake, g.stake, g.guild_id, winner_id))

        # streaks
        # winner: streak_win +1, streak_loss=0 ; loser: streak_loss +1, streak_win=0
        await db.execute("""
            UPDATE stats_players
            SET streak_win = streak_win + 1, streak_loss = 0
            WHERE guild_id=? AND user_id=?
        """, (g.guild_id, winner_id))
        await db.execute("""
            UPDATE stats_players
            SET streak_loss = streak_loss + 1, streak_win = 0
            WHERE guild_id=? AND user_id=?
        """, (g.guild_id, loser_id))

        await db.commit()

async def build_leaderboard_embed(guild: discord.Guild) -> discord.Embed:
    # Tri par total_wager desc
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT user_id, total_wager, net, wins, losses, biggest_win
            FROM stats_players
            WHERE guild_id=?
            ORDER BY total_wager DESC, user_id ASC
            LIMIT 30
        """, (guild.id,))
        rows = await cur.fetchall()
        cur2 = await db.execute("""
            SELECT COALESCE(SUM(total_wager),0) FROM stats_players WHERE guild_id=?
        """, (guild.id,))
        total_all = (await cur2.fetchone())[0]

    em = discord.Embed(
        title="Leaderboard",
        description="Classement par **total misé** (commission non incluse dans le net).",
        color=discord.Color.gold()
    )
    if not rows:
        em.add_field(name="Aucun joueur", value="Pas de parties enregistrées.", inline=False)
    else:
        lines = []
        for i, (uid, wager, net, wins, losses, biggest) in enumerate(rows, start=1):
            member = guild.get_member(uid)
            name = member.display_name if member else f"<@{uid}>"
            sign = "▲" if net > 0 else ("▼" if net < 0 else "•")
            lines.append(f"**{i}.** {name} — misé **{wager}** — net **{net}** {sign} — W/L: {wins}/{losses} — maxi: {biggest}")
        em.add_field(name="Joueurs", value="\n".join(lines), inline=False)
    em.set_footer(text=f"Total misé (tous joueurs) : {total_all}")
    return em

async def ensure_leaderboard_message(guild: discord.Guild) -> Optional[discord.Message]:
    if LEADERBOARD_CHANNEL_ID == 0:
        return None
    ch = guild.get_channel(LEADERBOARD_CHANNEL_ID)
    if not isinstance(ch, (discord.TextChannel, discord.Thread, discord.ForumChannel, discord.VoiceChannel)) and not isinstance(ch, discord.abc.Messageable):
        return None
    msg_id = await _get_lb_msg_id(guild.id)
    if msg_id:
        try:
            msg = await ch.fetch_message(msg_id)
            return msg
        except discord.NotFound:
            pass
    # Create new
    em = await build_leaderboard_embed(guild)
    msg = await ch.send(embed=em)
    await _set_lb_msg_id(guild.id, ch.id, msg.id)
    return msg

async def update_leaderboard(guild: discord.Guild):
    if guild is None:
        return
    lock = LB_LOCKS.setdefault(guild.id, asyncio.Lock())
    async with lock:
        msg = await ensure_leaderboard_message(guild)
        if not msg:
            return
        em = await build_leaderboard_embed(guild)
        await msg.edit(embed=em)

# ========== Views ==========
class DuelSelectView(discord.ui.View):
    def __init__(self, game: Game):
        super().__init__(timeout=300)
        self.game = game

    async def _ensure_creator(self, inter: discord.Interaction) -> bool:
        if inter.user.id != self.game.starter_id:
            await inter.response.send_message("Seul le créateur peut choisir le duel.", ephemeral=True)
            return False
        return True

    async def _set(self, inter: discord.Interaction, duel: str):
        if not await self._ensure_creator(inter): return
        self.game.duel_type = duel
        self.game.state = "choosing_side"
        await inter.response.edit_message(embed=build_duel_embed(self.game), view=SideSelectView(self.game))

    @discord.ui.button(label="🔴⚫ Rouge/Noir", style=discord.ButtonStyle.danger)
    async def b_color(self, inter: discord.Interaction, _btn: discord.ui.Button):
        await self._set(inter, "couleur")

    @discord.ui.button(label="➖➕ Pair/Impair", style=discord.ButtonStyle.secondary)
    async def b_even(self, inter: discord.Interaction, _btn: discord.ui.Button):
        await self._set(inter, "pairimpair")

    @discord.ui.button(label="1–18 / 19–36", style=discord.ButtonStyle.primary)
    async def b_range(self, inter: discord.Interaction, _btn: discord.ui.Button):
        await self._set(inter, "manque_passe")

class SideSelectView(discord.ui.View):
    def __init__(self, game: Game):
        super().__init__(timeout=300)
        self.game = game

        # Boutons selon duel_type
        if game.duel_type == "couleur":
            self.add_item(discord.ui.Button(label="Je choisis 🔴 Rouge", style=discord.ButtonStyle.danger, custom_id="side_rouge"))
            self.add_item(discord.ui.Button(label="Je choisis ⚫ Noir", style=discord.ButtonStyle.secondary, custom_id="side_noir"))
        elif game.duel_type == "pairimpair":
            self.add_item(discord.ui.Button(label="Je choisis Pair", style=discord.ButtonStyle.primary, custom_id="side_pair"))
            self.add_item(discord.ui.Button(label="Je choisis Impair", style=discord.ButtonStyle.secondary, custom_id="side_impair"))
        else:
            self.add_item(discord.ui.Button(label="Je choisis 1–18", style=discord.ButtonStyle.primary, custom_id="side_1_18"))
            self.add_item(discord.ui.Button(label="Je choisis 19–36", style=discord.ButtonStyle.secondary, custom_id="side_19_36"))

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.user.id != self.game.starter_id:
            await inter.response.send_message("Seul le créateur peut choisir son camp.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        # clean si pas terminé
        pass

    @discord.ui.button(label="placeholder", style=discord.ButtonStyle.secondary, disabled=True)
    async def _placeholder(self, inter: discord.Interaction, _btn: discord.ui.Button):
        # jamais affiché; les vrais boutons sont ajoutés dynamiquement
        await inter.response.defer()

    async def on_click(self, inter: discord.Interaction, choice_code: str):
        mapping = {
            "side_rouge": "rouge",
            "side_noir": "noir",
            "side_pair": "pair",
            "side_impair": "impair",
            "side_1_18": "1-18",
            "side_19_36": "19-36",
        }
        self.game.starter_choice = mapping[choice_code]
        self.game.state = "waiting_opponent"
        # Afficher view de join
        await inter.response.edit_message(embed=build_wait_embed(self.game), view=JoinView(self.game))

    async def interaction_check_component(self, inter: discord.Interaction, component_id: str):
        # route les custom_id
        if component_id.startswith("side_"):
            await self.on_click(inter, component_id)
            return True
        return False

    async def callback(self, inter: discord.Interaction):
        # Not used
        await inter.response.defer()

    async def on_error(self, error: Exception, item: discord.ui.Item, inter: discord.Interaction):
        try:
            await inter.response.send_message("Erreur d’interface.", ephemeral=True)
        except:
            pass

    async def on_children_interaction(self, inter: discord.Interaction):
        # hack to capture dynamic buttons
        if isinstance(inter.data, dict) and "custom_id" in inter.data:
            await self.interaction_check_component(inter, inter.data["custom_id"])

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # override to route
        if isinstance(interaction.data, dict) and "custom_id" in interaction.data:
            return await super().interaction_check(interaction)
        return await super().interaction_check(interaction)

class JoinView(discord.ui.View):
    def __init__(self, game: Game):
        super().__init__(timeout=300)
        self.game = game
        self.add_item(discord.ui.Button(label="Rejoindre la partie", style=discord.ButtonStyle.success, custom_id="join_game"))

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.user.id == self.game.starter_id:
            await inter.response.send_message("Tu ne peux pas rejoindre ta propre partie.", ephemeral=True)
            return False
        if self.game.joiner_id:
            await inter.response.send_message("Un joueur a déjà rejoint.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="placeholder", style=discord.ButtonStyle.secondary, disabled=True)
    async def _placeholder(self, inter: discord.Interaction, _btn: discord.ui.Button):
        await inter.response.defer()

    async def on_children_interaction(self, inter: discord.Interaction):
        if isinstance(inter.data, dict) and inter.data.get("custom_id") == "join_game":
            self.game.joiner_id = inter.user.id
            self.game.state = "awaiting_croupier"
            # Ping croupier
            mention = f"<@&{ROLE_CROUPIER_ID}>" if ROLE_CROUPIER_ID else "@CROUPIER"
            await inter.response.edit_message(embed=build_croupier_embed(self.game), view=CroupierValidateView(self.game))
            try:
                await inter.channel.send(f"{mention} — merci de **valider les mises**.", allowed_mentions=discord.AllowedMentions(roles=True))
            except:
                pass

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await super().interaction_check(interaction)

class CroupierValidateView(discord.ui.View):
    def __init__(self, game: Game):
        super().__init__(timeout=600)
        self.game = game
        self.add_item(discord.ui.Button(label="✅ Valider les mises (CROUPIER)", style=discord.ButtonStyle.success, custom_id="croupier_ok"))
        self.add_item(discord.ui.Button(label="❌ Annuler", style=discord.ButtonStyle.danger, custom_id="cancel_game"))

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.data.get("custom_id") == "croupier_ok":
            # restreindre au rôle croupier si fourni
            if ROLE_CROUPIER_ID and discord.utils.get(inter.user.roles, id=ROLE_CROUPIER_ID) is None:
                await inter.response.send_message("Réservé au rôle CROUPIER.", ephemeral=True)
                return False
        return True

    async def on_children_interaction(self, inter: discord.Interaction):
        cid = inter.data.get("custom_id")
        if cid == "croupier_ok":
            if self.game.croupier_validated:
                await inter.response.send_message("Déjà validé.", ephemeral=True)
                return
            self.game.croupier_validated = True
            # désactiver boutons
            for c in self.children:
                c.disabled = True
            await inter.response.edit_message(embed=build_spinning_embed(self.game), view=self)
            await run_spin_and_settle(inter, self.game)
        elif cid == "cancel_game":
            self.game.state = "done"
            for c in self.children:
                c.disabled = True
            await inter.response.edit_message(embed=build_cancel_embed(self.game), view=self)

# ========== Embeds ==========
def build_start_embed(starter: discord.Member, stake: int) -> discord.Embed:
    em = discord.Embed(
        title="🎰 Roulette – Nouvelle partie",
        description=f"Créateur : {starter.mention}\nMise : **{stake}**",
        color=discord.Color.gold()
    )
    em.add_field(name="Étape 1", value="Choisis le **type de duel** :", inline=False)
    return em

def build_duel_embed(game: Game) -> discord.Embed:
    labels = {
        "couleur": "Rouge/Noir",
        "pairimpair": "Pair/Impair",
        "manque_passe": "1–18 / 19–36"
    }
    em = discord.Embed(
        title="🎯 Choix du duel",
        description=f"Type sélectionné : **{labels.get(game.duel_type,'?')}**\n"
                    f"Choisis maintenant **ton camp**.",
        color=discord.Color.blurple()
    )
    return em

def build_wait_embed(game: Game) -> discord.Embed:
    em = discord.Embed(
        title="⌛ En attente d’un second joueur",
        description="Un joueur doit cliquer **Rejoindre la partie**.",
        color=discord.Color.orange()
    )
    em.add_field(name="Duel", value=display_duel(game), inline=True)
    em.add_field(name="Créateur", value=f"<@{game.starter_id}>", inline=True)
    em.add_field(name="Mise", value=f"{game.stake}", inline=True)
    return em

def build_croupier_embed(game: Game) -> discord.Embed:
    em = discord.Embed(
        title="🎩 Validation Croupier requise",
        description="Le croupier doit **valider les mises** pour lancer la roulette.",
        color=discord.Color.green()
    )
    em.add_field(name="Duel", value=display_duel(game), inline=True)
    em.add_field(name="Joueur 1", value=f"<@{game.starter_id}>", inline=True)
    em.add_field(name="Joueur 2", value=f"<@{game.joiner_id}>", inline=True)
    em.add_field(name="Mise (chaque joueur)", value=f"{game.stake}", inline=True)
    em.add_field(name="Commission", value=f"{COMMISSION_PERCENT}% du pot", inline=True)
    return em

def build_spinning_embed(game: Game) -> discord.Embed:
    em = discord.Embed(
        title="🎡 La roulette tourne...",
        description="Bonne chance !",
        color=discord.Color.orange()
    )
    em.add_field(name="Duel", value=display_duel(game), inline=True)
    if SPIN_GIF_URL:
        em.set_image(url=SPIN_GIF_URL)
    return em

def build_result_embed(game: Game, n: int, color_word: str, winner_id: int, loser_id: int, commission: int) -> discord.Embed:
    em = discord.Embed(
        title=f"🎉 Résultat : {n} ({color_word})",
        description=f"Gagnant : <@{winner_id}>\nPerdant : <@{loser_id}>",
        color=discord.Color.green() if winner_id else discord.Color.red()
    )
    em.add_field(name="Duel", value=display_duel(game), inline=True)
    pot = game.stake * 2
    em.add_field(name="Pot", value=f"{pot}", inline=True)
    em.add_field(name="Commission croupier", value=f"{commission} ({COMMISSION_PERCENT}%)", inline=True)
    em.set_footer(text="Leaderboard mis à jour.")
    return em

def build_cancel_embed(game: Game) -> discord.Embed:
    return discord.Embed(
        title="🛑 Partie annulée",
        description="Le croupier a annulé la partie.",
        color=discord.Color.red()
    )

def display_duel(game: Game) -> str:
    if game.duel_type == "couleur":
        return f"Rouge/Noir — choix J1 : **{game.starter_choice}**"
    if game.duel_type == "pairimpair":
        return f"Pair/Impair — choix J1 : **{game.starter_choice}**"
    return f"1–18 / 19–36 — choix J1 : **{game.starter_choice}**"

# ========== Spin & rules ==========
def spin_number() -> int:
    return random.randint(0, 36)

def color_of(n: int) -> str:
    if n == 0: return "vert"
    return "rouge" if n in RED_NUMBERS else "noir"

def is_even(n: int) -> bool:
    return n % 2 == 0

def in_range_1_18(n: int) -> bool:
    return 1 <= n <= 18

async def run_spin_and_settle(inter: discord.Interaction, game: Game):
    game.state = "spinning"
    await asyncio.sleep(2.0)  # petit délai pour le "spin"
    n = spin_number()
    col = color_of(n)

    # Determine winner
    # starter_choice vs implicit other choice for joiner
    if game.duel_type == "couleur":
        starter_win = (game.starter_choice == col)
    elif game.duel_type == "pairimpair":
        if n == 0:
            starter_win = False
        else:
            starter_win = (game.starter_choice == ("pair" if is_even(n) else "impair"))
    else:
        if n == 0:
            starter_win = False
        else:
            starter_win = (game.starter_choice == ("1-18" if in_range_1_18(n) else "19-36"))

    if starter_win:
        winner_id, loser_id = game.starter_id, game.joiner_id
    else:
        winner_id, loser_id = game.joiner_id, game.starter_id

    pot = game.stake * 2
    commission = (pot * COMMISSION_PERCENT) // 100

    # Persist
    await record_game_and_update_stats(game, winner_id, loser_id, n, col, commission)

    # Show result
    em = build_result_embed(game, n, col, winner_id, loser_id, commission)
    await inter.edit_original_response(embed=em, view=None)

    # Leaderboard update
    guild = inter.guild
    await update_leaderboard(guild)

    # mark done
    game.state = "done"
    ACTIVE_GAMES.pop(game.message_id, None)

# ========== Slash command ==========
@bot.tree.command(name="roulette", description="Créer une partie de roulette (duel)")
@app_commands.describe(mise="Montant misé par joueur (kamas)")
async def roulette_cmd(inter: discord.Interaction, mise: app_commands.Range[int, 1, 1_000_000]):
    # réponse rapide pour éviter Unknown interaction
    await inter.response.send_message("🎰 Partie créée ! Regarde le message ci-dessous.", ephemeral=True)

    starter = inter.user
    g = Game(guild_id=inter.guild.id, channel_id=inter.channel.id, starter_id=starter.id, stake=mise)

    msg = await inter.channel.send(embed=build_start_embed(starter, mise), view=DuelSelectView(g))
    g.message_id = msg.id
    ACTIVE_GAMES[msg.id] = g

# ========== Bot lifecycle ==========
@bot.event
async def on_ready():
    await db_init()
    try:
        await bot.tree.sync()
    except Exception as e:
        print("Sync error:", e)
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN manquant")
    bot.run(TOKEN)
