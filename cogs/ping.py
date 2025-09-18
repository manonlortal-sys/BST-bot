import os
import asyncio
import datetime
from typing import Dict, Set, Optional

import discord
from discord.ext import commands

# --- ENV (à configurer dans Render) ---
DEF_ROLE_ID = int(os.getenv("DEF_ROLE_ID", "0"))                 # rôle @DEF (guilde 1)
DEF2_ROLE_ID = int(os.getenv("DEF2_ROLE_ID", "0"))               # rôle @DEF2 (guilde 2)
ALERT_BUTTONS_CHANNEL_ID = int(os.getenv("ALERT_BUTTONS_CHANNEL_ID", "0"))  # canal panneau (boutons)
PING_TARGET_CHANNEL_ID = int(os.getenv("PING_TARGET_CHANNEL_ID", "0"))      # canal d'alerte (où ça ping)

# --- États en mémoire pour suivi des embeds (par message id du message d'alerte) ---
class AlertState:
    def __init__(self, guild_id: int, channel_id: int, message_id: int, side: str, clicked_by_id: int):
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.message_id = message_id
        self.side = side  # "DEF" / "DEF2"
        self.clicked_by_id = clicked_by_id
        self.won = False
        self.lost = False
        self.incomplete = False
        self.participants: Set[int] = set()

alert_states: Dict[int, AlertState] = {}  # message_id -> AlertState

ORANGE = discord.Color.orange()
GREEN = discord.Color.green()
RED = discord.Color.red()

def build_embed(state: AlertState, guild: Optional[discord.Guild]) -> discord.Embed:
    title = "🛎️ Alerte Percepteur – Guilde 1" if state.side == "DEF" else "🛎️ Alerte Percepteur – Guilde 2"
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

    embed = discord.Embed(
        title=title,
        description=(
            "Bot de ping — cliquez sur la guilde qui se fait attaquer pour alerter les joueurs. "
            "Ne cliquez **qu'une seule fois**.\n\n"
            f"{status_line}"
        ),
        color=color,
        timestamp=datetime.datetime.utcnow()
    )
    # Ping effectué par
    mention = f"<@{state.clicked_by_id}>"
    embed.add_field(name="📣 Ping effectué par", value=mention, inline=True)

    # Liste des défenseurs (👍)
    if state.participants:
        names = []
        if guild:
            for uid in list(state.participants)[:20]:  # limite affichage
                m = guild.get_member(uid)
                names.append(m.display_name if m else f"<@{uid}>")
        else:
            for uid in list(state.participants)[:20]:
                names.append(f"<@{uid}>")
        embed.add_field(name="🧙 Défenseurs (👍)", value=", ".join(names), inline=False)
    else:
        embed.add_field(name="🧙 Défenseurs (👍)", value="—", inline=False)

    embed.set_footer(text="Mettez 🏆 (gagnée), ❌ (perdue), 😡 (incomplète), 👍 (participation)")
    return embed


class PingButtonsView(discord.ui.View):
    def __init__(self, timeout: float = 300):
        super().__init__(timeout=timeout)

    @discord.ui.button(label="Guilde 1 (DEF)", style=discord.ButtonStyle.primary, custom_id="ping_def")
    async def ping_def(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_click(interaction, side="DEF")

    @discord.ui.button(label="Guilde 2 (DEF2)", style=discord.ButtonStyle.danger, custom_id="ping_def2")
    async def ping_def2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_click(interaction, side="DEF2")

    async def _handle_click(self, interaction: discord.Interaction, side: str):
        # Vérifications basiques
        if PING_TARGET_CHANNEL_ID == 0:
            return await interaction.response.send_message(
                "⚠️ PING_TARGET_CHANNEL_ID non configuré.", ephemeral=True
            )
        target_ch = interaction.client.get_channel(PING_TARGET_CHANNEL_ID)  # type: ignore
        if not isinstance(target_ch, (discord.TextChannel, discord.Thread)):
            return await interaction.response.send_message(
                "⚠️ Le canal cible d'alerte est introuvable.", ephemeral=True
            )

        # Mention du rôle en message texte (pas dans l'embed) pour que le ping parte bien
        role_id = DEF_ROLE_ID if side == "DEF" else DEF2_ROLE_ID
        role_mention = f"<@&{role_id}>" if role_id else ("@DEF" if side == "DEF" else "@DEF2")

        who = interaction.user.mention
        text = (
            f"{role_mention} — **Percepteur attaqué** ({'Guilde 1' if side=='DEF' else 'Guilde 2'}) ! "
            f"Merci de vous connecter. (Ping effectué par {who})"
        )

        # Envoyer le message d'alerte + embed associé
        await interaction.response.send_message("✅ Alerte envoyée dans le salon d'alerte.", ephemeral=True)

        sent = await target_ch.send(content=text)

        state = AlertState(
            guild_id=sent.guild.id if sent.guild else 0,
            channel_id=sent.channel.id,
            message_id=sent.id,
            side=side,
            clicked_by_id=interaction.user.id,
        )
        alert_states[sent.id] = state

        embed = build_embed(state, sent.guild)
        await target_ch.send(embed=embed)

        # Optionnel: tu peux lier l'embed au message original via un reply
        # embed_msg = await target_ch.send(embed=embed)
        # state.embed_message_id = embed_msg.id

        # Ici, on ne force pas l'ajout de réactions : les joueurs les mettront eux-mêmes.


class Ping(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # Slash command pour déployer le panneau de boutons
    @discord.app_commands.command(name="alerte", description="Publier le panneau de ping (DEF / DEF2).")
    @discord.app_commands.checks.has_permissions(manage_guild=True)
    async def alerte(self, interaction: discord.Interaction):
        if ALERT_BUTTONS_CHANNEL_ID == 0:
            return await interaction.response.send_message(
                "⚠️ ALERT_BUTTONS_CHANNEL_ID non configuré.", ephemeral=True
            )

        panel_ch = interaction.client.get_channel(ALERT_BUTTONS_CHANNEL_ID)  # type: ignore
        if not isinstance(panel_ch, (discord.TextChannel, discord.Thread)):
            return await interaction.response.send_message(
                "⚠️ Le salon de panneau (boutons) est introuvable.", ephemeral=True
            )

        embed = discord.Embed(
            title="🛎️ Bot de Ping Percepteur",
            description=(
                "Cliquez sur la guilde qui se fait attaquer pour **alerter les joueurs**.\n"
                "Ne cliquez **qu'une seule fois**."
            ),
            color=ORANGE,
        )
        view = PingButtonsView()
        await panel_ch.send(embed=embed, view=view)
        await interaction.response.send_message("✅ Panneau publié.", ephemeral=True)

    # Mise à jour de l'embed d'alerte selon les réactions (sur le message d'alerte dans le canal cible)
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        await self._handle_reaction_update(payload, added=True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        await self._handle_reaction_update(payload, added=False)

    async def _handle_reaction_update(self, payload: discord.RawReactionActionEvent, added: bool):
        # On ne considère que le canal cible d'alerte
        if payload.channel_id != PING_TARGET_CHANNEL_ID:
            return

        # Récup état
        state = alert_states.get(payload.message_id)
        if state is None:
            return

        # Ignorer les bots
        if payload.user_id == self.bot.user.id:
            return

        # Emoji mapping
        emoji = str(payload.emoji)
        # Mises à jour d'état
        if emoji == "🏆":
            state.won = added or state.won  # add = True, remove = False (on ne repasse pas à False si retiré)
            state.lost = False if added else state.lost
            state.incomplete = False if added else state.incomplete
        elif emoji == "❌":
            state.lost = added or state.lost
            state.won = False if added else state.won
            state.incomplete = False if added else state.incomplete
        elif emoji == "😡":
            state.incomplete = added or state.incomplete
            if added:
                state.won = False
                state.lost = False
        elif emoji == "👍":
            if added:
                state.participants.add(payload.user_id)
            else:
                state.participants.discard(payload.user_id)
        else:
            # autres emojis ignorés
            return

        # Éditer le dernier embed “lié” (on va retrouver le dernier embed après le message texte)
        channel = self.bot.get_channel(state.channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return
        try:
            msg = await channel.fetch_message(state.message_id)
        except discord.NotFound:
            return

        # On va chercher le message embed qui suit immédiatement (si possible)
        # Simplification: on cherche dans l'historique proche le 1er message du bot avec embed.
        async for m in channel.history(limit=10, after=discord.Object(id=state.message_id)):
            if m.author.id == self.bot.user.id and m.embeds:
                new_embed = build_embed(state, msg.guild)
                try:
                    await m.edit(embed=new_embed)
                except Exception:
                    pass
                break


async def setup(bot: commands.Bot):
    await bot.add_cog(Ping(bot))
```0
