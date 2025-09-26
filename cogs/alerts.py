# cogs/alerts.py
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional, List, Tuple

import discord
from discord import app_commands
from discord.ext import commands

from storage import (
    upsert_message,
    get_message_creator,
    get_participants_detailed,
    incr_leaderboard,
)

# ---------- ENV ----------
ALERT_CHANNEL_ID   = int(os.getenv("ALERT_CHANNEL_ID", "0"))
ROLE_DEF_ID        = int(os.getenv("ROLE_DEF_ID", "0"))
ROLE_DEF2_ID       = int(os.getenv("ROLE_DEF2_ID", "0"))
ROLE_TEST_ID       = int(os.getenv("ROLE_TEST_ID", "0"))
ADMIN_ROLE_ID      = int(os.getenv("ADMIN_ROLE_ID", "0"))  # facultatif ; si 0, pas de restriction côté TEST

# ---------- Constantes réactions ----------
EMOJI_VICTORY = "🏆"
EMOJI_DEFEAT  = "❌"
EMOJI_INCOMP  = "😡"
EMOJI_JOIN    = "👍"

# ---------- Helpers ----------
def _paris_ts(dt: datetime) -> int:
    return int(dt.replace(tzinfo=timezone.utc).timestamp())

# ---------- Embed d'alerte (message envoyé dans le salon d'alertes) ----------
async def build_ping_embed(msg: discord.Message) -> discord.Embed:
    """Construit l'embed d'alerte (le message où les gens réagissent)."""
    creator_id = get_message_creator(msg.id)
    creator_member = msg.guild.get_member(creator_id) if creator_id else None

    # Statut à partir des réactions actuelles
    reactions = {str(r.emoji): r.count for r in msg.reactions}
    win  = reactions.get(EMOJI_VICTORY, 0) > 0
    loss = reactions.get(EMOJI_DEFEAT,  0) > 0
    inc  = reactions.get(EMOJI_INCOMP,  0) > 0

    # État simplifié : "En cours" par défaut
    etat = "⏳ En cours"
    color = discord.Color.orange()
    if win and not loss:
        etat = f"{EMOJI_VICTORY} Défense gagnée"
        color = discord.Color.green()
    elif loss and not win:
        etat = f"{EMOJI_DEFEAT} Défense perdue"
        color = discord.Color.red()
    if inc:
        etat += f"\n{EMOJI_INCOMP} Défense incomplète"

    # Défenseurs + "(ajouté par X)" si pertinent
    defenders_lines: List[str] = []
    for uid, added_by, _ts in get_participants_detailed(msg.id):
        member = msg.guild.get_member(uid)
        name = member.display_name if member else f"<@{uid}>"
        if added_by and added_by != uid:
            adder = msg.guild.get_member(added_by)
            adder_name = adder.display_name if adder else f"<@{added_by}>"
            defenders_lines.append(f"{name} *(ajouté par {adder_name})*")
        else:
            defenders_lines.append(f"{name}")

    defenders_block = "• " + "\n• ".join(defenders_lines) if defenders_lines else "_Aucun défenseur pour le moment._"

    embed = discord.Embed(
        title="⚔️ Alerte attaque percepteur",
        description="⚠️ **Connectez-vous pour prendre la défense !**",
        color=color,
    )
    if creator_member:
        embed.add_field(name="⚡ Déclenché par", value=creator_member.display_name, inline=False)

    embed.add_field(name="État du combat", value=etat, inline=False)

    # Deux sauts de ligne (lisibilité) avant la liste de défenseurs
    embed.add_field(name="\u200b", value="\u200b", inline=False)
    embed.add_field(name="Défenseurs (👍)", value=defenders_block, inline=False)

    embed.set_footer(text="Ajoutez vos réactions : 🏆 gagné • ❌ perdu • 😡 incomplète • 👍 j'ai participé")
    return embed

# ---------- View "Ajouter défenseurs" (sélecteur utilisateurs) ----------
class AddDefendersSelect(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(min_values=1, max_values=3, placeholder="Sélectionne jusqu’à 3 défenseurs à ajouter")

class AddDefendersSelectView(discord.ui.View):
    def __init__(self, bot: commands.Bot, alert_message_id: int, adder_id: int):
        super().__init__(timeout=60)
        self.bot = bot
        self.alert_message_id = alert_message_id
        self.adder_id = adder_id
        self.select = AddDefendersSelect()
        self.add_item(self.select)

    @discord.ui.button(label="Confirmer l’ajout", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        from storage import add_participant, incr_leaderboard  # import local pour éviter cycles
        if interaction.user.id != self.adder_id:
            await interaction.response.send_message("Seul l’initiateur peut confirmer.", ephemeral=True)
            return

        added_any = False
        for user in self.select.values:
            ok = add_participant(self.alert_message_id, user.id, added_by=self.adder_id, source="manual")
            if ok:
                added_any = True
                incr_leaderboard(interaction.guild.id, "defense", user.id)

        try:
            await interaction.response.edit_message(content="Ajout effectué." if added_any else "Aucun ajout (doublons).", view=None)
        except Exception:
            pass

class AddDefendersButtonView(discord.ui.View):
    def __init__(self, bot: commands.Bot, alert_message_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.alert_message_id = alert_message_id

    @discord.ui.button(label="Ajouter défenseurs", style=discord.ButtonStyle.primary, emoji="🛡️")
    async def add_defenders(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = AddDefendersSelectView(self.bot, self.alert_message_id, interaction.user.id)
        await interaction.response.send_message("Sélectionne les défenseurs à ajouter :", view=view, ephemeral=True)

# ---------- View boutons du panneau ----------
class PingButtonsView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def _handle_click(self, interaction: discord.Interaction, role_id: int, team: Optional[int]):
        # TEST (Admin) : contrôle d’accès si ADMIN_ROLE_ID défini
        if role_id == ROLE_TEST_ID and ADMIN_ROLE_ID and ADMIN_ROLE_ID != 0:
            if not any(r.id == ADMIN_ROLE_ID for r in interaction.user.roles):
                await interaction.response.send_message("Bouton réservé aux administrateurs.", ephemeral=True)
                return

        if interaction.guild is None or ALERT_CHANNEL_ID == 0:
            try:
                await interaction.response.send_message("Salon d’alertes non configuré.", ephemeral=True)
            except Exception:
                pass
            return

        alert_channel = interaction.guild.get_channel(ALERT_CHANNEL_ID)
        if not isinstance(alert_channel, discord.TextChannel):
            try:
                await interaction.response.send_message("Salon d’alertes introuvable.", ephemeral=True)
            except Exception:
                pass
            return

        # Répond d’abord (évite les "Unknown interaction")
        try:
            await interaction.response.defer(ephemeral=True, thinking=False)
        except Exception:
            pass

        role_mention = f"<@&{role_id}>" if role_id else ""
        content = f"{role_mention} — **Percepteur attaqué !** Merci de vous connecter." if role_mention else "**Percepteur attaqué !** Merci de vous connecter."

        # Envoie l’alerte
        msg = await alert_channel.send(content)

        # Enregistre en DB (création message + créateur + team)
        upsert_message(
            msg.id,
            interaction.guild.id,
            alert_channel.id,
            _paris_ts(msg.created_at),
            creator_id=interaction.user.id,
            team=team,
        )
        incr_leaderboard(interaction.guild.id, "pingeur", interaction.user.id)

        # Ajoute l’embed d’alerte
        emb = await build_ping_embed(msg)
        try:
            await msg.edit(embed=emb)
        except Exception:
            pass

        # Retour utilisateur
        try:
            await interaction.followup.send("✅ Alerte envoyée.", ephemeral=True)
        except Exception:
            pass

    # 🛡️ Emoji bouclier sur les deux boutons de guilde
    @discord.ui.button(label="Guilde 1", style=discord.ButtonStyle.primary, emoji="🛡️")
    async def btn_def(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_click(interaction, ROLE_DEF_ID, team=1)

    @discord.ui.button(label="Guilde 2", style=discord.ButtonStyle.danger, emoji="🛡️")
    async def btn_def2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_click(interaction, ROLE_DEF2_ID, team=2)

    @discord.ui.button(label="TEST (Admin)", style=discord.ButtonStyle.secondary)
    async def btn_test(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_click(interaction, ROLE_TEST_ID, team=None)

# ---------- Cog ----------
class AlertsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="pingpanel", description="Publier le panneau de ping des percepteurs (défenses)")
    async def pingpanel(self, interaction: discord.Interaction):
        """Publie le panneau avec les boutons (Guilde 1 / Guilde 2 / TEST)."""
        # --- Nouvel embed (maquette demandée) ---
        title = "⚔️ Ping défenses percepteurs ⚔️"
        lines = []
        lines.append("**📢 Clique sur le bouton de la guilde qui se fait attaquer pour générer automatiquement un ping dans le canal défense.**")
        lines.append("")  # saut de ligne
        lines.append("*⚠️ Le bouton **TEST** n’est accessible qu’aux administrateurs pour la gestion du bot.*")

        embed = discord.Embed(
            title=title,
            description="\n".join(lines),
            color=discord.Color.blurple()
        )

        view = PingButtonsView(self.bot)
        await interaction.response.send_message(embed=embed, view=view)

async def setup(bot: commands.Bot):
    await bot.add_cog(AlertsCog(bot))
    # View persistante : permet aux anciens panneaux de rester cliquables après redémarrage
    bot.add_view(PingButtonsView(bot))
