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
    incomplete_attacks_count,   # NEW
    hourly_split_incomplete,    # NEW
)

LEADERBOARD_CHANNEL_ID = int(os.getenv("LEADERBOARD_CHANNEL_ID", "0"))

# Ligne visuelle séparatrice
SEP_LINE = "━━━━━━━━━━━━━━━━━━━━"

def medals_top_defenders(top: list[tuple[int, int]]) -> str:
    lines = []
    for i, (uid, cnt) in enumerate(top):
        if i == 0:
            lines.append(f"🥇 <@{uid}> : {cnt} défenses")
        elif i == 1:
            lines.append(f"🥈 <@{uid}> : {cnt} défenses")
        elif i == 2:
            lines.append(f"🥉 <@{uid}> : {cnt} défenses")
        else:
            lines.append(f"• <@{uid}> : {cnt} défenses")
    return "\n".join(lines) if lines else "_Aucun défenseur encore_"

def fmt_stats_block(att: int, w: int, l: int, inc: int) -> str:
    ratio = f"{(w/att*100):.1f}%" if att else "0%"
    return (
        f"⚔️ Attaques : {att}\n"
        f"🏆 Victoires : {w}\n"
        f"❌ Défaites : {l}\n"
        f"😡 Incomplet : {inc}\n"
        f"📊 Ratio victoire : {ratio}"
    )

def fmt_hourly_block(buckets: tuple[int, int, int, int], total: int) -> str:
    m, a, s, n = buckets
    def pct(x: int) -> str:
        return f"{(x/total*100):.1f}%" if total else "0%"
    return (
        f"🌅 Matin : {m} ({pct(m)})\n"
        f"🌞 Après-midi : {a} ({pct(a)})\n"
        f"🌙 Soir : {s} ({pct(s)})\n"
        f"🌌 Nuit : {n} ({pct(n)})"
    )

async def update_leaderboards(bot: commands.Bot, guild: discord.Guild):
    if not LEADERBOARD_CHANNEL_ID:
        return
    channel = bot.get_channel(LEADERBOARD_CHANNEL_ID)
    if channel is None or not isinstance(channel, discord.TextChannel):
        return

    # ---------- Leaderboard Défense ----------
    def_post = get_leaderboard_post(guild.id, "defense")
    if def_post:
        try:
            msg_def = await channel.fetch_message(def_post[1])
        except discord.NotFound:
            msg_def = await channel.send("📊 **Leaderboard Défense**")
            set_leaderboard_post(guild.id, channel.id, msg_def.id, "defense")
    else:
        msg_def = await channel.send("📊 **Leaderboard Défense**")
        set_leaderboard_post(guild.id, channel.id, msg_def.id, "defense")

    top_def = get_leaderboard_totals(guild.id, "defense")
    top_block = medals_top_defenders(top_def)

    w_all, l_all, inc_all, att_all = agg_totals_all(guild.id)
    w_g1, l_g1, inc_g1, att_g1 = agg_totals_by_team(guild.id, 1)
    w_g2, l_g2, inc_g2, att_g2 = agg_totals_by_team(guild.id, 2)
    buckets_all = hourly_split_all(guild.id)

    # NEW: attaques incomplètes (total + répartition horaire)
    inc_attacks_total = incomplete_attacks_count(guild.id)
    buckets_inc = hourly_split_incomplete(guild.id)

    embed_def = discord.Embed(title="📊 Leaderboard Défense", color=discord.Color.blue())

    # 🏆 Top défenseurs
    embed_def.add_field(name="**🏆 Top défenseurs**", value=top_block, inline=False)
    embed_def.add_field(name="\u200b", value=SEP_LINE, inline=False)

    # 📌 Stats globales
    embed_def.add_field(name="**📌 Stats globales**", value=fmt_stats_block(att_all, w_all, l_all, inc_all), inline=False)
    embed_def.add_field(name="\u200b", value="\n"+SEP_LINE, inline=False)

    # ⚠️ Attaques incomplètes
    # (même tranches/emoji que les attaques globales)
    inc_block = f"Total : {inc_attacks_total}\n\n" + fmt_hourly_block(buckets_inc, inc_attacks_total)
    embed_def.add_field(name="**⚠️ Attaques incomplètes**", value=inc_block, inline=False)
    embed_def.add_field(name="\u200b", value="\n"+SEP_LINE, inline=False)

    # 📌 Stats par guilde
    embed_def.add_field(name="**📌 Stats Guilde 1**", value=fmt_stats_block(att_g1, w_g1, l_g1, inc_g1), inline=False)
    embed_def.add_field(name="\u200b", value="\n"+SEP_LINE, inline=False)
    embed_def.add_field(name="**📌 Stats Guilde 2**", value=fmt_stats_block(att_g2, w_g2, l_g2, inc_g2), inline=False)

    # 🕒 Répartition horaire globale (toutes attaques)
    embed_def.add_field(name="\u200b", value="\n"+SEP_LINE, inline=False)
    embed_def.add_field(name="**🕒 Répartition horaire**", value=fmt_hourly_block(buckets_all, att_all), inline=False)

    await msg_def.edit(embed=embed_def)

    # ---------- Leaderboard Pingeurs ----------
    ping_post = get_leaderboard_post(guild.id, "pingeur")
    if ping_post:
        try:
            msg_ping = await channel.fetch_message(ping_post[1])
        except discord.NotFound:
            msg_ping = await channel.send("📊 **Leaderboard Pingeurs**")
            set_leaderboard_post(guild.id, channel.id, msg_ping.id, "pingeur")
    else:
        msg_ping = await channel.send("📊 **Leaderboard Pingeurs**")
        set_leaderboard_post(guild.id, channel.id, msg_ping.id, "pingeur")

    top_ping = get_leaderboard_totals(guild.id, "pingeur")
    ping_lines = []
    for i, (uid, cnt) in enumerate(top_ping):
        if i == 0:
            ping_lines.append(f"🥇 <@{uid}> : {cnt} pings")
        elif i == 1:
            ping_lines.append(f"🥈 <@{uid}> : {cnt} pings")
        elif i == 2:
            ping_lines.append(f"🥉 <@{uid}> : {cnt} pings")
        else:
            ping_lines.append(f"• <@{uid}> : {cnt} pings")
    ping_block = "\n".join(ping_lines) if ping_lines else "_Aucun pingeur encore_"

    embed_ping = discord.Embed(title="📊 Leaderboard Pingeurs", color=discord.Color.gold())
    embed_ping.add_field(name="**🏅 Top pingeurs**", value=ping_block, inline=False)
    await msg_ping.edit(embed=embed_ping)


class LeaderboardCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

async def setup(bot: commands.Bot):
    await bot.add_cog(LeaderboardCog(bot))
