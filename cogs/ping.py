import os
import datetime
from typing import Dict, Set, Optional, Tuple

import discord
from discord import app_commands
from discord.ext import commands

# =========================
#  ENV VARS (Render → Environment)
# =========================
CHANNEL_BUTTONS_ID = int(os.getenv("CHANNEL_BUTTONS_ID", "0"))     # salon du panneau (boutons)
CHANNEL_DEFENSE_ID = int(os.getenv("CHANNEL_DEFENSE_ID", "0"))     # salon des alertes
ROLE_DEF_ID = int(os.getenv("ROLE_DEF_ID", "0"))                   # rôle @Def
ROLE_DEF2_ID = int(os.getenv("ROLE_DEF2_ID", "0"))                 # rôle @Def2

ORANGE = discord.Color.orange()
GREEN = discord.Color.green()
RED = discord.Color.red()

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
        side: str,                    # "Def" | "Def2"
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
        self.incomplete: bool = False               # orthogonal à won/lost
        self.participants: Set[int] = set()         # utilisateurs ayant mis 👍

# base_message_id -> state
alert_states: Dict[int, AlertState] = {}

# =========================
#  Helpers
# =========================
def _title_for_side(side: str) -> str:
    return "⚠️ Alerte Percepteur – Guilde 1" if side == "Def" else "⚠️ Alerte Percepteur – Guilde 2"

def _status_and_color(state: AlertState) -> Tuple[str, discord.Color]:
    # Texte d'état + couleur, avec "incomplète" orthogonal
    suffix = " (incomplète)" if state.incomplete and (state.won or state.lost) else ""
    if state.won:
        return f"🏆 **Défense gagnée{suffix}**", GREEN
    if state.lost:
        return f"❌ **Défense perdue{suffix}**", RED
    if state.incomplete:
        return "😡 **Défense incomplète**", ORANGE
    return "⏳ Défense en cours (réagissez pour mettre à jour)", ORANGE

def build_embed(state: AlertState, guild: Optional[discord.Guild]) -> discord.Embed:
    status_line, color = _status_and_color(state)

    e = discord.Embed(
        title=_title_for_side(state.side),
        description="🔔 **Connectez-vous pour prendre la défense**\n\n" + status_line,
        color=color,
        timestamp=datetime.datetime.utcnow()
    )

    # Indication du déclencheur (dans l'embed seulement, pas de ping texte de l'utilisateur)
    e.add_field(name="🧑‍✈️ Déclenché par", value=f"<@{state.clicked_by_id}>", inline=True)

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
        e.add_field(name="🛡️ Défenseurs (👍)", value=", ".join(names), inline=False)
    else:
        e.add_field(name="🛡️ Défenseurs (👍)", value="—", inline=False)

    e.set_footer(text="Ajoutez : 🏆 (gagnée), ❌ (perdue), 😡 (incomplète), 👍 (participation)")
    return e

# Mention forcée des rôles (au cas où les mentions seraient restreintes par défaut)
ALLOWED_MENTIONS_ROLES = discord.AllowedMentions(roles=True, users=False, everyone=False)

# =========================
#  Vue avec boutons (persistante)
# =========================
class PingButtonsView(discord.ui.View):
    """
    Panneau avec 2 boutons : Guilde 1 (@Def) / Guilde 2 (@Def2).
    Vue PERSISTANTE : enregistrez-la au démarrage avec bot.add_view(PingButtonsView()).
    """
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Guilde 1 (Def)", style=discord.ButtonStyle.primary, custom_id="ping_def")
    async def btn_def(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_click(interaction, side="Def")

    @discord.ui.button(label="Guilde 2 (Def2)", style=discord.ButtonStyle.danger, custom_id="ping_def2")
    async def btn_def2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_click(interaction, side="Def2")

    async def _handle_click(self, interaction: discord.Interaction, side: str):
        # Accusé de réception immédiat pour éviter 10062
        await interaction.response.defer(thinking=False)

        # Vérifs ENV / salons
        target_ch = interaction.client.get_channel(CHANNEL_DEFENSE_ID)  # type: ignore
        if CHANNEL_DEFENSE_ID == 0 or not isinstance(target_ch, (discord.TextChannel, discord.Thread)):
            return await interaction.followup.send("⚠️ CHANNEL_DEFENSE_ID non configuré ou salon introuvable.", ephemeral=True)

        # Mention du rôle (hors embed)
        if side == "Def":
            rid = ROLE_DEF_ID
            role_mention = f"<@&{rid}>" if rid else "@Def"
            guild_label = "Guilde 1"
        else:
            rid = ROLE_DEF2_ID
            role_mention = f"<@&{rid}>" if rid else "@Def2"
            guild_label = "Guilde 2"

        base_text = f"{role_mention} — **Percepteur attaqué** ({guild_label}) !"

        # Message texte (ping)
        base_msg = await target_ch.send(content=base_text, allowed_mentions=ALLOWED_MENTIONS_ROLES)

        # Embed initial (reply au ping pour liaison visuelle)
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

        # Mémoriser l'état
        state.embed_message_id = embed_msg.id
        alert_states[base_msg.id] = state

        # Confirmation à l'utilisateur
        await interaction.followup.send("✅ Alerte envoyée dans le salon d'alerte.", ephemeral=True)

# =========================
#  Cog
# =========================
class PingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # Publie le panneau de boutons dans CHANNEL_BUTTONS_ID
    @app_commands.command(name="pingpanel", description="Publier le panneau de ping (@Def / @Def2).")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def pingpanel(self, interaction: discord.Interaction):
        # Accusé de réception immédiat pour éviter 10062
        await interaction.response.defer(ephemeral=True, thinking=False)

        panel_ch = interaction.client.get_channel(CHANNEL_BUTTONS_ID)  # type: ignore
        if CHANNEL_BUTTONS_ID == 0 or not isinstance(panel_ch, (discord.TextChannel, discord.Thread)):
            return await interaction.followup.send("⚠️ CHANNEL_BUTTONS_ID non configuré ou salon introuvable.", ephemeral=True)

        embed = discord.Embed(
            title="📢 Bot de Ping Percepteur",
            description=(
                "Cliquez sur la guilde qui se fait attaquer pour **alerter les joueurs**.\n"
                "Ne cliquez **qu'une seule fois**."
            ),
            color=ORANGE
        )
        await panel_ch.send(embed=embed, view=PingButtonsView())
        await interaction.followup.send("✅ Panneau publié.", ephemeral=True)

    # Mets à jour l'embed d'alerte au fil des réactions (dans CHANNEL_DEFENSE_ID)
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        await self._handle_reaction_update(payload, added=True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        await self._handle_reaction_update(payload, added=False)

    async def _handle_reaction_update(self, payload: discord.RawReactionActionEvent, added: bool):
        # Ne traite que le salon cible
        if CHANNEL_DEFENSE_ID == 0 or payload.channel_id != CHANNEL_DEFENSE_ID:
            return

        # Retrouver l'état par base_message_id ou embed_message_id
        state = alert_states.get(payload.message_id)
        if state is None:
            for st in alert_states.values():
                if st.embed_message_id == payload.message_id:
                    state = st
                    break
        if state is None:
            return

        # Ignore les bots
        if self.bot.user and payload.user_id == self.bot.user.id:
            return

        emoji = str(payload.emoji)

        # Récupérer le message embed
        channel = self.bot.get_channel(state.channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return
        try:
            embed_msg = await channel.fetch_message(state.embed_message_id)
        except discord.NotFound:
            return

        # Mettre à jour les drapeaux (won/lost exclusifs ; incomplete orthogonal)
        if emoji == "🏆":
            if added:
                state.won = True
                state.lost = False
            else:
                state.won = False
        elif emoji == "❌":
            if added:
                state.lost = True
                state.won = False
            else:
                state.lost = False
        elif emoji == "😡":
            state.incomplete = added
        elif emoji == "👍":
            if added:
                state.participants.add(payload.user_id)
            else:
                state.participants.discard(payload.user_id)
        else:
            # autres emojis ignorés
            return

        # Reconstruire l'embed et éditer
        new_embed = build_embed(state, embed_msg.guild)
        try:
            await embed_msg.edit(embed=new_embed)
        except Exception:
            pass

# =========================
#  setup (cog)
# =========================
async def setup(bot: commands.Bot):
    await bot.add_cog(PingCog(bot))
