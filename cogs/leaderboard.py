# cogs/leaderboard.py
import os
import discord
from discord.ext import commands

from storage import (
    get_leaderboard_post,
    set_leaderboard_post,
    get_leaderboard_totals,
    agg_totals_all,
    agg_totals_by_team,
    hourly_split_all,
    get_attack_incomplete_total,
    hourly_split_attack_incomplete,
)

LEADERBOARD_CHANNEL_ID = int(os.getenv("LEADERBOARD_CHANNEL_ID", "0"))
SEPARATOR = "────────────────────────────"

def _build_defense_embed(guild: discord.Guild) -> discord.Embed:
    embed = discord.Embed(title="📊 Leaderboard Défense", color=discord.Color.blue())

    # ---------- 🏆 Top défenseurs ----------
    top_def = get_leaderboard_totals(guild.id, "defense")
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, (uid, cnt) in enumerate(top_def, start=1):
        member = guild.get_member(uid)
        name = member.display_name if member else f"<@{uid}>"
        prefix = medals[i - 1] if i <= 3 else f"{i}."
        lines.append(f"{prefix} {name} — {cnt} défenses")
    top_block = "\n".join(lines) if lines else "_Aucun défenseur pour le moment._"
    embed.add_field(name="🏆 Top défenseurs", value=top_block, inline=False)

    embed.add_field(name="\u200b", value=SEPARATOR, inline=False)

    # ---------- 📊 Stats globales ----------
    w, l, inc, tot = agg_totals_all(guild.id)
    ratio = f"{(w/(w+l)*100):.1f}%" if (w + l) else "0%"
    stats_globales = "\n".join([
        f"⚔️ Attaques : {tot}",
        f"🏆 Victoires : {w}",
        f"❌ Défaites : {l}",
        f"😡 Défenses incomplètes : {inc}",
        f"📈 Ratio : {ratio}",
    ])
    embed.add_field(name="📊 Stats globales", value=stats_globales or "\u200b", inline=False)

    embed.add_field(name="\u200b", value=SEPARATOR, inline=False)

    # ---------- 📊 Stats Guilde 1 ----------
    w1, l1, inc1, tot1 = agg_totals_by_team(guild.id, 1)
    ratio1 = f"{(w1/(w1+l1)*100):.1f}%" if (w1 + l1) else "0%"
    stats_g1 = "\n".join([
        f"⚔️ Attaques : {tot1}",
        f"🏆 Victoires : {w1}",
        f"❌ Défaites : {l1}",
        f"😡 Défenses incomplètes : {inc1}",
        f"📈 Ratio : {ratio1}",
    ])
    embed.add_field(name="📊 Stats Guilde 1", value=stats_g1 or "\u200b", inline=False)

    embed.add_field(name="\u200b", value=SEPARATOR, inline=False)

    # ---------- 📊 Stats Guilde 2 ----------
    w2, l2, inc2, tot2 = agg_totals_by_team(guild.id, 2)
    ratio2 = f"{(w2/(w2+l2)*100):.1f}%" if (w2 + l2) else "0%"
    stats_g2 = "\n".join([
        f"⚔️ Attaques : {tot2}",
        f"🏆 Victoires : {w2}",
        f"❌ Défaites : {l2}",
        f"😡 Défenses incomplètes : {inc2}",
        f"📈 Ratio : {ratio2}",
    ])
    embed.add_field(name="📊 Stats Guilde 2", value=stats_g2 or "\u200b", inline=False)

    embed.add_field(name="\u200b", value=SEPARATOR, inline=False)

    # ---------- 🕒 Répartition horaire ----------
    m, d, e, n = hourly_split_all(guild.id)
    hourly_block = "\n".join([
        f"🌅 Matin : {m}",
        f"🌞 Journée : {d}",
        f"🌆 Soir : {e}",
        f"🌙 Nuit : {n}",
    ])
    embed.add_field(name="🕒 Répartition horaire", value=hourly_block or "\u200b", inline=False)

    embed.add_field(name="\u200b", value=SEPARATOR, inline=False)

    # ---------- ⚠️ Attaques incomplètes ----------
    inc_total = get_attack_incomplete_total(guild.id)
    embed.add_field(name="⚠️ Attaques incomplètes", value=f"🚫 Total : {inc_total}", inline=False)

    embed.add_field(name="\u200b", value=SEPARATOR, inline=False)

    im, id_, ie, in_ = hourly_split_attack_incomplete(guild.id)
    inc_hourly_block = "\n".join([
        f"🌅 Matin : {im}",
        f"🌞 Journée : {id_}",
        f"🌆 Soir : {ie}",
        f"🌙 Nuit : {in_}",
    ])
    embed.add_field(name="🕒 Répartition horaire (attaques incomplètes)", value=inc_hourly_block or "\u200b", inline=False)

    return embed

def _build_pingeurs_embed(guild: discord.Guild) -> discord.Embed:
    embed = discord.Embed(title="📣 Leaderboard Pingeurs", color=discord.Color.gold())
    top_ping = get_leaderboard_totals(guild.id, "pingeur")
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, (uid, cnt) in enumerate(top_ping, start=1):
        member = guild.get_member(uid)
        name = member.display_name if member else f"<@{uid}>"
        prefix = medals[i-1] if i <= 3 else f"{i}."
        lines.append(f"{prefix} {name} — {cnt} pings")
    block = "\n".join(lines) if lines else "_Aucun pingeur encore_"
    embed.add_field(name="Top pingeurs", value=block, inline=False)
    return embed

async def update_leaderboards(bot: commands.Bot, guild: discord.Guild):
    """Fonction appelée par alerts/reactions après chaque changement."""
    channel = bot.get_channel(LEADERBOARD_CHANNEL_ID)
    if channel is None:
        return

    # ---------- Défense ----------
    post = get_leaderboard_post(guild.id, "defense")
    if post:
        try:
            msg_def = await channel.fetch_message(post[1])
        except discord.NotFound:
            msg_def = await channel.send("📊 **Leaderboard Défense**")
            set_leaderboard_post(guild.id, channel.id, msg_def.id, "defense")
    else:
        msg_def = await channel.send("📊 **Leaderboard Défense**")
        set_leaderboard_post(guild.id, channel.id, msg_def.id, "defense")
    await msg_def.edit(embed=_build_defense_embed(guild))

    # ---------- Pingeurs ----------
    post_p = get_leaderboard_post(guild.id, "pingeur")
    if post_p:
        try:
            msg_ping = await channel.fetch_message(post_p[1])
        except discord.NotFound:
            msg_ping = await channel.send("📊 **Leaderboard Pingeurs**")
            set_leaderboard_post(guild.id, channel.id, msg_ping.id, "pingeur")
    else:
        msg_ping = await channel.send("📊 **Leaderboard Pingeurs**")
        set_leaderboard_post(guild.id, channel.id, msg_ping.id, "pingeur")
    await msg_ping.edit(embed=_build_pingeurs_embed(guild))

class LeaderboardCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        # Initialise/rafraîchit au démarrage
        for g in self.bot.guilds:
            try:
                await update_leaderboards(self.bot, g)
            except Exception:
                pass

async def setup(bot: commands.Bot):
    await bot.add_cog(LeaderboardCog(bot))
