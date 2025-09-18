import discord
from discord.ext import commands

class Ping(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="testping")
    async def testping(self, ctx):
        """Commande de test pour vérifier que le cog ping fonctionne"""
        await ctx.send("📢 Le cog Ping est bien chargé !")

async def setup(bot):
    await bot.add_cog(Ping(bot))
