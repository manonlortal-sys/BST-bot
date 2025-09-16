import discord
from discord.ext import commands
from datetime import datetime, timedelta
from collections import defaultdict
from flask import Flask
from threading import Thread
import pytz
from zoneinfo import ZoneInfo
from collections import defaultdict
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import io

CHANNEL_ID = 1327548733398843413

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.reactions = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)
occurences = defaultdict(int)

# --- Détection des messages de défense ---
def message_mentionne_def(message):
    def_roles = ["Def", "Def2"]
    for role in message.role_mentions:
        if role.name in def_roles:
            return True
    for embed in message.embeds:
        if embed.description and ("@def" in embed.description.lower() or "@def2" in embed.description.lower()):
            return True
        if embed.title and ("@def" in embed.title.lower() or "@def2" in embed.title.lower()):
            return True
    if "@def" in message.content.lower() or "@def2" in message.content.lower():
        return True
    if message.author.bot:
        if "@def" in message.content.lower() or "@def2" in message.content.lower():
            return True
        for embed in message.embeds:
            if embed.description and ("@def" in embed.description.lower() or "@def2" in embed.description.lower()):
                return True
            if embed.title and ("@def" in embed.title.lower() or "@def2" in embed.title.lower()):
                return True
    return False

@bot.command()
async def defstats(ctx):
    now = datetime.now(ZoneInfo("Europe/Paris"))
    one_week_ago = now - timedelta(days=7)
    channel = bot.get_channel(CHANNEL_ID)

    victory_emoji = "🏆"
    defeat_emoji = "❌"
    rage_emoji = "😡"
    thumbsup_emoji = "👍"

    victory_count = 0
    defeat_count = 0
    rage_count = 0
    checked_messages = 0
    def1_count = 0
    def2_count = 0
    simultaneous_count = 0
    thumbsup_stats = defaultdict(lambda: {"count": 0, "name": ""})
    attaque_par_alliance = defaultdict(int)
    alliances = ["La Bande", "Ateam", "Intmi", "Clan Oshimo", "Ivory", "La Secte", "Gueux randoms"]

    last_ping_time = None

    async for message in channel.history(limit=None, after=one_week_ago, oldest_first=True):
        if message.author != bot.user and message_mentionne_def(message):
            if last_ping_time and (message.created_at - last_ping_time).total_seconds() < 15:
                continue
            last_ping_time = message.created_at

            mentions_def1 = any(role.name.lower() == "def" for role in message.role_mentions)
            mentions_def2 = any(role.name.lower() == "def2" for role in message.role_mentions)

            for embed in message.embeds:
                if embed.description:
                    desc = embed.description.lower()
                    mentions_def1 |= "@def" in desc
                    mentions_def2 |= "@def2" in desc
                if embed.title:
                    title = embed.title.lower()
                    mentions_def1 |= "@def" in title
                    mentions_def2 |= "@def2" in title

            content_lower = message.content.lower()
            mentions_def1 |= "@def" in content_lower
            mentions_def2 |= "@def2" in content_lower

            checked_messages += 1
            if mentions_def1 and mentions_def2:
                simultaneous_count += 1
            elif mentions_def1:
                def1_count += 1
            elif mentions_def2:
                def2_count += 1

            utilisateurs_comptes = set()
            for reaction in message.reactions:
                if str(reaction.emoji) == victory_emoji:
                    victory_count += 1
                elif str(reaction.emoji) == defeat_emoji:
                    defeat_count += 1
                elif str(reaction.emoji) == rage_emoji:
                    rage_count += 1
                elif str(reaction.emoji) == thumbsup_emoji:
                    async for user_react in reaction.users():
                        if not user_react.bot and user_react.id not in utilisateurs_comptes:
                            utilisateurs_comptes.add(user_react.id)
                            try:
                                member = await ctx.guild.fetch_member(user_react.id)
                                name = member.display_name
                            except:
                                name = user_react.name
                            thumbsup_stats[user_react.id]["count"] += 1
                            thumbsup_stats[user_react.id]["name"] = name

            for member in message.mentions:
                if not member.bot and member.id not in utilisateurs_comptes:
                    utilisateurs_comptes.add(member.id)
                    thumbsup_stats[member.id]["count"] += 1
                    thumbsup_stats[member.id]["name"] = member.display_name

            for alliance in alliances:
                if alliance.lower() in content_lower:
                    attaque_par_alliance[alliance] += 1
                for embed in message.embeds:
                    if embed.description and alliance.lower() in embed.description.lower():
                        attaque_par_alliance[alliance] += 1
                    if embed.title and alliance.lower() in embed.title.lower():
                        attaque_par_alliance[alliance] += 1

    embed_color = 0x2ecc71 if victory_count >= defeat_count and victory_count >= rage_count else (0xe67e22 if defeat_count >= rage_count else 0xe74c3c)

    embed = discord.Embed(
        title="📊 Statistiques des Défenses – 7 derniers jours",
        description="Résumé des attaques sur les percepteurs avec participation des défenseurs.",
        color=embed_color
    )
    embed.add_field(name="📍 Défenses détectées", value=f"`{checked_messages}`", inline=True)
    embed.add_field(name="🏰 Attaques sur Guilde 1", value=f"`{def1_count}`", inline=True)
    embed.add_field(name="🗼 Attaques sur Guilde 2", value=f"`{def2_count}`", inline=True)
    embed.add_field(name="🌿 Simultanées", value=f"`{simultaneous_count}`", inline=True)
    embed.add_field(name="\u200B", value="**🎯 Résultats des combats**", inline=False)
    embed.add_field(name="🏆 Victoires", value=f"`{victory_count}`", inline=True)
    embed.add_field(name="❌ Défaites", value=f"`{defeat_count}`", inline=True)
    embed.add_field(name="😡 Incomplètes", value=f"`{rage_count}`", inline=True)

    if thumbsup_stats:

        # Fusion manuelle des pseudos
        alias_mapping = {
            "1383914690270466048": "994240541585854574",
        }

        # Étape 1 : créer une copie fusionnée des données
        fusion_stats = defaultdict(lambda: {"count": 0, "name": ""})

        for user_id, data in thumbsup_stats.items():
            mapped_id = alias_mapping.get(user_id, user_id)
            fusion_stats[mapped_id]["count"] += data["count"]
            # on garde le nom du "compte principal"
            if not fusion_stats[mapped_id]["name"] or user_id == mapped_id:
                fusion_stats[mapped_id]["name"] = data["name"]


        # Étape 2 : trier
        sorted_defenders = sorted(fusion_stats.values(), key=lambda x: x["count"], reverse=True)

        sorted_defenders = sorted(thumbsup_stats.values(), key=lambda x: x["count"], reverse=True)
        lines = [f"{user['name']:<40} | {user['count']}" for user in sorted_defenders]
        header = f"{'Défenseur':<40} | Def\n{'-'*40} | ----"
        chunks = [header]
        for line in lines:
            if len(chunks[-1]) + len(line) + 1 > 950:
                chunks.append(header)
            chunks[-1] += f"\n{line}"
        for i, chunk in enumerate(chunks):
            title = "🧙 Top Défenseurs" if i == 0 else f"⬇️ Suite ({i+1})"
            embed.add_field(name=title, value=f"```{chunk}```", inline=False)
    else:
        embed.add_field(name="🧙 Top Défenseurs", value="Aucun défenseur cette dernière journée 😴", inline=False)

    embed.set_footer(text=f"Mise à jour : {datetime.utcnow().strftime('%d/%m/%Y à %H:%M UTC')}")
    await ctx.send(embed=embed)

@bot.command()
async def liste(ctx):
    now = datetime.now(ZoneInfo("Europe/Paris"))
    one_week_ago = now - timedelta(days=7)
    channel = bot.get_channel(CHANNEL_ID)
    thumbsup_stats = defaultdict(lambda: {"count": 0, "name": ""})

    async for message in channel.history(limit=None, after=one_week_ago, oldest_first=True):
        if message_mentionne_def(message):
            utilisateurs_comptes = set()
            for reaction in message.reactions:
                if str(reaction.emoji) == "👍":
                    async for user_react in reaction.users():
                        if not user_react.bot and user_react.id not in utilisateurs_comptes:
                            utilisateurs_comptes.add(user_react.id)
                            try:
                                member = await ctx.guild.fetch_member(user_react.id)
                                name = member.display_name
                            except:
                                name = user_react.name
                            thumbsup_stats[user_react.id]["count"] += 1
                            thumbsup_stats[user_react.id]["name"] = name
            for member in message.mentions:
                if not member.bot and member.id not in utilisateurs_comptes:
                    utilisateurs_comptes.add(member.id)
                    thumbsup_stats[member.id]["count"] += 1
                    thumbsup_stats[member.id]["name"] = member.display_name

    if thumbsup_stats:
        sorted_defenders = sorted(thumbsup_stats.values(), key=lambda x: x["count"], reverse=True)
        lines = [f"{user['name']} : {user['count']} def" for user in sorted_defenders]
        await ctx.send("\n".join(lines))
    else:
        await ctx.send("Aucun défenseur détecté dans les dernières 24h.")

    import matplotlib.pyplot as plt
    import io

    @bot.command()
    async def alliance(ctx):
        now = datetime.now(ZoneInfo("Europe/Paris"))
        one_week_ago = now - timedelta(days=7)
        channel = bot.get_channel(CHANNEL_ID)

        attaques = []

        async for message in channel.history(limit=None, after=one_week_ago, oldest_first=True):
            content_lower = message.content.lower()
            for embed in message.embeds:
                content_lower += f" {embed.title or ''} {embed.description or ''}".lower()

            if any(alliance.lower() in content_lower for alliance in [
                "Vae Victis", "Horizon", "Eclipse", "New Era", 
                "Autre alliance, merci de préciser la guilde", "Destin"
            ]):
                local_time = message.created_at.replace(
                    tzinfo=ZoneInfo("UTC")
                ).astimezone(ZoneInfo("Europe/Paris"))
                attaques.append(local_time.hour)

        if not attaques:
            await ctx.send("Aucune attaque détectée dans les 7 derniers jours.")
            return

        # Comptage par tranches de 2 heures
        tranches = [f"{h:02d}h-{(h+2)%24:02d}h" for h in range(0, 24, 2)]
        compteur = [0]*12

        for heure in attaques:
            index = heure // 2
            compteur[index] += 1

        # Création du camembert
        plt.figure(figsize=(6,6))
        plt.pie(
            compteur, 
            labels=tranches, 
            autopct=lambda p: f'{int(round(p*sum(compteur)/100))}' if p > 0 else '',
            startangle=90
        )
        plt.title("Répartition des attaques par tranches horaires (7 jours)")

        # Sauvegarde en mémoire et envoi
        buf = io.BytesIO()
        plt.savefig(buf, format="png", bbox_inches="tight")
        buf.seek(0)
        plt.close()

        file = discord.File(buf, filename="attaques.png")
        await ctx.send(file=file)

@bot.command()
async def alliance(ctx):
    now = datetime.now(ZoneInfo("Europe/Paris"))
    one_week_ago = now - timedelta(days=7)
    channel = bot.get_channel(CHANNEL_ID)

    attaques = []

    async for message in channel.history(limit=None, after=one_week_ago, oldest_first=True):
        content_lower = message.content.lower()
        for embed in message.embeds:
            content_lower += f" {embed.title or ''} {embed.description or ''}".lower()

        if any(alliance.lower() in content_lower for alliance in [
            "Vae Victis", "Horizon", "Eclipse", "New Era", 
            "Autre alliance, merci de préciser la guilde", "Destin"
        ]):
            local_time = message.created_at.replace(
                tzinfo=ZoneInfo("UTC")
            ).astimezone(ZoneInfo("Europe/Paris"))
            attaques.append(local_time.hour)

    if not attaques:
        await ctx.send("Aucune attaque détectée dans les 7 derniers jours.")
        return

    # Comptage par tranches de 2 heures
    tranches = [f"{h:02d}h-{(h+2)%24:02d}h" for h in range(0, 24, 2)]
    compteur = [0]*12

    for heure in attaques:
        index = heure // 2
        compteur[index] += 1

    # Création du camembert
    plt.figure(figsize=(6,6))
    plt.pie(
        compteur, 
        labels=tranches, 
        autopct=lambda p: f'{int(round(p*sum(compteur)/100))}' if p > 0 else '',
        startangle=90
    )
    plt.title("Répartition des attaques par tranches horaires (7 jours)")

    # Sauvegarde en mémoire et envoi
    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight")
    buf.seek(0)
    plt.close()

    file = discord.File(buf, filename="attaques.png")
    await ctx.send(file=file)

@bot.command(name="alliances7j")
async def alliances7j(ctx: commands.Context):
    """
    Liste chronologique sur 48h: <date heure> — <Alliance> — <lien>
    """
    # --- Paramètres ---
    tz = ZoneInfo(LOCAL_TZ) if 'LOCAL_TZ' in globals() else ZoneInfo("Europe/Paris")
    now = datetime.now(tz)
    since = now - timedelta(days=7)

    # Mappe des alliances que tu veux détecter (ajoute/retire librement)
    # clé = motif à chercher (minuscule), valeur = libellé affiché
    ALLIANCES_MAP = {
        "vae victis": "Vae Victis",
        "horizon": "Horizon",
        "eclipse": "Eclipse",
        "new era": "New Era",
        "destin": "Destin",
        # Exemple de libellé long que tu avais:
        "autre alliance, merci de préciser la guilde": "Autre alliance (à préciser)",
        # Tu peux en ajouter d'autres ici:
        # "clan oshimo": "Clan Oshimo",
        # "ivory": "Ivory",
        # "la secte": "La Secte",
        # "ateam": "ATeam",
        # "la bande": "La Bande",
        # "intmi": "INTMI",
        # "gueux randoms": "Gueux randoms",
    }

    channel = bot.get_channel(CHANNEL_ID)
    if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.ForumChannel)):
        await ctx.send("Channel introuvable ou non textuel.")
        return

    def detect_alliance(text_lower: str) -> str | None:
        for key, label in ALLIANCES_MAP.items():
            if key in text_lower:
                return label
        return None

    # Récupération des messages depuis 48h
    entries: list[tuple[datetime, str, str]] = []  # (datetime_local, alliance_label, jump_url)

    async for message in channel.history(limit=None, after=since, oldest_first=True):
        parts = [(message.content or "")]
        for e in message.embeds:
            parts.append(e.title or "")
            parts.append(e.description or "")
        text_lower = " ".join(parts).lower()

        alliance = detect_alliance(text_lower)
        if alliance:
            # created_at est normalement en UTC aware; on convertit proprement
            created_utc = message.created_at
            if created_utc.tzinfo is None:
                created_utc = created_utc.replace(tzinfo=timezone.utc)
            dt_local = created_utc.astimezone(tz)
            entries.append((dt_local, alliance, message.jump_url))

    if not entries:
        await ctx.send("Aucune attaque détectée dans les **48 dernières heures**.")
        return

    # Tri chrono
    entries.sort(key=lambda x: x[0])

    # Mise en forme et envoi (en chunks <= 2000 caractères)
    def fmt_line(dt: datetime, alliance: str, url: str) -> str:
        return f"{dt.strftime('%d/%m %H:%M')} — {alliance} — {url}"

    header = "📅 **Attaques détectées sur 7 jours (heure locale)**\n"
    block = header
    for dt_local, alliance, url in entries:
        line = fmt_line(dt_local, alliance, url) + "\n"
        if len(block) + len(line) > 1800:  # marge de sécurité
            await ctx.send(block)
            block = ""
        block += line

    if block:
        await ctx.send(block)

@bot.command()
async def graphic(ctx):
    channel = bot.get_channel(CHANNEL_ID)
    messages = []
    async for message in channel.history(limit=5000):
        if message.author == bot.user and message.embeds:
            messages.append(message)
        if len(messages) >= 10:
            break
    messages = sorted(messages, key=lambda m: m.created_at)  # Chrono

    if not messages:
        await ctx.send("Aucun message de statistiques trouvé.")
        return

    import re
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import io
    from datetime import timezone

    dates = []
    victories = []
    defeats = []
    incompletes = []
    totals = []

    # Regex patterns
    regex_vic = re.compile(r"🏆 Victoires\s*`(\d+)`", re.IGNORECASE)
    regex_def = re.compile(r"❌ Défaites\s*`(\d+)`", re.IGNORECASE)
    regex_inc = re.compile(r"😡 Incomplètes\s*`(\d+)`", re.IGNORECASE)
    regex_tot = re.compile(r"📍 Défenses détectées\s*`(\d+)`", re.IGNORECASE)

    for msg in messages:
        embed = msg.embeds[0]
        text_to_search = (embed.description or "") + "\n"
        for field in embed.fields:
            text_to_search += field.name + "\n" + (field.value or "") + "\n"

        vic = regex_vic.search(text_to_search)
        defe = regex_def.search(text_to_search)
        inc = regex_inc.search(text_to_search)
        tot = regex_tot.search(text_to_search)

        if not (vic and defe and inc and tot):
            continue

        vic_n = int(vic.group(1))
        defe_n = int(defe.group(1))
        inc_n = int(inc.group(1))
        tot_n = int(tot.group(1))
        if tot_n == 0:
            continue

        dates.append(msg.created_at.replace(tzinfo=timezone.utc))
        victories.append(vic_n)
        defeats.append(defe_n)
        incompletes.append(inc_n)
        totals.append(tot_n)

    if not dates:
        await ctx.send("Pas assez de données exploitables pour créer un graphique.")
        return

    # Calcul pourcentages
    victories_pct = [v / t * 100 for v, t in zip(victories, totals)]
    defeats_pct = [d / t * 100 for d, t in zip(defeats, totals)]
    incompletes_pct = [i / t * 100 for i, t in zip(incompletes, totals)]

    # --- Graphique 1 : Pourcentages ---
    plt.figure(figsize=(10, 6))
    plt.plot(dates, victories_pct, label="🏆 Victoires (%)", color="green", marker='o')
    plt.plot(dates, defeats_pct, label="❌ Défaites (%)", color="red", marker='o')
    plt.plot(dates, incompletes_pct, label="😡 Incomplètes (%)", color="orange", marker='o')
    plt.title("Évolution des Pourcentages de Défenses")
    plt.xlabel("Date")
    plt.ylabel("Pourcentage (%)")
    plt.ylim(0, 100)
    plt.grid(True, linestyle='--', alpha=0.5)
    plt.legend()
    plt.gcf().autofmt_xdate()
    plt.gca().xaxis.set_major_locator(mdates.AutoDateLocator())
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%d/%m %H:%M'))
    plt.tight_layout()
    buf1 = io.BytesIO()
    plt.savefig(buf1, format='png', dpi=150)
    plt.close()

    # --- Graphique 2 : Valeurs absolues ---
    plt.figure(figsize=(10, 6))
    plt.plot(dates, victories, label="🏆 Victoires", color="green", marker='o')
    plt.plot(dates, defeats, label="❌ Défaites", color="red", marker='o')
    plt.plot(dates, incompletes, label="😡 Incomplètes", color="orange", marker='o')
    plt.plot(dates, totals, label="📍 Défenses détectées", color="blue", marker='o')
    plt.title("Évolution des Nombres Absolus de Défenses")
    plt.xlabel("Date")
    plt.ylabel("Nombre")
    plt.grid(True, linestyle='--', alpha=0.5)
    plt.legend()
    plt.gcf().autofmt_xdate()
    plt.gca().xaxis.set_major_locator(mdates.AutoDateLocator())
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%d/%m %H:%M'))
    plt.tight_layout()
    buf2 = io.BytesIO()
    plt.savefig(buf2, format='png', dpi=150)
    plt.close()

    buf1.seek(0)
    buf2.seek(0)

    await ctx.send(file=discord.File(fp=buf1, filename="defenses_pourcentages.png"))
    await ctx.send(file=discord.File(fp=buf2, filename="defenses_valeurs.png"))


bot.run
