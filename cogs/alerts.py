from __future__ import annotations

import time
from typing import Optional, List

import discord
from discord.ext import commands

from .utils import (
    get_state,
    AlertData,
    ROLE_MEMBRES_ID,
    ROLE_TEST_ID,
    PING_COOLDOWN_SECONDS,
    now_ts,
    format_attack_time,
    CHANNEL_DEFENSE_ID,
)


class AttackerModal(discord.ui.Modal, title="Définir l'attaquant"):
    def __init__(self, bot: commands.Bot, alert_message_id: int):
        super().__init__(timeout=300)
        self.bot = bot
        self.alert_message_id = alert_message_id

        self.attacker_input = discord.ui.TextInput(
            label="Guilde attaquante",
            placeholder="Nom de la guilde / alliance / infos utiles",
            max_length=200,
            required=True,
        )
        self.add_item(self.attacker_input)

    async def on_submit(self, interaction: discord.Interaction):
        state = get_state(self.bot)
        alert = state.alerts.get(self.alert_message_id)
        if not alert:
            await interaction.response.send_message(
                "Cette alerte n'existe plus.", ephemeral=True
            )
            return

        alert.attacker = str(self.attacker_input.value).strip()
        alerts_cog: Optional[Alerts] = self.bot.get_cog("Alerts")  # type: ignore
        if alerts_cog:
            await alerts_cog.update_alert_message(alert.message_id)

        await interaction.response.send_message(
            "Attaquant mis à jour sur l'alerte.", ephemeral=True
        )


class DefenderSelect(discord.ui.UserSelect):
    def __init__(self, bot: commands.Bot, alert_message_id: int):
        super().__init__(placeholder="Sélectionne un ou plusieurs défenseurs…", min_values=1, max_values=5)
        self.bot = bot
        self.alert_message_id = alert_message_id

    async def callback(self, interaction: discord.Interaction):
        state = get_state(self.bot)
        alert = state.alerts.get(self.alert_message_id)
        if not alert:
            await interaction.response.send_message(
                "Cette alerte n'existe plus.", ephemeral=True
            )
            return

        alerts_cog: Optional[Alerts] = self.bot.get_cog("Alerts")  # type: ignore
        if not alerts_cog:
            await interaction.response.send_message(
                "Système d'alertes indisponible.", ephemeral=True
            )
            return

        added: List[str] = []
        for user in self.values:
            if await alerts_cog.add_defender_to_alert(alert.message_id, user.id):
                added.append(user.mention)

        if not added:
            msg = "Les défenseurs sélectionnés étaient déjà enregistrés sur cette alerte."
        else:
            msg = "Défenseurs ajoutés : " + ", ".join(added)

        await interaction.response.edit_message(content=msg, view=None)


class DefenderSelectView(discord.ui.View):
    def __init__(self, bot: commands.Bot, alert_message_id: int):
        super().__init__(timeout=60)
        self.add_item(DefenderSelect(bot, alert_message_id))


class AlertView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="Solo",
        style=discord.ButtonStyle.secondary,
        custom_id="alert_solo",
    )
    async def solo_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        state = get_state(self.bot)
        state.alerts.pop(interaction.message.id, None)
        try:
            await interaction.message.delete()
        except discord.HTTPException:
            try:
                await interaction.response.send_message(
                    "Impossible de supprimer ce message.", ephemeral=True
                )
            except discord.HTTPException:
                pass

    @discord.ui.button(
        label="Attaquant",
        style=discord.ButtonStyle.primary,
        custom_id="alert_attacker",
    )
    async def attacker_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        state = get_state(self.bot)
        if interaction.message.id not in state.alerts:
            await interaction.response.send_message(
                "Cette alerte n'existe plus.", ephemeral=True
            )
            return

        await interaction.response.send_modal(
            AttackerModal(self.bot, interaction.message.id)
        )

    @discord.ui.button(
        label="Défenseur",
        style=discord.ButtonStyle.success,
        custom_id="alert_defender",
    )
    async def defender_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        state = get_state(self.bot)
        if interaction.message.id not in state.alerts:
            await interaction.response.send_message(
                "Cette alerte n'existe plus.", ephemeral=True
            )
            return

        view = DefenderSelectView(self.bot, interaction.message.id)
        await interaction.response.send_message(
            "Sélectionne un ou plusieurs défenseurs :", view=view, ephemeral=True
        )


class Alerts(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.alert_view = AlertView(bot)
        # Vue persistante pour que les boutons continuent de marcher après un redémarrage
        bot.add_view(self.alert_view)

    # --- Construction / mise à jour de l'embed ---

    def build_alert_embed(self, alert: AlertData) -> discord.Embed:
        if alert.state == "won" and alert.incomplete:
            etat = "Gagnée (incomplète)"
            color = discord.Color.yellow()
        elif alert.state == "lost" and alert.incomplete:
            etat = "Perdue (incomplète)"
            color = discord.Color.dark_red()
        elif alert.state == "won":
            etat = "Gagnée"
            color = discord.Color.green()
        elif alert.state == "lost":
            etat = "Perdue"
            color = discord.Color.dark_red()
        else:
            etat = "En cours"
            color = discord.Color.red()

        embed = discord.Embed(
            title="📯 Alerte Défense",
            color=color,
        )

        embed.add_field(
            name="🔔 Déclenchée par :",
            value=f"<@{alert.triggered_by_id}>",
            inline=False,
        )

        embed.add_field(
            name="🛡️ État de la défense :",
            value=etat,
            inline=False,
        )

        if alert.defenders:
            defenders_str = ", ".join(f"<@{d}>" for d in alert.defenders)
        else:
            defenders_str = "Aucun"

        embed.add_field(
            name="⚔️ Défenseurs :",
            value=defenders_str,
            inline=False,
        )

        attacker_str = alert.attacker if alert.attacker else "Non renseigné"

        embed.add_field(
            name="🎯 Attaquant :",
            value=attacker_str,
            inline=False,
        )

        embed.add_field(
            name="⏰ Heure de l’attaque :",
            value=format_attack_time(alert.created_timestamp),
            inline=False,
        )

        return embed

    async def update_alert_message(self, alert_id: int):
        state = get_state(self.bot)
        alert = state.alerts.get(alert_id)
        if not alert:
            return

        channel = self.bot.get_channel(alert.channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return

        try:
            msg = await channel.fetch_message(alert.message_id)
        except discord.HTTPException:
            return

        embed = self.build_alert_embed(alert)
        try:
            await msg.edit(embed=embed, view=self.alert_view)
        except discord.HTTPException:
            pass

    # --- API utilisée par les autres cogs ---

    async def handle_ping_button(
        self, interaction: discord.Interaction, is_test: bool
    ):
        state = get_state(self.bot)
        user = interaction.user

        # Bouton Test : réservé aux admins (vérif ailleurs si besoin aussi)
        if is_test:
            has_admin = False
            if isinstance(user, discord.Member):
                has_admin = any(
                    r.id == ROLE_TEST_ID or r.id == ROLE_MEMBRES_ID or r.id == ROLE_ADMIN_ID
                    for r in user.roles
                )
            # Tu avais demandé "seul rôle Admin pour Test" => on force admin ici
            if isinstance(user, discord.Member):
                has_admin = any(r.id == ROLE_ADMIN_ID for r in user.roles)
            if not has_admin:
                await interaction.response.send_message(
                    "Ce bouton est réservé aux administrateurs.", ephemeral=True
                )
                return
        else:
            # Cooldown global uniquement pour Ping! (pas Test)
            now = time.time()
            if (
                state.last_ping_timestamp is not None
                and now - state.last_ping_timestamp < PING_COOLDOWN_SECONDS
            ):
                restant = int(
                    PING_COOLDOWN_SECONDS - (now - state.last_ping_timestamp)
                )
                restant = max(restant, 1)
                await interaction.response.send_message(
                    f"Un ping a déjà été envoyé récemment. Merci d'attendre encore {restant} secondes.",
                    ephemeral=True,
                )
                return
            state.last_ping_timestamp = now

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "Cette commande ne peut être utilisée que sur un serveur.", ephemeral=True
            )
            return

        defense_channel = self.bot.get_channel(CHANNEL_DEFENSE_ID)
        if not isinstance(defense_channel, discord.TextChannel):
            await interaction.response.send_message(
                "Le canal de défense est introuvable.", ephemeral=True
            )
            return

        if is_test:
            role_id = ROLE_TEST_ID
            role_mention = f"<@&{ROLE_TEST_ID}>"
            text = f"{role_mention} Alerte de test déclenchée."
            role_kind = "test"
        else:
            role_id = ROLE_MEMBRES_ID
            role_mention = f"<@&{ROLE_MEMBRES_ID}>"
            text = f"🚨{role_mention} un percepteur se fait attaquer ! Merci de vous connecter ! 🚨"
            role_kind = "members"

        created_ts = now_ts()
        alert_data = AlertData(
            message_id=0,  # provisoire
            channel_id=defense_channel.id,
            guild_id=guild.id,
            triggered_by_id=user.id,
            role_kind=role_kind,
            created_timestamp=created_ts,
        )

        embed = self.build_alert_embed(alert_data)

        # On envoie l'alerte avec les boutons
        msg = await defense_channel.send(content=text, embed=embed, view=self.alert_view)

        alert_data.message_id = msg.id
        state.alerts[msg.id] = alert_data

        # Leaderboard Ping : uniquement pour Ping!, pas pour Test
        if not is_test:
            state.ping_counts[user.id] = state.ping_counts.get(user.id, 0) + 1
            leaderboard_cog = self.bot.get_cog("Leaderboard")  # type: ignore
            if leaderboard_cog:
                await leaderboard_cog.update_leaderboards()  # type: ignore

        # On confirme l'action au clickeur
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "Alerte envoyée dans le canal de défense.", ephemeral=True
            )

    async def add_defender_to_alert(
        self, alert_id: int, user_id: int
    ) -> bool:
        state = get_state(self.bot)
        alert = state.alerts.get(alert_id)
        if not alert:
            return False

        if user_id in alert.defenders:
            return False

        alert.defenders.add(user_id)
        # Leaderboard Défenseurs : +1 par alerte où la personne est défenseur
        state.defense_counts[user_id] = state.defense_counts.get(user_id, 0) + 1

        await self.update_alert_message(alert_id)

        leaderboard_cog = self.bot.get_cog("Leaderboard")  # type: ignore
        if leaderboard_cog:
            await leaderboard_cog.update_leaderboards()  # type: ignore

        return True

    async def mark_defense_won(self, alert_id: int):
        state = get_state(self.bot)
        alert = state.alerts.get(alert_id)
        if not alert:
            return
        alert.state = "won"
        await self.update_alert_message(alert_id)

    async def mark_defense_lost(self, alert_id: int):
        state = get_state(self.bot)
        alert = state.alerts.get(alert_id)
        if not alert:
            return
        alert.state = "lost"
        await self.update_alert_message(alert_id)

    async def toggle_incomplete(self, alert_id: int):
        state = get_state(self.bot)
        alert = state.alerts.get(alert_id)
        if not alert:
            return
        alert.incomplete = not alert.incomplete
        await self.update_alert_message(alert_id)


async def setup(bot: commands.Bot):
    await bot.add_cog(Alerts(bot))

