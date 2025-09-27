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

SEPARATOR = "────────────────────────────"

class LeaderboardCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _build_defense_embed(self, guild: discord.Guild) -> discord.Embed:
        embed = discord.Embed(
            title="📊 Leaderboard Défenses",
            color=discord.Color.blurple(),
        )

        # 🏆 Top défenseurs
        top_def = get_leaderboard_totals(guild.id, "defense", limit=10)
        if top_def:
            desc = []
            medals = ["🥇", "🥈", "🥉"]
            for i, (uid, count) in enumerate(top_def, start=1):
                member = guild.get_member(uid)
                name = member.display_name if member else f"<@{uid}>"
                prefix = medals[i - 1] if i <= 3 else f"{i}."
                desc.append(f"{prefix} {name} — {count} défenses")
            embed.add_field(name="🏆 Top défenseurs", value="\n".join(desc), inline=False)

        embed.add_field(name="\u200b", value=SEPARATOR, inline=False)

        # 📊 Stats globales
        w, l, inc, total = agg_totals_all(guild.id)
        ratio = f"{(w / (w + l) * 100):.1f}%" if (w + l) else "0%"
        global_stats = [
            f"⚔️ Attaques : {total}",
            f"🏆 Victoires : {w}",
            f"❌ Défaites : {l}",
            f"😡 Défenses incomplètes : {inc}",
            f"📈 Ratio : {ratio}",
        ]
        embed.add_field(name="📊 Stats globales", value="\n".join(global_stats), inline=False)

        embed.add_field(name="\u200b", value=SEPARATOR, inline=False)

        # 📊 Stats Guilde 1
        w1, l1, inc1, tot1 = agg_totals_by_team(guild.id, 1)
        ratio1 = f"{(w1 / (w1 + l1) * 100):.1f}%" if (w1 + l1) else "0%"
        team1_stats = [
            f"⚔️ Attaques : {tot1}",
            f"🏆 Victoires : {w1}",
            f"❌ Défaites : {l1}",
            f"😡 Défenses incomplètes : {inc1}",
            f"📈 Ratio : {ratio1}",
        ]
        embed.add_field(name="📊 Stats Guilde 1", value="\n".join(team1_stats), inline=False)

        embed.add_field(name="\u200b", value=SEPARATOR, inline=False)

        # 📊 Stats Guilde 2
        w2, l2, inc2, tot2 = agg_totals_by_team(guild.id, 2)
        ratio2 = f"{(w2 / (w2 + l2) * 100):.1f}%" if (w2 + l2) else "0%"
        team2_stats = [
            f"⚔️ Attaques : {tot2}",
            f"🏆 Victoires : {w2}",
            f"❌ Défaites : {l2}",
            f"😡 Défenses incomplètes : {inc2}",
            f"📈 Ratio : {ratio2}",
        ]
        embed.add_field(name="📊 Stats Guilde 2", value="\n".join(team2_stats), inline=False)

        embed.add_field(name="\u200b", value=SEPARATOR, inline=False)

        # 🕒 Répartition horaire
        morning, afternoon, evening, night = hourly_split_all(guild.id)
        hourly_stats = [
            f"🌅 Matin : {morning}",
            f"🌞 Après-midi : {afternoon}",
            f"🌙 Soir : {evening}",
            f"🌌 Nuit : {night}",
        ]
        embed.add_field(name="🕒 Répartition horaire", value="\n".join(hourly_stats), inline=False)

        embed.add_field(name="\u200b", value=SEPARATOR, inline=False)

        # ⚠️ Attaques incomplètes
        inc_total = get_aggregate(guild.id, "global", "attacks_incomplete")
        inc_morning = get_aggregate(guild.id, "hourly", "inc_morning")
        inc_afternoon = get_aggregate(guild.id, "hourly", "inc_afternoon")
        inc_evening = get_aggregate(guild.id, "hourly", "inc_evening")
        inc_night = get_aggregate(guild.id, "hourly", "inc_night")

        attack_incomp_stats = [
            f"🚫 Total : {inc_total}",
            f"🌅 Matin : {inc_morning}",
            f"🌞 Après-midi : {inc_afternoon}",
            f"🌙 Soir : {inc_evening}",
            f"🌌 Nuit : {inc_night}",
        ]
        embed.add_field(name="⚠️ Attaques incomplètes", value="\n".join(attack_incomp_stats), inline=False)

        return embed

async def setup(bot: commands.Bot):
    await bot.add_cog(LeaderboardCog(bot))
