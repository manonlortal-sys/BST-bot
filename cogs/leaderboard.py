# cogs/leaderboard.py
import os
import discord
from discord.ext import commands

from storage import (
    get_leaderboard_post,
    set_leaderboard_post,
    get_leaderboard_totals,
    agg_totals_all,
    hourly_split_all,
    get_attack_incomplete_total,
    hourly_split_attack_incomplete,
)

LEADERBOARD_CHANNEL_ID = int(os.getenv("LEADERBOARD_CHANNEL_ID", "0"))

class LeaderboardCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

async def update_leaderboards(bot: commands.Bot, guild: discord.Guild):
    channel = bot.get_channel(LEADERBOARD_CHANNEL_ID)
    if channel is None:
        return

    # ---- Défense leaderboard post ----
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

    # Top défenseurs
    top_def = get_leaderboard_totals(guild.id, "defense")
    top_lines = []
    medals = ["🥇", "🥈", "🥉"]
    for i, (uid, cnt) in enumerate(top_def):
        medal = medals[i] if i < len(medals) else "•"
        top_lines.append(f"{medal} <@{uid}> — {cnt}")
    top_block = "\n".join(top_lines) if top_lines else "_Aucun défenseur encore_"

    # Stats globales
    total_w, total_l, total_inc_def, total_att = agg_totals_all(guild.id)
    ratio = f"{(total_w/total_att*100):.1f}%" if total_att else "0%"

    # Répartition horaire (toutes défenses)
    m,d,e,n = hourly_split_all(guild.id)

    # Attaques incomplètes
    inc_att_total = get_attack_incomplete_total(guild.id)
    im,id_,ie,in_ = hourly_split_attack_incomplete(guild.id)

    # Construction embed
    embed_def = discord.Embed(title="📊 Leaderboard Défense", color=discord.Color.blue())

    embed_def.add_field(name="🥇 **Top défenseurs**", value=top_block or "\u200b", inline=False)

    # espace
    embed_def.add_field(name="\u200b", value="\u200b", inline=False)

    stats_block = "\n".join([
        f"⚔️ Attaques : {total_att}",
        f"🏆 Victoires : {total_w}",
        f"❌ Défaites : {total_l}",
        f"😡 Défenses incomplètes : {total_inc_def}",
        f"📈 Ratio victoire : {ratio}",
    ])
    embed_def.add_field(name="📊 **Stats globales**", value=stats_block or "\u200b", inline=False)

    # espace
    embed_def.add_field(name="\u200b", value="\u200b", inline=False)

    hourly_block = f"🌅 Matin : {m} · 🌞 Journée : {d} · 🌆 Soir : {e} · 🌙 Nuit : {n}"
    embed_def.add_field(name="🕒 **Répartition horaire (toutes défenses)**", value=hourly_block or "\u200b", inline=False)

    # espace
    embed_def.add_field(name="\u200b", value="\u200b", inline=False)

    inc_total_block = f"Total : {inc_att_total}"
    embed_def.add_field(name="⚠️ **Attaques incomplètes**", value=inc_total_block or "\u200b", inline=False)

    # espace
    embed_def.add_field(name="\u200b", value="\u200b", inline=False)

    inc_hourly_block = f"🌅 Matin : {im} · 🌞 Journée : {id_} · 🌆 Soir : {ie} · 🌙 Nuit : {in_}"
    embed_def.add_field(name="🕒 **Répartition horaire (attaques incomplètes)**", value=inc_hourly_block or "\u200b", inline=False)

    await msg_def.edit(embed=embed_def)

async def setup(bot: commands.Bot):
    await bot.add_cog(LeaderboardCog(bot))
