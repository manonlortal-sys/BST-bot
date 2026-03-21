def is_orga_or_admin(interaction):
    # Ton ID perso (autorisé quoi qu'il arrive)
    if interaction.user.id == 1352575142668013588:
        return True

    # Admin
    if interaction.user.guild_permissions.administrator:
        return True

    # Rôle Lead (exact)
    for role in interaction.user.roles:
        if role.name == "Lead":
            return True

    return False
