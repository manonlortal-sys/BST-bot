import discord

def embed_players(players):
    embed = discord.Embed(title="Joueurs inscrits")

    if not players:
        embed.description = "Aucun joueur"
        return embed

    lines = []
    for p in players:
        cls = p.cls if p.cls else "❌"
        lines.append(f"<@{p.user_id}> — {cls}")

    embed.description = "\n".join(lines)
    return embed


def embed_teams(teams):
    embed = discord.Embed(title="Équipes")

    if not teams:
        embed.description = "Aucune équipe"
        return embed

    lines = []

    for t in teams:
        players_txt = []
        for p in t.players:
            players_txt.append(f"<@{p.user_id}> ({p.cls})")

        lines.append(f"**EQUIPE {t.id}**\n" + "\n".join(players_txt))

    embed.description = "\n\n".join(lines)
    return embed
