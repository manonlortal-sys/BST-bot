import os
from typing import List, Optional
import discord
from discord.ext import commands

from storage import (
    upsert_message,
    incr_leaderboard,
    get_message_creator,
    get_participants_detailed,
    try_claim_first_defender,
    get_first_defender,
    add_participant,
)

from .leaderboard import update_leaderboards

# ---------- ENV ----------
ALERT_CHANNEL_ID = int(os.getenv("ALERT_CHANNEL_ID", "0"))
ROLE_DEF_ID = int(os.getenv("ROLE_DEF_ID", "0"))
ROLE_DEF2_ID = int(os.getenv("ROLE_DEF2_ID", "0"))
ROLE_TEST_ID = int(os.getenv("ROLE_TEST_ID", "0"))
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", "0"))

# ---------- Emojis ----------
EMOJI_VICTORY = "🏆"
EMOJI_DEFEAT = "❌"
EMOJI_INCOMP = "😡"
EMOJI_JOIN = "👍"

# ---------- Embed constructeur ----------
async def build_ping_embed(msg: discord.Message) -> discord.Embed:
    creator_id: Optional[int] = get_message_creator(msg.id)
    creator_member = msg.guild.get_member(creator_id) if creator_id else None

    # Liste des participants depuis la DB (avec "ajouté par ...")
    parts = get_participants_detailed(msg.id)  # [(user_id, added_by, ts), ...]
    lines: List[str] = []
    for user_id, added_by, _ in parts:
        member = msg.guild.get_member(user_id)
        name = member.display_name if member else f"<@{user_id}>"
        if added_by and added_by != user_id:
            bym = msg.guild.get_member(added_by)
            byname = bym.display_name if bym else f"<@{added_by}>"
            lines.append(f"{name} (ajouté par {byname})")
        else:
            lines.append(name)
    defenders_block = "• " + "\n• ".join(lines) if lines else "_Aucun défenseur pour le moment._"

    # Etat (couleur + texte) depuis les réactions actuelles
    reactions = {str(r.emoji): r for r in msg.reactions}
    win  = (EMOJI_VICTORY in reactions and reactions[EMOJI_VICTORY].count > 0)
    loss = (EMOJI_DEFEAT in reactions and reactions[EMOJI_DEFEAT].count > 0)
    incomplete = (EMOJI_INCOMP in reactions and reactions[EMOJI_INCOMP].count > 0)

    if win and not loss:
        color = discord.Color.green()
        etat = f"{EMOJI_VICTORY} **Défense gagnée**"
        if incomplete: etat += f"\n{EMOJI_INCOMP} Défense incomplète"
    elif loss and not win:
        color = discord.Color.red()
        etat = f"{EMOJI_DEFEAT} **Défense perdue**"
        if incomplete: etat += f"\n{EMOJI_INCOMP} Défense incomplète"
    else:
        color = discord.Color.orange()
        etat = "⏳ **En cours / à confirmer**"
        if incomplete: etat += f"\n{EMOJI_INCOMP} Défense incomplète"

    embed = discord.Embed(
        title="🛡️ Alerte Percepteur",
        description="⚠️ **Connectez-vous pour prendre la défense !**",
        color=color,
    )
    embed.add_field(name="État du combat", value=etat, inline=False)
    embed.add_field(name="Défenseurs (👍 ou ajout via bouton)", value=defenders_block, inline=False)
    if creator_member:
        embed.add_field(name="⚡ Déclenché par", value=creator_member.display_name, inline=False)
    embed.set_footer(text="Réagissez : 🏆 gagné • ❌ perdu • 😡 incomplète • 👍 j'ai participé")
    return embed

# ---------- View: sélection utilisateurs (max 3) ----------
class AddDefendersSelectView(discord.ui.View):
    def __init__(self, bot: commands.Bot, message_id: int, claimer_id: int):
        super().__init__(timeout=120)
        self.bot = bot
        self.message_id = message_id
        self.claimer_id = claimer_id
        self.user_select = discord.ui.UserSelect(min_values=1, max_values=3, placeholder="Sélectionne jusqu'à 3 défenseurs")
        self.add_item(self.user_select)

    @discord.ui.button(label="Confirmer l'ajout", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 🔧 CORRECTIF: on défère tout de suite pour éviter "échec de l'interaction"
        await interaction.response.defer(ephemeral=True, thinking=True)

        if interaction.user.id != self.claimer_id:
            await interaction.followup.send("Action réservée au premier défenseur.", ephemeral=True)
            return

        if not self.user_select.values:
            await interaction.followup.send("Sélection vide.", ephemeral=True)
            return

        guild = interaction.guild
        channel = guild.get_channel(interaction.channel_id)
        msg = await channel.fetch_message(self.message_id)

        added_any = False
        for member in self.user_select.values:
            inserted = add_participant(self.message_id, member.id, self.claimer_id, "button")
            if inserted:
                added_any = True
                incr_leaderboard(guild.id, "defense", member.id)

        if added_any:
            emb = await build_ping_embed(msg)
            try:
                await msg.edit(embed=emb)
            except Exception:
                pass
            try:
                await update_leaderboards(self.bot, guild)
            except Exception:
                pass

        await interaction.followup.send("✅ Ajout effectué.", ephemeral=True)
        self.stop()

# ---------- View: bouton à ajouter après 1er 👍 ----------
class AddDefendersButtonView(discord.ui.View):
    def __init__(self, bot: commands.Bot, message_id: int):
        # View non persistante, attachée au message d'alerte
        super().__init__(timeout=None)
        self.bot = bot
        self.message_id = message_id

    @discord.ui.button(label="Ajouter défenseurs", style=discord.ButtonStyle.primary, emoji="🛡️", custom_id="add_defenders")
    async def add_defenders(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Vérifie que l'utilisateur est bien le premier défenseur
        first_id = get_first_defender(self.message_id)
        if first_id is None or interaction.user.id != first_id:
            await interaction.response.send_message("Bouton réservé au premier défenseur (premier 👍).", ephemeral=True)
            return
        # Ouvre un select ephemeral
        await interaction.response.send_message(
            "Sélectionne jusqu'à 3 défenseurs à ajouter :",
            view=AddDefendersSelectView(self.bot, self.message_id, first_id),
            ephemeral=True
        )

# ---------- View boutons du panneau ----------
class PingButtonsView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def _handle_click(self, interaction: discord.Interaction, role_id: int):
        try:
            await interaction.response.defer(ephemeral=True, thinking=False)
        except Exception:
            pass

        guild = interaction.guild
        if guild is None or ALERT_CHANNEL_ID == 0:
            return
        alert_channel = guild.get_channel(ALERT_CHANNEL_ID)
        if not isinstance(alert_channel, discord.TextChannel):
            return

        role_mention = f"<@&{role_id}>" if role_id else ""
        content = (
            f"{role_mention} — **Percepteur attaqué !** Merci de vous connecter."
            if role_mention else
            "**Percepteur attaqué !** Merci de vous connecter."
        )

        msg = await alert_channel.send(content)
        upsert_message(
            msg.id,
            msg.guild.id,
            msg.channel.id,
            int(msg.created_at.timestamp()),
            creator_id=interaction.user.id,
        )

        emb = await build_ping_embed(msg)
        try:
            await msg.edit(embed=emb)
        except Exception:
            pass

        await update_leaderboards(self.bot, guild)

        try:
            await interaction.followup.send("✅ Alerte envoyée.", ephemeral=True)
        except Exception:
            pass

    @discord.ui.button(label="Guilde 1", style=discord.ButtonStyle.primary, custom_id="pingpanel:def1")
    async def btn_def(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_click(interaction, ROLE_DEF_ID)

    @discord.ui.button(label="Guilde 2", style=discord.ButtonStyle.danger, custom_id="pingpanel:def2")
    async def btn_def2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_click(interaction, ROLE_DEF2_ID)

    @discord.ui.button(label="TEST (Admin)", style=discord.ButtonStyle.secondary, custom_id="pingpanel:test")
    async def btn_test(self, interaction: discord.Interaction, button: discord.ui.Button):
        if ADMIN_ROLE_ID and not any(r.id == ADMIN_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("Bouton réservé aux admins.", ephemeral=True)
            return
        await self._handle_click(interaction, ROLE_TEST_ID)

class AlertsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

async def setup(bot: commands.Bot):
    await bot.add_cog(AlertsCog(bot))
