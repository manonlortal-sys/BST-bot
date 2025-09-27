# cogs/alerts.py
import os
from typing import List, Optional
import discord
from discord.ext import commands
from discord import app_commands

from storage import (
    upsert_message,
    incr_leaderboard,
    get_message_creator,
    get_participants_detailed,
    get_first_defender,
    add_participant,
    is_attack_incomplete,
    set_attack_incomplete,
)
from .leaderboard import update_leaderboards

# ---------- ENV ----------
ALERT_CHANNEL_ID = int(os.getenv("ALERT_CHANNEL_ID", "0"))
ROLE_DEF_ID      = int(os.getenv("ROLE_DEF_ID", "0"))
ROLE_DEF2_ID     = int(os.getenv("ROLE_DEF2_ID", "0"))
ROLE_TEST_ID     = int(os.getenv("ROLE_TEST_ID", "0"))
ADMIN_ROLE_ID    = int(os.getenv("ADMIN_ROLE_ID", "0"))

# ---------- Emojis ----------
EMOJI_VICTORY = "🏆"
EMOJI_DEFEAT  = "❌"
EMOJI_INCOMP  = "😡"  # défense incomplète (côté défense)
EMOJI_JOIN    = "👍"

# ---------- Embed constructeur ----------
async def build_ping_embed(msg: discord.Message) -> discord.Embed:
    creator_id: Optional[int] = get_message_creator(msg.id)
    creator_member = msg.guild.get_member(creator_id) if creator_id else None

    parts = get_participants_detailed(msg.id)  # [(user_id, added_by, ts)]
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

    reactions = {str(r.emoji): r for r in msg.reactions}
    win        = EMOJI_VICTORY in reactions and reactions[EMOJI_VICTORY].count > 0
    loss       = EMOJI_DEFEAT  in reactions and reactions[EMOJI_DEFEAT].count  > 0
    incomplete_def = EMOJI_INCOMP in reactions and reactions[EMOJI_INCOMP].count > 0  # défense incomplète

    if win and not loss:
        color = discord.Color.green()
        etat = f"{EMOJI_VICTORY} **Défense gagnée**"
    elif loss and not win:
        color = discord.Color.red()
        etat = f"{EMOJI_DEFEAT} **Défense perdue**"
    else:
        color = discord.Color.orange()
        etat = "⏳ **En cours**"

    # Lignes additionnelles d'état
    if incomplete_def:
        etat += f"\n{EMOJI_INCOMP} Défense incomplète"

    if is_attack_incomplete(msg.id):
        etat += f"\n⚠️ Les attaquants n’étaient pas 4 !"

    embed = discord.Embed(
        title="🛡️ Alerte Attaque Percepteur",
        description="⚠️ **Connectez-vous pour prendre la défense !**",
        color=color,
    )
    if creator_member:
        embed.add_field(name="⚡ Déclenché par", value=creator_member.display_name, inline=False)
    embed.add_field(name="État du combat", value=etat, inline=False)
    embed.add_field(name="\u200b", value="\u200b", inline=False)  # séparation visuelle
    embed.add_field(name="Défenseurs (👍 ou ajout via bouton)", value=defenders_block, inline=False)
    embed.set_footer(text="Réagissez : 🏆 gagné • ❌ perdu • 😡 incomplète • 👍 j'ai participé")
    return embed

# ---------- Views ----------
class AddDefendersSelectView(discord.ui.View):
    def __init__(self, bot: commands.Bot, message_id: int, claimer_id: int):
        super().__init__(timeout=120)
        self.bot = bot
        self.message_id = message_id
        self.claimer_id = claimer_id
        self.selected_users: List[discord.Member] = []

    @discord.ui.select(
        cls=discord.ui.UserSelect,
        min_values=1,
        max_values=3,
        placeholder="Sélectionne jusqu'à 3 défenseurs",
    )
    async def user_select(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        self.selected_users = select.values
        await interaction.response.defer(ephemeral=True)

    @discord.ui.button(label="Confirmer l'ajout", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)

        if interaction.user.id != self.claimer_id:
            await interaction.followup.send("Action réservée au premier défenseur.", ephemeral=True)
            return

        if not self.selected_users:
            await interaction.followup.send("Sélection vide.", ephemeral=True)
            return

        guild = interaction.guild
        channel = guild.get_channel(interaction.channel_id) or guild.get_thread(interaction.channel_id)
        if channel is None:
            await interaction.followup.send("Impossible de retrouver le message d'alerte.", ephemeral=True)
            return

        msg = await channel.fetch_message(self.message_id)

        added_any = False
        for member in self.selected_users:
            inserted = add_participant(self.message_id, member.id, self.claimer_id, "button")
            if inserted:
                added_any = True
                incr_leaderboard(guild.id, "defense", member.id)

        if added_any:
            emb = await build_ping_embed(msg)
            try:
                await msg.edit(embed=emb, view=AddDefendersButtonView(self.bot, self.message_id))
            except Exception:
                pass
            try:
                await update_leaderboards(self.bot, guild)
            except Exception:
                pass

        await interaction.followup.send("✅ Ajout effectué.", ephemeral=True)
        self.stop()

class AddDefendersButtonView(discord.ui.View):
    def __init__(self, bot: commands.Bot, message_id: int, *, disable_attack_btn: bool = False):
        super().__init__(timeout=7200)  # 2h
        self.bot = bot
        self.message_id = message_id
        self.disable_attack_btn = disable_attack_btn

    @discord.ui.button(label="Ajouter défenseurs", style=discord.ButtonStyle.primary, emoji="🛡️", custom_id="add_defenders")
    async def add_defenders(self, interaction: discord.Interaction, button: discord.ui.Button):
        first_id = get_first_defender(self.message_id)
        if first_id is None or interaction.user.id != first_id:
            await interaction.response.send_message("Bouton réservé au premier défenseur (premier 👍).", ephemeral=True)
            return
        await interaction.response.send_message(
            "Sélectionne jusqu'à 3 défenseurs à ajouter :",
            view=AddDefendersSelectView(self.bot, self.message_id, first_id),
            ephemeral=True
        )

    @discord.ui.button(label="Attaque incomplète", style=discord.ButtonStyle.secondary, emoji="⚠️", custom_id="mark_attack_incomplete")
    async def mark_attack_incomplete(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Si déjà marqué, prévenir
        if is_attack_incomplete(self.message_id):
            await interaction.response.send_message("Déjà marqué comme **attaque incomplète**.", ephemeral=True)
            return

        # Marquer en DB
        set_attack_incomplete(self.message_id, True)

        # Mettre à jour l'embed + désactiver le bouton
        guild = interaction.guild
        channel = guild.get_channel(interaction.channel_id) or guild.get_thread(interaction.channel_id)
        if channel is None:
            await interaction.response.send_message("Impossible de retrouver le message d'alerte.", ephemeral=True)
            return

        msg = await channel.fetch_message(self.message_id)

        # Rebuild embed
        emb = await build_ping_embed(msg)

        # Redéployer la view avec le bouton ⚠️ désactivé
        new_view = AddDefendersButtonView(self.bot, self.message_id, disable_attack_btn=True)
        for item in new_view.children:
            if isinstance(item, discord.ui.Button) and item.custom_id == "mark_attack_incomplete":
                item.disabled = True
                item.label = "Attaque incomplète (marquée)"
                break

        try:
            await msg.edit(embed=emb, view=new_view)
        except Exception:
            pass

        # Rafraîchir leaderboard
        try:
            await update_leaderboards(self.bot, guild)
        except Exception:
            pass

        await interaction.response.send_message("⚠️ Attaque marquée **incomplète**.", ephemeral=True)

class PingButtonsView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)  # persistante (ré-enregistrée au boot)
        self.bot = bot

    async def _handle_click(self, interaction: discord.Interaction, role_id: int, team: Optional[int]):
        try:
            await interaction.response.defer(ephemeral=True, thinking=False)
        except Exception:
            pass

        guild = interaction.guild
        if guild is None or ALERT_CHANNEL_ID == 0:
            return

        alert_channel = guild.get_channel(ALERT_CHANNEL_ID) or guild.get_thread(ALERT_CHANNEL_ID)
        if alert_channel is None:
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
            team=team,
        )
        try:
            incr_leaderboard(guild.id, "pingeur", interaction.user.id)
        except Exception:
            pass

        emb = await build_ping_embed(msg)
        try:
            # au départ, on n’attache pas la view des défenseurs ; elle sera attachée
            # par le cog reactions après le premier 👍 (comme avant)
            await msg.edit(embed=emb)
        except Exception:
            pass

        await update_leaderboards(self.bot, guild)

        try:
            await interaction.followup.send("✅ Alerte envoyée.", ephemeral=True)
        except Exception:
            pass

    @discord.ui.button(label="Guilde 1", style=discord.ButtonStyle.primary, emoji="🛡️", custom_id="pingpanel:def1")
    async def btn_def(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_click(interaction, ROLE_DEF_ID, team=1)

    @discord.ui.button(label="Guilde 2", style=discord.ButtonStyle.danger, emoji="🛡️", custom_id="pingpanel:def2")
    async def btn_def2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_click(interaction, ROLE_DEF2_ID, team=2)

    @discord.ui.button(label="TEST (Admin)", style=discord.ButtonStyle.secondary, custom_id="pingpanel:test")
    async def btn_test(self, interaction: discord.Interaction, button: discord.ui.Button):
        if ADMIN_ROLE_ID and not any(r.id == ADMIN_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("Bouton réservé aux admins.", ephemeral=True)
            return
        await self._handle_click(interaction, ROLE_TEST_ID, team=0)

class AlertsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="pingpanel", description="Publier le panneau d’alerte percepteur")
    async def pingpanel(self, interaction: discord.Interaction):
        # Déférer d'abord (évite Unknown interaction 10062)
        try:
            await interaction.response.defer(ephemeral=False, thinking=False)
        except Exception:
            pass

        # Embed panneau
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

        await interaction.followup.send(
            embed=embed,
            view=PingButtonsView(self.bot),
            ephemeral=False
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(AlertsCog(bot))
