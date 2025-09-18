import os
import datetime
from typing import Dict, Set, Optional

import discord
from discord import app_commands
from discord.ext import commands

# =========================
#  ENV VARS (Render → Environment)
# =========================
# Salon où s'affiche le panneau (boutons)
CHANNEL_BUTTONS_ID = int(os.getenv("CHANNEL_BUTTONS_ID", "0"))
# Salon où part l'alerte (ping + embed)
PING_TARGET_CHANNEL_ID = int(os.getenv("PING_TARGET_CHANNEL_ID", "0"))
# Rôles à ping
ROLE_DEF_ID = int(os.getenv("ROLE_DEF_ID", "0"))     # @DEF (Guilde 1)
ROLE_DEF2_ID = int(os.getenv("ROLE_DEF2_ID", "0"))   # @DEF2 (Guilde 2)

# =========================
#  État d'une alerte
# =========================
class AlertState:
    def __init__(
        self,
        guild_id: int,
        channel_id: int,
        base_message_id: int,
        embed_message_id: int,
        side: str,                    # "DEF" | "DEF2"
        clicked_by_id: int
    ):
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.base_message_id = base_message_id      # message texte avec la mention du rôle
        self.embed_message_id = embed_message_id    # message embed à éditer
        self.side = side
        self.clicked_by_id = clicked_by_id
        self.won: bool = False
        self.lost: bool = False
        self.incomplete: bool = False
        self.participants: Set[int] = set()         # utilisateurs ayant mis 👍

# base_message_id -> state
alert_states: Dict[int, AlertState] = {}

ORANGE = discord.Color.orange()
GREEN = discord.Color.green()
RED = discord.Color.red()


def _duel_title(side: str) -> str:
    return "🛎️ Alerte Percepteur – Guilde 1" if side == "DEF" else "🛎️ Alerte Percepteur – Guilde 2"


def build_embed(state: AlertState, guild: Optional[discord.Guild]) -> discord.Embed:
    # Statut + couleur
    status_line = "⏳ Défense en cours (réagissez pour mettre à jour)"
    color = ORANGE
    if state.won:
        status_line = "🏆 **Défense gagnée**"
        color = GREEN
    elif state.lost:
        status_line = "❌ **Défense perdue**"
        color = RED
    elif state.incomplete:
        status_line = "😡 **Défense incomplète**"
        color = ORANGE

    e = discord.Embed(
        title=_duel_title(state.side),
        description=(
            "Bot de ping — cliquez sur la guilde qui se fait attaquer pour **alerter les joueurs**.\n"
            "Ne cliquez **qu'une seule fois**.\n\n"
            f"{status_line}"
        ),
        color=color,
        timestamp=datetime.datetime.utcnow()
    )

    # Ping effectué par
    e.add_field(name="📣 Ping effectué par", value=f"<@{state.clicked_by_id}>", inline=True)

    # Liste des défenseurs (👍)
    if state.participants:
        names = []
        if guild:
            for uid in list(state.participants)[:25]:
                m = guild.get_member(uid)
                names.append(m.display_name if m else f"<@{uid}>")
        else:
            for uid in list(state.participants)[:25]:
                names.append(f"<@{uid}>")
        e.add_field(name="🧙 Défenseurs (👍)", value=", ".join(names), inline=False)
    else:
        e.add_field(name="🧙 Défenseurs (👍)", value="—", inline=False)

    e.set_footer(text="Mettez 🏆 (gagnée), ❌ (perdue), 😡 (incomplète), 👍 (participation)")
    return e


class PingButtonsView(discord.ui.View):
    """Panneau avec 2 boutons : Guilde 1 (DEF) / Guilde 2 (DEF2)."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Guilde 1 (DEF)", style=discord.ButtonStyle.primary, custom_id="ping_def")
    async def btn_def(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_click(interaction, side="DEF")

    @discord.ui.button(label="Guilde 2 (DEF2)", style=discord.ButtonStyle.danger, custom_id="ping_def2")
    async def btn_def2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_click(interaction, side="DEF2")

    async def _handle_click(self, interaction: discord.Interaction, side: str):
        # Vérifs basiques ENV / salons
        if PING_TARGET_CHANNEL_ID == 0:
            return await interaction.response.send_message("⚠️ PING_TARGET_CHANNEL_ID non configuré.", ephemeral=True)
        target_ch = interaction.client.get_channel(PING_TARGET_CHANNEL_ID)  # type: ignore
        if not isinstance(target_ch, (discord.TextChannel, discord.Thread)):
            return await interaction.response.send_message("⚠️ Salon cible introuvable.", ephemeral=True)

        # Mention du rôle (hors embed)
        role_id = ROLE_DEF_ID if side == "DEF" else ROLE_DEF2_ID
        role_mention = f"<@&{role_id}>" if role_id else ("@DEF" if side == "DEF" else "@DEF2")
        who = interaction.user.mention

        # Message texte (ping)
        base_text = (
            f"{role_mention} — **Percepteur attaqué** ({'Guilde 1' if side=='DEF' else 'Guilde 2'}) ! "
            f"Merci de vous connecter. (Ping effectué par {who})"
        )
        await interaction.response.send_message("✅ Alerte envoyée dans le salon d'alerte.", ephemeral=True)
        base_msg = await target_ch.send(content=base_text)

        # Embed initial (reply au ping pour les lier visuellement)
        state = AlertState(
            guild_id=base_msg.guild.id if base_msg.guild else 0,
            channel_id=base_msg.channel.id,
            base_message_id=base_msg.id,
            embed_message_id=0,
            side=side,
            clicked_by_id=interaction.user.id,
        )
        embed = build_embed(state, base_msg.guild)
        embed_msg = await target_ch.send(embed=embed, reference=base_msg, mention_author=False)

        # On mémorise l'état
        state.embed_message_id = embed_msg.id
        alert_states[base_msg.id] = state


class PingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # Publie le panneau de boutons dans CHANNEL_BUTTONS_ID
    @app_commands.command(name="pingpanel", description="Publier le panneau de ping (DEF / DEF2).")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def pingpanel(self, interaction: discord.Interaction):
        if CHANNEL_BUTTONS_ID == 0:
            return await interaction.response.send_message("⚠️ CHANNEL_BUTTONS_ID non configuré.", ephemeral=True)
        panel_ch = interaction.client.get_channel(CHANNEL_BUTTONS_ID)  # type: ignore
        if not isinstance(panel_ch, (discord.TextChannel, discord.Thread)):
            return await interaction.response.send_message("⚠️ Salon panneau introuvable.", ephemeral=True)

        embed = discord.Embed(
            title="📢 Bot de Ping Percepteur",
            description=(
                "Cliquez sur la guilde qui se fait attaquer pour **alerter les joueurs**.\n"
                "Ne cliquez **qu'une seule fois**."
            ),
            color=ORANGE
        )
        await panel_ch.send(embed=embed, view=PingButtonsView())
        await interaction.response.send_message("✅ Panneau publié.", ephemeral=True)

    # Mets à jour l'embed d'alerte au fil des réactions (dans PING_TARGET_CHANNEL_ID)
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        await self._handle_reaction_update(payload, added=True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        await self._handle_reaction_update(payload, added=False)

    async def _handle_reaction_update(self, payload: discord.RawReactionActionEvent, added: bool):
        # On ignore si pas le salon cible
        if PING_TARGET_CHANNEL_ID == 0 or payload.channel_id != PING_TARGET_CHANNEL_ID:
            return

        # On met à jour l'état seulement si la réaction est sur le message "base" (ping texte) OU sur l'embed lié
        state = alert_states.get(payload.message_id)
        if state is None:
            # peut-être que la réaction est sur l'embed -> retrouver le state associé
            for st in alert_states.values():
                if st.embed_message_id == payload.message_id:
                    state = st
                    break
        if state is None:
            return

        # Ignore les bots
        if payload.user_id == (self.bot.user.id if self.bot.user else 0):
            return

        emoji = str(payload.emoji)

        # Récupérer le channel et l'embed message
        channel = self.bot.get_channel(state.channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return

        # Recalculer la liste des défenseurs (👍) depuis l'embed_message
        try:
            embed_msg = await channel.fetch_message(state.embed_message_id)
        except discord.NotFound:
            return

        # Mettre à jour les drapeaux statut
        if emoji == "🏆":
            if added:
                state.won, state.lost, state.incomplete = True, False, False
        elif emoji == "❌":
            if added:
                state.won, state.lost, state.incomplete = False, True, False
        elif emoji == "😡":
            if added:
                state.won, state.lost, state.incomplete = False, False, True
        elif emoji == "👍":
            if added:
                state.participants.add(payload.user_id)
            else:
                state.participants.discard(payload.user_id)
        else:
            # autres emojis ignorés
            return

        # Reconstruire l'embed
        guild = embed_msg.guild
        new_embed = build_embed(state, guild)

        # Editer l'embed
        try:
            await embed_msg.edit(embed=new_embed)
        except Exception:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(PingCog(bot))
