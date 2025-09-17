# ==============================================
#  Bot Discord — Réécriture "rapide au démarrage"
#  - Sync par serveur (vite)
#  - Matplotlib en lazy-import (quand utilisé)
#  - Slots (1 jeton, animation emoji)
#  - Roulette 1v1 avec croupier, commission 5%
#  - Leaderboard serveur via SQLite (aiosqlite)
#  - !sync (admin) pour maj instant des slash commands
#  - Option Web (Flask) si ton service Render est Web
# ==============================================

import os
import asyncio
import threading
import secrets
import random
import time
from dataclasses import dataclass
from typing import Optional, Dict, List

import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

# ---------- Option Web (Render Web Service) ----------
WEB_MODE = os.getenv("WEB_MODE", "off").lower() in {"1","true","on","yes"}
if WEB_MODE:
    from flask import Flask
    app = Flask(__name__)
    @app.get("/")
    def home():
        return "Bot en ligne"
    def run_flask():
        port = int(os.getenv("PORT", 10000))
        app.run(host="0.0.0.0", port=port)
    threading.Thread(target=run_flask, daemon=True).start()

# ---------- ENV / CONFIG ----------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN") or ""
GUILD_IDS = [int(x) for x in os.getenv("GUILD_IDS","" ).split(",") if x.strip().isdigit()]
ROLE_CROUPIER_ID = int(os.getenv("ROLE_CROUPIER_ID", "0") or 0)  # rôle qui valide
SPIN_GIF_URL = os.getenv("SPIN_GIF_URL", "")  # gif optionnel pour roulette
LEADERBOARD_CHANNEL_ID = int(os.getenv("LEADERBOARD_CHANNEL_ID","0") or 0)  # optionnel (si tu veux poster périodiquement)

# Slots config
def _as_pos_int(name: str, default: int) -> int:
    try: val = int(os.getenv(name, default))
    except Exception: val = default
    return max(1, val)
SLOTS_TOKEN_VALUE = _as_pos_int('SLOTS_TOKEN_VALUE', 100)
SLOTS_LINES = 5 if os.getenv('SLOTS_LINES','5') == '5' else 1
SLOTS_ANIM_FRAMES = int(os.getenv('SLOTS_ANIM_FRAMES', '14'))
SLOTS_ANIM_DELAY = float(os.getenv('SLOTS_ANIM_DELAY', '0.15'))

# Roulette config
ROULETTE_JOIN_TIMEOUT = 300  # 5 min pour trouver un 2e joueur
CROUPIER_TIMEOUT = 180       # 3 min pour valider
SPIN_COUNTDOWN = 5           # 5..1 avant résultat
CROUPIER_COMMISSION = 0.05   # 5%
RED_NUMBERS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}

# ---------- Intents & Bot ----------
intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = True  # pour !sync
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- DB (aiosqlite) ----------
import aiosqlite
DB_PATH = os.getenv("DB_PATH", "casino.db")

async def db_init():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS lb_users(
              guild_id INTEGER NOT NULL,
              user_id  INTEGER NOT NULL,
              total_bet INTEGER NOT NULL DEFAULT 0,
              net       INTEGER NOT NULL DEFAULT 0,
              wins      INTEGER NOT NULL DEFAULT 0,
              losses    INTEGER NOT NULL DEFAULT 0,
              PRIMARY KEY (guild_id, user_id)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS lb_commission(
              guild_id INTEGER PRIMARY KEY,
              amount   INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        await db.commit()

def fmt_kamas(n: int) -> str:
    try:
        return f"{int(n):,}".replace(",", " ")
    except Exception:
        return str(n)

async def _upsert_bet(guild_id: int, user_id: int, amount: int):
    amount = max(0, int(amount))
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO lb_users(guild_id, user_id, total_bet) VALUES(?,?,?)\n             ON CONFLICT(guild_id,user_id) DO UPDATE SET total_bet=total_bet+excluded.total_bet",
            (guild_id, user_id, amount)
        )
        await db.commit()

async def _upsert_net(guild_id: int, user_id: int, delta: int, win: bool|None=None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO lb_users(guild_id, user_id, net, wins, losses) VALUES(?,?,?,0,0)\n             ON CONFLICT(guild_id,user_id) DO UPDATE SET net=lb_users.net+excluded.net",
            (guild_id, user_id, int(delta))
        )
        if win is True:
            await db.execute(
                "UPDATE lb_users SET wins=wins+1 WHERE guild_id=? AND user_id=?",
                (guild_id, user_id)
            )
        elif win is False:
            await db.execute(
                "UPDATE lb_users SET losses=losses+1 WHERE guild_id=? AND user_id=?",
                (guild_id, user_id)
            )
        await db.commit()

async def _add_commission(guild_id: int, amount: int):
    amount = max(0, int(amount))
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO lb_commission(guild_id, amount) VALUES(?,?)\n             ON CONFLICT(guild_id) DO UPDATE SET amount=lb_commission.amount+excluded.amount",
            (guild_id, amount)
        )
        await db.commit()

async def get_leaderboard_rows(guild_id: int) -> List[tuple[int,int,int,int,int]]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id, total_bet, net, wins, losses FROM lb_users WHERE guild_id=? ORDER BY total_bet DESC LIMIT 20",
            (guild_id,)
        )
        rows = await cur.fetchall()
    return rows

# ---------- Sync (vite) ----------
@bot.event
async def on_ready():
    await db_init()
    try:
        if GUILD_IDS:
            for gid in GUILD_IDS:
                await bot.tree.sync(guild=discord.Object(id=gid))
        else:
            # Évite sync() global à chaque boot (lent). On expose !sync.
            pass
    except Exception as e:
        print("Sync error:", e)
    print(f"Connecté en tant que {bot.user}")

@bot.command(name="sync")
@commands.has_permissions(administrator=True)
async def sync_cmd(ctx: commands.Context):
    synced = await ctx.bot.tree.sync(guild=ctx.guild)
    await ctx.reply(f"✅ Sync OK — {len(synced)} commandes mises à jour pour ce serveur.")

# =====================================================
#  SLOTS — 3x3, 5 lignes, 1 jeton (bouton rouge)
# =====================================================
SYMBOLS = ["7️⃣", "⭐", "🔔", "🍇", "🍋", "🍒"]
WEIGHTS = [1,     2,    3,    4,    5,    6 ]
PAYOUTS = {"7️⃣":50, "⭐":25, "🔔":10, "🍇":5, "🍋":3, "🍒":2}
WIN_LINES = [
    [(0,0),(0,1),(0,2)],
    [(1,0),(1,1),(1,2)],
    [(2,0),(2,1),(2,2)],
    [(0,0),(1,1),(2,2)],
    [(0,2),(1,1),(2,0)],
]
_rng = secrets.SystemRandom()

def _wchoice():
    total = sum(WEIGHTS)
    r = _rng.randrange(total)
    acc = 0
    for sym, w in zip(SYMBOLS, WEIGHTS):
        acc += w
        if r < acc:
            return sym
    return SYMBOLS[-1]

def slots_generate_grid():
    return [[_wchoice() for _ in range(3)] for _ in range(3)]

def slots_compute_payout(grid, bet_per_line: int, lines: int):
    active = [1] if lines == 1 else list(range(5))
    total = 0
    details = []
    for i in active:
        (r1,c1),(r2,c2),(r3,c3) = WIN_LINES[i]
        s1,s2,s3 = grid[r1][c1], grid[r2][c2], grid[r3][c3]
        if s1 == s2 == s3:
            mult = PAYOUTS.get(s1, 0)
            if mult:
                win = bet_per_line * mult
                total += win
                details.append((i, s1, mult))
    return total, details

def slots_render_grid(grid):
    rows = [f"| {grid[r][0]} | {grid[r][1]} | {grid[r][2]} |" for r in range(3)]
    return "```
" + "\n".join(rows) + "\n```"

def slots_frames(final_grid, frames: int):
    colA = [ _wchoice() for _ in range(3) ]
    colB = [ _wchoice() for _ in range(3) ]
    colC = [ _wchoice() for _ in range(3) ]
    out = []
    for i in range(frames):
        freeze_A = (i >= int(frames*0.4))
        freeze_B = (i >= int(frames*0.7))
        g = [[None,None,None] for _ in range(3)]
        if freeze_A:
            for r in range(3): g[r][0] = final_grid[r][0]
        else:
            colA = colA[1:] + [_wchoice()]
            for r in range(3): g[r][0] = colA[r]
        if freeze_B:
            for r in range(3): g[r][1] = final_grid[r][1]
        else:
            colB = colB[1:] + [_wchoice()]
            for r in range(3): g[r][1] = colB[r]
        if i == frames-1:
            for r in range(3): g[r][2] = final_grid[r][2]
        else:
            colC = colC[1:] + [_wchoice()]
            for r in range(3): g[r][2] = colC[r]
        out.append(g)
    return out

def slots_build_embed(lines: int, grid, details, footer: Optional[str]):
    lines = 5 if lines == 5 else 1
    bet_per_line = SLOTS_TOKEN_VALUE
    total_bet = bet_per_line * lines
    title = "🎰 **Machine à sous** — 1 jeton / spin"
    desc = (
        f"🪙 **Jeton** : `1`  (valeur `{fmt_kamas(bet_per_line)}` kamas)\n"
        f"🔢 **Lignes actives** : `{lines}`\n"
        f"📦 **Mise totale** : `{fmt_kamas(total_bet)}` kamas\n\n"
        + slots_render_grid(grid or slots_generate_grid())
    )
    if details is not None:
        if details:
            lines_txt = []
            for idx, sym, mult in details:
                label = ["L1","L2","L3","D1","D2"][idx]
                lines_txt.append(f"🔥 **{label}** — {sym}{sym}{sym} ×{mult}")
            total_win = sum(bet_per_line * mult for _,_,mult in details)
            desc += "\n" + "\n".join(lines_txt)
            desc += "\n" + f"**Gain total** : `{fmt_kamas(total_win)}` kamas"
        else:
            desc += "\n**Pas de ligne gagnante.** 😿"
    embed = discord.Embed(title=title, description=desc, color=0xC0392B)
    embed.set_footer(text=footer or "Clique sur le bouton rouge pour lancer un spin (1 jeton)")
    return embed

class SlotsOneTokenView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.spin_lock = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Cette machine est ouverte par un autre joueur.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🪙 1 JETON — 🎰 SPIN", style=discord.ButtonStyle.danger)
    async def btn_spin(self, inter: discord.Interaction, _):
        if self.spin_lock:
            return await inter.response.send_message("Spin déjà en cours…", ephemeral=True)
        self.spin_lock = True
        for c in self.children: c.disabled = True
        try:
            await self.do_spin(inter)
        finally:
            for c in self.children: c.disabled = False
            self.spin_lock = False
            try:
                await inter.edit_original_response(view=self)
            except Exception:
                pass

    async def do_spin(self, inter: discord.Interaction):
        lines = SLOTS_LINES
        bet_per_line = SLOTS_TOKEN_VALUE
        total_bet = bet_per_line * lines
        if total_bet <= 0:
            return await inter.response.send_message("Configuration de mise invalide.", ephemeral=True)

        await _upsert_bet(inter.guild.id, inter.user.id, total_bet)
        final_grid = slots_generate_grid()
        payout, details = slots_compute_payout(final_grid, bet_per_line, lines)
        net = payout - total_bet

        # Animation
        spinning = slots_build_embed(lines, None, None, "\n\n⏳ *La machine tourne…*")
        try:
            await inter.response.edit_message(embed=spinning, view=self)
        except discord.InteractionResponded:
            pass
        msg = inter.message
        for g in slots_frames(final_grid, SLOTS_ANIM_FRAMES):
            await asyncio.sleep(SLOTS_ANIM_DELAY)
            await msg.edit(embed=slots_build_embed(lines, g, None, None), view=self)

        if net > 0:
            await _upsert_net(inter.guild.id, inter.user.id, net, win=True)
        elif net < 0:
            await _upsert_net(inter.guild.id, inter.user.id, -net, win=False)

        await msg.edit(embed=slots_build_embed(lines, final_grid, details, None), view=self)
        try:
            await update_leaderboard_message(inter.guild)
        except Exception:
            pass

@bot.tree.command(name="slots", description="Machine à sous 3×3 — 1 jeton")
async def slots_cmd(interaction: discord.Interaction):
    view = SlotsOneTokenView(interaction.user.id)
    embed = slots_build_embed(SLOTS_LINES, slots_generate_grid(), None, None)
    await interaction.response.send_message(embed=embed, view=view)

# =====================================================
#  ROULETTE — 1v1 avec CROUPIER & commission 5%
# =====================================================
@dataclass
class RouletteGame:
    channel_id: int
    starter_id: int
    stake: int
    duel_type: Optional[str] = None   # "couleur"|"parite"|"plage"
    starter_choice: Optional[str] = None
    joiner_id: Optional[int] = None
    message_id: Optional[int] = None
    state: str = "init"  # init -> choose_duel -> choose_side -> waiting_player -> wait_croupier -> spinning -> done

active_games: Dict[int, List[RouletteGame]] = {}

def roulette_color(n: int) -> str:
    if n == 0: return "vert"
    return "rouge" if n in RED_NUMBERS else "noir"

def roulette_parity(n: int) -> str:
    if n == 0: return "zero"
    return "pair" if (n % 2 == 0) else "impair"

def roulette_range(n: int) -> str:
    if n == 0: return "zero"
    return "1-18" if 1 <= n <= 18 else "19-36"

def add_game(g: RouletteGame):
    active_games.setdefault(g.channel_id, []).append(g)

def remove_game(g: RouletteGame):
    lst = active_games.get(g.channel_id, [])
    if g in lst:
        lst.remove(g)
    if not lst:
        active_games.pop(g.channel_id, None)

# ---- Views ----
class DuelSelectView(discord.ui.View):
    def __init__(self, game: RouletteGame):
        super().__init__(timeout=180)
        self.game = game

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.user.id != self.game.starter_id:
            await inter.response.send_message("Seul le créateur choisit le type de duel.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🔴⚫ Rouge/Noir", style=discord.ButtonStyle.danger)
    async def b_color(self, inter: discord.Interaction, _):
        await self.set_duel(inter, "couleur")

    @discord.ui.button(label="#️⃣ Pair/Impair", style=discord.ButtonStyle.primary)
    async def b_parity(self, inter: discord.Interaction, _):
        await self.set_duel(inter, "parite")

    @discord.ui.button(label="↕️ 1-18 / 19-36", style=discord.ButtonStyle.secondary)
    async def b_range(self, inter: discord.Interaction, _):
        await self.set_duel(inter, "plage")

    async def set_duel(self, inter: discord.Interaction, kind: str):
        self.game.duel_type = kind
        self.game.state = "choose_side"
        for c in self.children: c.disabled = True
        try:
            await inter.response.edit_message(embed=roulette_embed_choose_side(self.game), view=SideSelectView(self.game))
        except discord.InteractionResponded:
            msg = await inter.original_response()
            await msg.edit(embed=roulette_embed_choose_side(self.game), view=SideSelectView(self.game))

class SideSelectView(discord.ui.View):
    def __init__(self, game: RouletteGame):
        super().__init__(timeout=180)
        self.game = game

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.user.id != self.game.starter_id:
            await inter.response.send_message("Seul le créateur choisit son camp.", ephemeral=True)
            return False
        return True

    def _labels(self):
        if self.game.duel_type == "couleur":
            return ("🔴 Rouge", "⚫ Noir")
        if self.game.duel_type == "parite":
            return ("Pair", "Impair")
        return ("1-18", "19-36")

    @discord.ui.button(label="A", style=discord.ButtonStyle.success)
    async def b_a(self, inter: discord.Interaction, btn: discord.ui.Button):
        await self.pick(inter, 0)

    @discord.ui.button(label="B", style=discord.ButtonStyle.secondary)
    async def b_b(self, inter: discord.Interaction, btn: discord.ui.Button):
        await self.pick(inter, 1)

    async def on_timeout(self):
        remove_game(self.game)

    async def pick(self, inter: discord.Interaction, idx: int):
        a,b = self._labels()
        self.game.starter_choice = (a if idx==0 else b).split()[0].lower().replace("🔴","rouge").replace("⚫","noir")
        self.game.state = "waiting_player"
        # Message d'attente avec … animés
        view = JoinView(self.game)
        try:
            await inter.response.edit_message(embed=roulette_embed_wait_player(self.game), view=view)
        except discord.InteractionResponded:
            msg = await inter.original_response()
            await msg.edit(embed=roulette_embed_wait_player(self.game), view=view)
        # animation ...
        channel = inter.channel
        msg = await inter.original_response()
        for i in range(1, 10):
            await asyncio.sleep(0.7)
            if self.game.state != "waiting_player":
                break
            dots = "."* ( (i%3)+1 )
            e = roulette_embed_wait_player(self.game, suffix=f"\n\nEn attente d'un second joueur{dots}")
            try:
                await msg.edit(embed=e, view=view)
            except Exception:
                break
        # timeout d'entrée joueur
        async def _timeout_join():
            await asyncio.sleep(ROULETTE_JOIN_TIMEOUT)
            if self.game.state == "waiting_player" and self.game.joiner_id is None:
                await channel.send(f"⏳ Temps écoulé, partie annulée (créée par <@{self.game.starter_id}>).")
                remove_game(self.game)
        bot.loop.create_task(_timeout_join())

class JoinView(discord.ui.View):
    def __init__(self, game: RouletteGame):
        super().__init__(timeout=ROULETTE_JOIN_TIMEOUT)
        self.game = game

    @discord.ui.button(label="Rejoindre", style=discord.ButtonStyle.primary, emoji="🧍")
    async def b_join(self, inter: discord.Interaction, _):
        if inter.user.id == self.game.starter_id:
            return await inter.response.send_message("Tu es déjà dans la partie.", ephemeral=True)
        if self.game.joiner_id is not None:
            return await inter.response.send_message("Un joueur a déjà rejoint.", ephemeral=True)
        self.game.joiner_id = inter.user.id
        self.game.state = "wait_croupier"
        # ping croupier en DEHORS de l'embed
        role_ping = f"<@&{ROLE_CROUPIER_ID}>" if ROLE_CROUPIER_ID else "CROUPIER"
        await inter.channel.send(f"{role_ping} — merci de **valider les mises** pour démarrer la roulette.")
        # affiche l'embed validation
        view = CroupierView(self.game)
        try:
            await inter.response.edit_message(embed=roulette_embed_wait_croupier(self.game), view=view)
        except discord.InteractionResponded:
            msg = await inter.original_response()
            await msg.edit(embed=roulette_embed_wait_croupier(self.game), view=view)

class CroupierView(discord.ui.View):
    def __init__(self, game: RouletteGame):
        super().__init__(timeout=CROUPIER_TIMEOUT)
        self.game = game

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if ROLE_CROUPIER_ID:
            has_role = discord.utils.get(inter.user.roles, id=ROLE_CROUPIER_ID) is not None if isinstance(inter.user, discord.Member) else False
            if not has_role:
                await inter.response.send_message("Seul le rôle CROUPIER peut valider.", ephemeral=True)
                return False
        return True

    @discord.ui.button(label="Valider les mises", style=discord.ButtonStyle.success, emoji="✅")
    async def b_validate(self, inter: discord.Interaction, _):
        # Début spin
        self.game.state = "spinning"
        try:
            await inter.response.defer(thinking=False)
        except discord.InteractionResponded:
            pass
        # Affiche GIF + compte à rebours
        desc = (
            f"👥 <@{self.game.starter_id}> vs <@{self.game.joiner_id}>\n"
            f"⚔️ Duel : **{self.game.duel_type}** — choix créateur **{self.game.starter_choice}**\n"
            f"💵 Mise : **{fmt_kamas(self.game.stake)}** kamas chacun\n"
        )
        embed = discord.Embed(title="🎡 Roulette — c'est parti !", description=desc+f"⌛ La roue tourne… **{SPIN_COUNTDOWN}**", color=0xF1C40F)
        if SPIN_GIF_URL:
            embed.set_image(url=SPIN_GIF_URL)
        msg = await inter.followup.send(embed=embed, wait=True)
        for t in range(SPIN_COUNTDOWN-1, 0, -1):
            await asyncio.sleep(1)
            embed.description = desc + f"⌛ La roue tourne… **{t}**"
            try:
                await msg.edit(embed=embed)
            except Exception:
                break
        await asyncio.sleep(1)
        # Tirage
        n = secrets.randbelow(37)
        col = roulette_color(n)
        par = roulette_parity(n)
        rng = roulette_range(n)
        # Détermine gagnant selon duel
        def wins(choice: str) -> bool:
            c = choice
            if self.game.duel_type == "couleur":
                return c in {"rouge","noir"} and (col == c)
            if self.game.duel_type == "parite":
                return c in {"pair","impair"} and (par == c)
            if self.game.duel_type == "plage":
                return c in {"1-18","19-36"} and (rng == c)
            return False
        creator_wins = wins(self.game.starter_choice or "")
        winner_id = self.game.starter_id if creator_wins else self.game.joiner_id
        loser_id  = self.game.joiner_id if creator_wins else self.game.starter_id
        # Payout & commission
        pot = self.game.stake * 2
        commission = int(round(pot * CROUPIER_COMMISSION))
        payout = pot - commission
        # Leaderboard: total_bet + net
        await _upsert_bet(inter.guild.id, self.game.starter_id, self.game.stake)
        await _upsert_bet(inter.guild.id, self.game.joiner_id, self.game.stake)
        # net: gagnant gagne (payout - mise propre), perdant perd mise
        win_net = payout - self.game.stake
        lose_net = self.game.stake
        await _upsert_net(inter.guild.id, winner_id,  win_net, win=True)
        await _upsert_net(inter.guild.id, loser_id,   lose_net, win=False)
        await _add_commission(inter.guild.id, commission)
        # Résultat
        color_emoji = "🔴" if col=="rouge" else ("⚫" if col=="noir" else "🟢")
        title = f"🏁 Résultat : {n} {color_emoji}"
        desc2 = (
            f"👥 <@{self.game.starter_id}> vs <@{self.game.joiner_id}>\n"
            f"⚔️ Duel : **{self.game.duel_type}** — choix créateur **{self.game.starter_choice}**\n"
            f"💵 Pot : {fmt_kamas(pot)}k — 🧮 Commission croupier {int(CROUPIER_COMMISSION*100)}% = {fmt_kamas(commission)}k\n"
            f"🏆 Gagnant : <@{winner_id}> **+{fmt_kamas(payout)}k**  |  😿 Perdant : <@{loser_id}> **-{fmt_kamas(self.game.stake)}k**"
        )
        col_for_embed = 0x2ECC71 if col=="vert" else (0xE74C3C if col=="rouge" else 0x2C3E50)
        res = discord.Embed(title=title, description=desc2, color=col_for_embed)
        await inter.followup.send(embed=res)
        self.game.state = "done"
        remove_game(self.game)
        try:
            await update_leaderboard_message(inter.guild)
        except Exception:
            pass

# ---- Embeds helpers ----

def roulette_embed_start(game: RouletteGame):
    return discord.Embed(
        title="🎲 Roulette — création",
        description=(
            f"Créateur : <@{game.starter_id}>\n"
            f"💵 Mise : **{fmt_kamas(game.stake)}** kamas chacun\n\n"
            "Choisis le **type de duel** :"
        ),
        color=0xF1C40F,
    )

def roulette_embed_choose_side(game: RouletteGame):
    a,b = ("Rouge","Noir") if game.duel_type=="couleur" else ("Pair","Impair") if game.duel_type=="parite" else ("1-18","19-36")
    return discord.Embed(
        title="🎯 Choix du camp",
        description=(
            f"Duel : **{game.duel_type}**\n"
            f"Choisis ton camp : **{a}** ou **{b}**"
        ),
        color=0x3498DB,
    )

def roulette_embed_wait_player(game: RouletteGame, suffix: str = ""):
    return discord.Embed(
        title="🕒 En attente d'un second joueur",
        description=(
            f"Créateur : <@{game.starter_id}>  •  Mise **{fmt_kamas(game.stake)}** kamas\n"
            "➡️ **Clique Rejoindre** pour accepter le défi (commande /roulette non nécessaire)" + suffix
        ),
        color=0x95A5A6,
    )

def roulette_embed_wait_croupier(game: RouletteGame):
    return discord.Embed(
        title="📣 En attente du CROUPIER",
        description=(
            f"👥 <@{game.starter_id}> vs <@{game.joiner_id}>\n"
            f"⚔️ Duel : **{game.duel_type}** — choix créateur **{game.starter_choice}**\n"
            f"💵 Mise : **{fmt_kamas(game.stake)}** kamas chacun\n\n"
            "Un croupier doit appuyer sur **Valider les mises** pour lancer la roulette."
        ),
        color=0xE67E22,
    )

# ---- Commande slash ----
@bot.tree.command(name="roulette", description="Créer une roulette 1v1 (croupier requis)")
@app_commands.describe(mise="Mise unitaire (kamas) pour chaque joueur")
async def roulette_cmd(inter: discord.Interaction, mise: int):
    if mise <= 0:
        return await inter.response.send_message("La mise doit être un entier positif.", ephemeral=True)
    game = RouletteGame(channel_id=inter.channel_id, starter_id=inter.user.id, stake=mise)
    add_game(game)
    view = DuelSelectView(game)
    embed = roulette_embed_start(game)
    await inter.response.send_message(embed=embed, view=view)

# =====================================================
#  LEADERBOARD — commande
# =====================================================
@bot.tree.command(name="leaderboard", description="Classement serveur (mises & net)")
async def leaderboard_cmd(inter: discord.Interaction):
    await inter.response.defer(thinking=True)
    rows = await get_leaderboard_rows(inter.guild.id)
    if not rows:
        return await inter.followup.send("Aucune donnée pour l'instant.")
    lines = []
    for i,(uid,total,net,w,l) in enumerate(rows, start=1):
        lines.append(f"**{i}.** <@{uid}> — misé `{fmt_kamas(total)}k` • net `{fmt_kamas(net)}k` • W/L {w}/{l}")
    embed = discord.Embed(title="🏆 Leaderboard serveur", description="\n".join(lines), color=0x9B59B6)
    await inter.followup.send(embed=embed)

# =====================================================
#  MAIN
# =====================================================
if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN manquant")
    bot.run(TOKEN)
