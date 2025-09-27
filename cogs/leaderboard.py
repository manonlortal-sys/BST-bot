# cogs/leaderboard.py
import discord
from discord.ext import commands

from storage import (
    get_leaderboard_totals,
    agg_totals_all,
    agg_totals_by_team,
    hourly_split_all,
    get_aggregate,
)


async def build_leaderboard_embed(guild: discord.Guild) -> discord.Embed:
    embed = discord.Embed(
        title="📊 Leaderboard Défenses",
        color=discord.Color.gold()
    )

    # ---------- Top défenseurs ----------
    top_def = get_leaderboard_totals(guild.id, "defense", limit=10)
    desc = ""
    medals = ["🥇", "🥈", "🥉"]

    for i, (uid, count) in enumerate(top_def, start=1):
        member = guild.get_member(uid)
        name = member.display_name if member else f"<@{uid}>"
        prefix = medals[i - 1] if i <= 3 else f"{i}."
        desc += f"{prefix} {name} — {count} défenses\n"

    if not desc:
        desc = "_Aucun défenseur pour le moment._"

    embed.add_field(name="🏆 Top défenseurs", value=desc, inline=False)

    # ---------- Stats globales ----------
    wins, losses, inc, total = agg_totals_all(guild.id)
    ratio = f"{(wins / (wins + losses) * 100):.1f}%" if (wins + losses) > 0 else "0%"

    stats_globales = (
        f"📊 **Stats globales**\n"
        f"Attaques : {total}\n"
        f"Victoires : {wins}\n"
        f"Défaites : {losses}\n"
        f"Incomplètes : {inc}\n"
        f"Ratio : {ratio}"
    )
    embed.add_field(name="\u200b", value=stats_globales, inline=False)

    # ---------- Stats Guilde 1 ----------
    w1, l1, inc1, tot1 = agg_totals_by_team(guild.id, 1)
    ratio1 = f"{(w1 / (w1 + l1) * 100):.1f}%" if (w1 + l1) > 0 else "0%"

    stats_g1 = (
        f"📊 **Stats Guilde 1**\n"
        f"Attaques : {tot1}\n"
        f"Victoires : {w1}\n"
        f"Défaites : {l1}\n"
        f"Incomplètes : {inc1}\n"
        f"Ratio : {ratio1}"
    )
    embed.add_field(name="\u200b", value=stats_g1, inline=False)

    # ---------- Stats Guilde 2 ----------
    w2, l2, inc2, tot2 = agg_totals_by_team(guild.id, 2)
    ratio2 = f"{(w2 / (w2 + l2) * 100):.1f}%" if (w2 + l2) > 0 else "0%"

    stats_g2 = (
        f"📊 **Stats Guilde 2**\n"
        f"Attaques : {tot2}\n"
        f"Victoires : {w2}\n"
        f"Défaites : {l2}\n"
        f"Incomplètes : {inc2}\n"
        f"Ratio : {ratio2}"
    )
    embed.add_field(name="\u200b", value=stats_g2, inline=False)

    # ---------- Répartition horaire ----------
    morning, afternoon, evening, night = hourly_split_all(guild.id)
    repartition = (
        f"🕒 **Répartition horaire**\n"
        f"🌅 Matin : {morning}\n"
        f"☀️ Après-midi : {afternoon}\n"
        f"🌆 Soir : {evening}\n"
        f"🌙 Nuit : {night}"
    )
    embed.add_field(name="\u200b", value=repartition, inline=False)

    # ---------- Attaques incomplètes ----------
    incomplete_total = get_aggregate(guild.id, "global", "incomplete")
    inc_morning = get_aggregate(guild.id, "hourly", "morning_inc")
    inc_afternoon = get_aggregate(guild.id, "hourly", "afternoon_inc")
    inc_evening = get_aggregate(guild.id, "hourly", "evening_inc")
    inc_night = get_aggregate(guild.id, "hourly", "night_inc")

    inc_stats = f"⚠️ **Attaques incomplètes**\nTotal : {incomplete_total}"
    embed.add_field(name="\u200b", value=inc_stats, inline=False)

    repartition_inc = (
        f"🕒 **Répartition horaire (attaques incomplètes)**\n"
        f"🌅 Matin : {inc_morning}\n"
        f"☀️ Après-midi : {inc_afternoon}\n"
        f"🌆 Soir : {inc_evening}\n"
        f"🌙 Nuit : {inc_night}"
    )
    embed.add_field(name="\u200b", value=repartition_inc, inline=False)

    return embed


async def update_leaderboards(bot: commands.Bot, guild: discord.Guild):
    from storage import get_leaderboard_post, set_leaderboard_post

    embed = await build_leaderboard_embed(guild)

    for type_ in ["defense"]:
        post = get_leaderboard_post(guild.id, type_)
        if post:
            channel = guild.get_channel(post[0])
            if not channel:
                continue
            try:
                msg = await channel.fetch_message(post[1])
                await msg.edit(embed=embed)
            except Exception:
                continue
        else:
            # Pas encore de leaderboard → on en crée un
            channel = discord.utils.get(guild.text_channels, name="leaderboard")
            if channel:
                msg = await channel.send(embed=embed)
                set_leaderboard_post(guild.id, channel.id, msg.id, type_)


class LeaderboardCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            try:
                await update_leaderboards(self.bot, guild)
            except Exception:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(LeaderboardCog(bot))
