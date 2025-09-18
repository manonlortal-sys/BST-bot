# ping.py
import asyncio
from datetime import datetime
from typing import Optional, Set

import discord
from discord.ext import commands
from discord import app_commands

# === CONFIG ===
ALERT_BUTTONS_CHANNEL_ID = 1358772372831994040   # panneau avec boutons
PING_TARGET_CHANNEL_ID   = 1327548733398843413   # salon où le ping/alerte part

# ⚠️ A REMPLIR : IDs des rôles @DEF et @DEF2
DEF_ROLE_ID  = 0  # ex: 123456789012345678
DEF2_ROLE_ID = 0  # ex: 987654321098765432

# Emojis écoutés
EMOJI_WIN   = "🏆"
EMOJI_LOSS  = "❌"
EMOJI_INCOMPLETE = "😡"
EMOJI_PARTICIPANT = "👍"

ALERT_MESSAGE_IDS: Set[int] = set()


def _base_alert_embed(guilde_label: str, clicker: discord.Member) -> discord.Embed:
    e = discord.Embed(
        title=f"🛡️ Alerte Défense – {guilde_label}",
        description=(
            f"⚔️ Le percepteur de **{guilde_label}** est attaqué !\n"
            f"Merci de vous connecter rapidement pour défendre."
        ),
        color=discord.Color.orange()
    )
    e.add_field(name="Ping effectué par", value=clicker.mention, inline=False)
    e.add_field(name="Résultat", value="—", inline=True)
    e.add_field(name="Participants", value="—", inline=False)
    e.set_footer(text=f"Système d’alerte • {datetime.now().strftime('%d/%m %H:%M')}")
    return e


async def _rebuild_embed_from_reactions(msg: discord.Message) -> Optional[discord.Embed]:
    """Met à jour Résultat + Participants en fonction des réactions."""
    if not msg.embeds:
        return None
    embed = msg.embeds[0]

    win = loss = incomplete = False
    participants_names = []

    for reaction in msg.reactions:
        users = [u async for u in reaction.users() if not u.bot]
        if str(reaction.emoji) == EMOJI_WIN and users:
            win = True
        elif str(reaction.emoji) == EMOJI_LOSS and users:
            loss = True
        elif str(reaction.emoji) == EMOJI_INCOMPLETE and users:
            incomplete = True
        elif str(reaction.emoji) == EMOJI_PARTICIPANT and users:
            for u in users[:12]:
                participants_names.append(u.display_name if hasattr(u, "display_name") else u.name)
            extra = max(len(users) - 12, 0)
            if extra > 0:
                participants_names.append(f"+{extra}")

    if win:
        result_text = f"{EMOJI_WIN} Défense **gagnée**"
        color = discord.Color.green()
    elif loss:
        result_text = f"{EMOJI_LOSS} Défense **perdue**"
        color = discord.Color.red()
    elif incomplete:
        result_text = f"{EMOJI_INCOMPLETE} Défense **incomplète**"
        color = discord.Color.orange()
    else:
        result_text = "—"
        color = discord.Color.orange()

    fields = list(embed.fields)
    idx_res = next((i for i, f in enumerate(fields) if f.name.lower() == "résultat"), None)
    if idx_res is None:
        embed.add_field(name="Résultat", value=result_text, inline=True)
    else:
        embed.set_field_at(idx_res, name="Résultat", value=result_text, inline=True)

    part_text = "—" if not participants_names else ", ".join(participants_names)
    idx_part = next((i for i, f in enumerate(fields) if f.name.lower() == "participants"), None)
    if idx_part is None:
        embed.add_field(name="Participants", value=part_text, inline=False)
    else:
        embed.set_field_at(idx_part, name="Participants", value=part_text, inline=False)

    embed.color = color
    embed.set_footer(text=f"Dernière mise à jour • {datetime.now().strftime('%d/%m %H:%M')}")
    return embed


class DefenseAlertView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _send_alert(self, inter: discord.Interaction, role_id: int, guilde_label: str):
        target_channel = inter.client.get_channel(PING_TARGET_CHANNEL_ID)
        if target_channel is None:
            await inter.response.send_message("❌ Salon d’alerte introuvable.", ephemeral=True)
            return

        role_mention = f"<@&{role_id}>" if role_id else "@role-invalide"
        allowed = discord.AllowedMentions(roles=True, users=False, everyone=False)

        embed = _base_alert_embed(guilde_label, inter.user)
        sent = await target_channel.send(content=f"{role_mention}", embed=embed, allowed_mentions=allowed)
        ALERT_MESSAGE_IDS.add(sent.id)

        await inter.response.send_message(f"✅ Alerte envoyée pour **{guilde_label}**.", ephemeral=True)

    @discord.ui.button(label="🔴 Guilde 1 (DEF)", style=discord.ButtonStyle.danger)
    async def g1(self, inter: discord.Interaction, _btn: discord.ui.Button):
        await self._send_alert(inter, DEF_ROLE_ID, "Guilde 1")

    @discord.ui.button(label="⚫ Guilde 2 (DEF2)", style=discord.ButtonStyle.secondary)
    async def g2(self, inter: discord.Interaction, _btn: discord.ui.Button):
        await self._send_alert(inter, DEF2_ROLE_ID, "Guilde 2")


class DefenseAlert(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="alerte", description="Poster le panneau d’alerte (DEF/DEF2).")
    async def alerte(self, inter: discord.Interaction):
        channel = inter.client.get_channel(ALERT_BUTTONS_CHANNEL_ID)
        if channel is None:
            await inter.response.send_message("❌ Canal des boutons introuvable.", ephemeral=True)
            return

        view = DefenseAlertView()
        embed = discord.Embed(
            title="🛡️ Bot de Ping – Défense",
            description=(
                "Cliquez sur la guilde qui se fait attaquer pour **alerter** les joueurs.\n"
                "❗ Ne cliquez qu’**une seule fois** par alerte.\n\n"
                f"Réagissez ensuite dans le salon d’alerte avec :\n"
                f"- {EMOJI_WIN} victoire\n"
                f"- {EMOJI_LOSS} défaite\n"
                f"- {EMOJI_INCOMPLETE} incomplète\n"
                f"- {EMOJI_PARTICIPANT} participant\n\n"
                "_Le bot mettra à jour l’embed automatiquement._"
            ),
            color=discord.Color.orange()
        )

        await inter.response.send_message("✅ Panneau envoyé.", ephemeral=True)
        await channel.send(embed=embed, view=view)

    @commands.Cog.listener("on_raw_reaction_add")
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.message_id not in ALERT_MESSAGE_IDS:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        channel = guild.get_channel(payload.channel_id)
        if channel is None:
            return
        msg = await channel.fetch_message(payload.message_id)
        new_embed = await _rebuild_embed_from_reactions(msg)
        if new_embed:
            await msg.edit(embed=new_embed)

    @commands.Cog.listener("on_raw_reaction_remove")
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        await self.on_raw_reaction_add(payload)


async def setup(bot: commands.Bot):
    await bot.add_cog(DefenseAlert(bot))
