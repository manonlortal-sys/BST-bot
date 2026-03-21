def is_orga_or_admin(interaction):
    # Admin
    if interaction.user.guild_permissions.administrator:
        return True

    # Rôle Lead
    for role in interaction.user.roles:
        if role.name.lower() == "Lead":
            return True

    return False
