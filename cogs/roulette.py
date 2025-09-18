import os
import random
import asyncio
import discord
from discord.ext import commands

CROUPIER_ROLE_ID = int(os.getenv("CROUPIER_ROLE_ID", "0"))   # rôle croupier (ping/validation)
ROULETTE_GIF_URL = os.getenv("ROULETTE_GIF_URL", "")         # gif de roulette (optionnel)
COMMISSION_PERCENT = float(os.getenv("COMMISSION_PERCENT", "5.0"))  # 5% par défaut

# Leaderboard en mémoire: {guild_id: {user_id: {"mise": int, "net": int}}}
leaderboards: dict[int, dict[int, dict[str, int]]] = {}

RED_NUMBERS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}


def lb_add(guild_id: int, user_id: int, mise: int = 0, net: int = 0):
    g = leaderboards.setdefault(guild_id, {})
    s = g.setdefault(user_id, {"mise": 0, "net": 0})
    s["mise"] += mise
    s["net"] += net


class DuelTypeSelect(discord.ui.View):
    def __init__(self, starter: discord.Member, mise: int, timeout: float = 120):
        super().__init__(timeout=timeout)
        self.starter = starter
        self.mise = mise
        self.duel_type: str | None = None  # "couleur" | "parite" | "intervalle"
        self.msg: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.starter.id:
            await interaction.response.send_message("Seul le créateur peut choisir le type de duel.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🔴⚫  rouge/noir", style=discord.ButtonStyle.danger)
    async def btn_color(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.duel_type = "couleur"
        await interaction.response.edit_message(view=None)
        self.stop()

    @discord.ui.button(label="⚖️  pair/impair", style=discord.ButtonStyle.primary)
    async def btn_parity(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.duel_type = "parite"
        await interaction.response.edit_message(view=None)
        self.stop()

    @discord.ui.button(label="1️⃣-18 / 19-36", style=discord.ButtonStyle.success)
    async def btn_range(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.duel_type = "intervalle"
        await interaction.response.edit_message(view=None)
        self.stop()


class SideSelect(discord.ui.View):
    def __init__(self, starter: discord.Member, duel_type: str, timeout: float = 120):
        super().__init__(timeout=timeout)
        self.starter = starter
        self.duel_type = duel_type
        self.choice: str | None = None  # "rouge"/"noir" | "pair"/"impair" | "1-18"/"19-36"

        # boutons dynamiques selon duel
        if duel_type == "couleur":
            self.add_item(discord.ui.Button(label="🔴 Rouge", style=discord.ButtonStyle.danger, custom_id="c_rouge"))
            self.add_item(discord.ui.Button(label="⚫ Noir", style=discord.ButtonStyle.secondary, custom_id="c_noir"))
        elif duel_type == "parite":
            self.add_item(discord.ui.Button(label="Pair", style=discord.ButtonStyle.primary, custom_id="p_pair"))
            self.add_item(discord.ui.Button(label="Impair", style=discord.ButtonStyle.secondary, custom_id="p_impair"))
        else:
            self.add_item(discord.ui.Button(label="1-18", style=discord.ButtonStyle.success, custom_id="r_1_18"))
            self.add_item(discord.ui.Button(label="19-36", style=discord.ButtonStyle.secondary, custom_id="r_19_36"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.starter.id:
            await interaction.response.send_message("Seul le créateur choisit son camp.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="dummy", style=discord.ButtonStyle.secondary, disabled=True)
    async def _dummy(self, *_):  # ne sera jamais affiché (on ajoute des boutons dynamiques au __init__)
        pass

    async def on_timeout(self):
        # désactiver tous les boutons si timeout
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

    async def callback(self, interaction: discord.Interaction, custom_id: str):
        mapping = {
            "c_rouge": "rouge", "c_noir": "noir",
            "p_pair": "pair", "p_impair": "impair",
            "r_1_18": "1-18", "r_19_36": "19-36",
        }
        if custom_id in mapping:
            self.choice = mapping[custom_id]
            await interaction.response.edit_message(view=None)
            self.stop()

    async def interaction_check_and_route(self, interaction: discord.Interaction):
        if await self.interaction_check(interaction):
            await self.callback(interaction, interaction.data.get("custom_id"))  # type: ignore

    async def on_error(self, interaction: discord.Interaction, error: Exception, item) -> None:
        try:
            await interaction.response.send_message(f"Erreur: {error}", ephemeral=True)
        except:
            pass

    # monkey patch: route tous les boutons dynamiques ici
    async def interaction_check(self, interaction: discord.Interaction) -> bool:  # type: ignore[override]
        if interaction.user.id != self.starter.id:
            await interaction.response.send_message("Seul le créateur choisit son camp.", ephemeral=True)
            return False
        # route
        await self.callback(interaction, interaction.data.get("custom_id"))  # type: ignore
        return False


class JoinAndValidate(discord.ui.View):
    def __init__(self, starter: discord.Member, mise: int, duel_type: str, starter_choice: str, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.starter = starter
        self.mise = mise
        self.duel_type = duel_type
        self.starter_choice = starter_choice
        self.joiner: discord.Member | None = None
        self.validated_by: discord.Member | None = None

    @discord.ui.button(label="🤝 Rejoindre", style=discord.ButtonStyle.primary)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id == self.starter.id:
            return await interaction.response.send_message("Tu es déjà le créateur de la partie.", ephemeral=True)
        if self.joiner is not None:
            return await interaction.response.send_message("Un adversaire a déjà rejoint.", ephemeral=True)
        self.joiner = interaction.user  # type: ignore
        await interaction.response.send_message(f"{interaction.user.mention} a rejoint la partie !", ephemeral=True)

    @discord.ui.button(label="✅ Valider mises (croupier)", style=discord.ButtonStyle.success)
    async def validate(self, interaction: discord.Interaction, button: discord.ui.Button):
        if CROUPIER_ROLE_ID and not any(r.id == CROUPIER_ROLE_ID for r in interaction.user.roles):  # type: ignore
            return await interaction.response.send_message("Réservé au rôle Croupier.", ephemeral=True)
        if self.joiner is None:
            return await interaction.response.send_message("Attends qu’un adversaire rejoigne.", ephemeral=True)
        self.validated_by = interaction.user  # type: ignore
        await interaction.response.send_message("Mises validées, la roulette va tourner…", ephemeral=True)
        self.stop()


class Roulette(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(name="roulette", description="Lancer une roulette à deux joueurs (avec croupier)")
    @discord.app_commands.describe(mise="Mise en kamas (entier positif)")
    async def roulette_cmd(self, interaction: discord.Interaction, mise: int):
        if mise <= 0:
            return await interaction.response.send_message("La mise doit être un entier **positif**.", ephemeral=True)

        # 1) Choix du type de duel
        duel_view = DuelTypeSelect(starter=interaction.user, mise=mise)
        duel_embed = discord.Embed(
            title="🎰 Nouvelle Roulette",
            description=(
                f"Créateur : {interaction.user.mention}\n"
                f"Mise : **{mise}k**\n\n"
                f"Choisis le **type de duel** :"
            ),
            color=discord.Color.orange()
        )
        await interaction.response.send_message(embed=duel_embed, view=duel_view)
        duel_msg = await interaction.original_response()
        await duel_view.wait()
        if not duel_view.duel_type:
            try:
                await duel_msg.edit(content="⏳ Duel annulé (aucun type choisi).", embed=None, view=None)
            except:
                pass
            return
        duel_type = duel_view.duel_type

        # 2) Choix du camp par le créateur
        side_view = SideSelect(starter=interaction.user, duel_type=duel_type)
        side_embed = discord.Embed(
            title="🎯 Choisis ton camp",
            description=(
                f"Type : **{('rouge/noir' if duel_type=='couleur' else 'pair/impair' if duel_type=='parite' else '1-18/19-36')}**\n"
                "Clique un bouton ci-dessous."
            ),
            color=discord.Color.orange()
        )
        msg2 = await interaction.channel.send(embed=side_embed, view=side_view)
        await asyncio.sleep(0)  # yield
        await side_view.wait()
        if not side_view.choice:
            try:
                await msg2.edit(content="⏳ Duel annulé (aucun camp choisi).", embed=None, view=None)
            except:
                pass
            return
        starter_choice = side_view.choice

        # 3) Attente adversaire + validation croupier
        join_view = JoinAndValidate(
            starter=interaction.user, mise=mise, duel_type=duel_type, starter_choice=starter_choice
        )
        wait_embed = discord.Embed(
            title="⏱️ En attente d’un second joueur",
            description=(
                f"**Type :** {('rouge/noir' if duel_type=='couleur' else 'pair/impair' if duel_type=='parite' else '1-18/19-36')}\n"
                f"**Camp du créateur :** `{starter_choice}`\n\n"
                "• Un adversaire clique **Rejoindre**\n"
                "• Puis un **Croupier** valide les mises"
            ),
            color=discord.Color.orange()
        )
        msg3 = await interaction.channel.send(embed=wait_embed, view=join_view)
        await join_view.wait()

        if join_view.joiner is None:
            try:
                await msg3.edit(content="⏳ Temps écoulé, personne n’a rejoint.", embed=None, view=None)
            except:
                pass
            return
        if join_view.validated_by is None:
            try:
                await msg3.edit(content="⏳ Temps écoulé, mises non validées par un croupier.", embed=None, view=None)
            except:
                pass
            return

        # 4) Spin
        spin_embed = discord.Embed(
            title="🎡 La roulette tourne…",
            description="Bonne chance !",
            color=discord.Color.orange()
        )
        if ROULETTE_GIF_URL:
            spin_embed.set_image(url=ROULETTE_GIF_URL)
        spin_msg = await interaction.channel.send(embed=spin_embed)
        await asyncio.sleep(5)

        n = random.randint(0, 36)
        color = "vert" if n == 0 else ("rouge" if n in RED_NUMBERS else "noir")
        parity = "pair" if n != 0 and n % 2 == 0 else "impair"
        interval = "1-18" if 1 <= n <= 18 else ("19-36" if 19 <= n <= 36 else "0")

        # qui gagne ?
        def starter_wins() -> bool:
            if duel_type == "couleur":
                return starter_choice == color
            if duel_type == "parite":
                return starter_choice == parity
            if duel_type == "intervalle":
                return starter_choice == interval
            return False

        winner = interaction.user if starter_wins() else join_view.joiner  # type: ignore
        loser = join_view.joiner if winner == interaction.user else interaction.user  # type: ignore

        total_pot = mise * 2
        commission = int(round(total_pot * (COMMISSION_PERCENT / 100.0)))
        gain = total_pot - commission

        result_embed = discord.Embed(
            title="✅ Résultat de la roulette",
            description=(
                f"**Nombre :** {n} ({color}) — {parity} — {interval}\n"
                f"**Gagnant :** {winner.mention}\n"
                f"**Gain :** {gain}k\n"
                f"**Commission croupier :** {commission}k"
            ),
            color=discord.Color.green() if winner == interaction.user else discord.Color.red()
        )
        await spin_msg.edit(embed=result_embed)

        # 5) Leaderboard (mise totale et net)
        gid = interaction.guild.id  # type: ignore
        lb_add(gid, interaction.user.id, mise=mise, net=(gain - mise) if winner == interaction.user else -mise)
        lb_add(gid, join_view.joiner.id, mise=mise, net=(gain - mise) if winner == join_view.joiner else -mise)  # type: ignore

    @discord.app_commands.command(name="leaderboard", description="Afficher le leaderboard (par serveur)")
    async def leaderboard_cmd(self, interaction: discord.Interaction):
        gid = interaction.guild.id  # type: ignore
        data = leaderboards.get(gid)
        if not data:
            return await interaction.response.send_message("Pas encore de parties ici.", ephemeral=True)

        classement = sorted(data.items(), key=lambda kv: kv[1]["mise"], reverse=True)
        total_mises = sum(v["mise"] for v in data.values())

        lines = []
        for uid, stats in classement:
            member = interaction.guild.get_member(uid)  # type: ignore
            name = member.display_name if member else f"ID:{uid}"
            lines.append(f"**{name}** — misé: {stats['mise']}k | net: {stats['net']}k")

        embed = discord.Embed(title="📊 Leaderboard", description="\n".join(lines), color=discord.Color.blurple())
        embed.set_footer(text=f"Total misé (serveur) : {total_mises}k")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Roulette(bot))
