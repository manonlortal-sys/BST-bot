# cogs/combat.py (suite et mise à jour)

LADDER_ROLE_ID = 1328097429525893192  # Remplace par l'ID réel du rôle ladder

class CombatView(discord.ui.View):
    BONUS_POINTS = {"aucun_mort": 3, "attaque": 5, "defense": 5, "sup": -2, "inf": 3}

    def __init__(self, cog, joueur_id):
        super().__init__(timeout=None)
        self.cog = cog
        self.joueur_id = joueur_id

    # ----------------- Boutons principaux -----------------
    @discord.ui.button(label="🗡️ Attaque", style=discord.ButtonStyle.red)
    async def attaque(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_type(interaction, "Attaque")

    @discord.ui.button(label="🛡️ Défense", style=discord.ButtonStyle.red)
    async def defense(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_type(interaction, "Défense")

    @discord.ui.button(label="💀 Aucun mort", style=discord.ButtonStyle.gray)
    async def aucun_mort(self, interaction: discord.Interaction, button: discord.ui.Button):
        combat = self.cog.combats_en_cours[self.joueur_id]
        combat["aucun_mort"] = not combat["aucun_mort"]
        combat["bonus"]["aucun_mort"] = self.BONUS_POINTS["aucun_mort"] if combat["aucun_mort"] else 0
        combat["points"] = sum(combat["bonus"].values())
        await self.update_embed(combat)
        await interaction.response.defer()

    @discord.ui.button(label="➕ Ajouter joueurs", style=discord.ButtonStyle.blurple)
    async def ajouter_joueurs(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = AjouterJoueursView(self.cog, self.joueur_id)
        await interaction.response.send_message(
            "Sélectionne les joueurs à ajouter ⬇️",
            view=view,
            ephemeral=True
        )

    @discord.ui.button(label="📸 Ajouter screens", style=discord.ButtonStyle.gray)
    async def ajouter_screens(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Envoie ici tes screens du combat (tu peux en envoyer plusieurs).",
            ephemeral=True
        )
        # On stocke la réponse de l'utilisateur dans combat["pending_screens"]
        combat = self.cog.combats_en_cours[self.joueur_id]
        combat["pending_screens"] = True  # Flag pour indiquer qu'on attend des fichiers

    @discord.ui.button(label="✅ Valider combat", style=discord.ButtonStyle.green)
    async def valider_combat(self, interaction: discord.Interaction, button: discord.ui.Button):
        combat = self.cog.combats_en_cours[self.joueur_id]

        if len(combat["joueurs_present"]) == 0:
            await interaction.response.send_message(
                "❌ Tu dois ajouter au moins un joueur avant de valider.",
                ephemeral=True
            )
            return

        # Préparer les fichiers (screens)
        files = getattr(combat, "screens", [])
        embed = await self.create_final_embed(combat)

        # Envoi au rôle ladder
        role = interaction.guild.get_role(LADDER_ROLE_ID)
        content = role.mention if role else ""
        await interaction.channel.send(content=content, embed=embed, files=files)

        # Supprimer le combat
        del self.cog.combats_en_cours[self.joueur_id]
        await interaction.response.send_message("✅ Combat validé et envoyé au ladder !", ephemeral=True)

    # ----------------- Fonctions auxiliaires -----------------
    async def set_type(self, interaction: discord.Interaction, combat_type: str):
        combat = self.cog.combats_en_cours[self.joueur_id]
        combat["type"] = combat_type
        combat["bonus"]["attaque" if combat_type == "Attaque" else "defense"] = self.BONUS_POINTS[combat_type.lower()]
        combat["points"] = sum(combat["bonus"].values())
        await self.update_embed(combat)
        await interaction.response.defer()

    async def update_embed(self, combat):
        points_lines = [
            f"🗡️ Attaque : +{combat['bonus']['attaque']} pts",
            f"🛡️ Défense : +{combat['bonus']['defense']} pts",
            f"💀 Aucun mort : +{combat['bonus']['aucun_mort']} pts",
        ]
        # Supériorité/infériorité si présent
        if "sup_inf" in combat:
            sup_inf = combat["sup_inf"]
            if sup_inf == "sup":
                points_lines.append(f"⬆ Supériorité : {self.BONUS_POINTS['sup']} pts")
            elif sup_inf == "inf":
                points_lines.append(f"⬇ Infériorité : +{self.BONUS_POINTS['inf']} pts")

        embed = discord.Embed(
            title="📊 Ajout d’un combat au ladder purgatoire",
            description="Validation en attente ⏳",
            color=0x5865F2
        )
        embed.add_field(
            name="👥 Joueurs présents",
            value=", ".join([m.mention for m in combat["joueurs_present"]])
        )
        embed.add_field(name="💠 Points du combat", value="\n".join(points_lines))
        embed.add_field(name="💰 Points par joueur", value=f"{combat['points']} pts")
        embed.add_field(
            name="📸 Screens ajoutés",
            value=f"{len(combat.get('screens', []))} fichier(s)" if combat.get("screens") else "0"
        )
        await combat["message"].edit(embed=embed, view=combat["view"])

    async def create_final_embed(self, combat):
        points_lines = [
            f"🗡️ Attaque : +{combat['bonus']['attaque']} pts",
            f"🛡️ Défense : +{combat['bonus']['defense']} pts",
            f"💀 Aucun mort : +{combat['bonus']['aucun_mort']} pts",
        ]
        if "sup_inf" in combat:
            sup_inf = combat["sup_inf"]
            if sup_inf == "sup":
                points_lines.append(f"⬆ Supériorité : {self.BONUS_POINTS['sup']} pts")
            elif sup_inf == "inf":
                points_lines.append(f"⬇ Infériorité : +{self.BONUS_POINTS['inf']} pts")

        embed = discord.Embed(
            title="📊 Combat validé au ladder purgatoire",
            description="✅ Combat validé et envoyé !",
            color=0x57F287
        )
        embed.add_field(
            name="👥 Joueurs présents",
            value=", ".join([m.mention for m in combat["joueurs_present"]])
        )
        embed.add_field(name="💠 Points du combat", value="\n".join(points_lines))
        embed.add_field(name="💰 Total par joueur", value=f"{combat['points']} pts")
        return embed

# Les classes AjouterJoueursView et JoueurSelect restent identiques, elles mettent à jour l'embed en temps réel