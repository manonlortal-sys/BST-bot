import discord
from discord.ext import commands

class Roulette(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="testroulette")
    async def testroulette(self, ctx):
        """Commande de test pour vérifier que le cog roulette fonctionne"""
        await ctx.send("🎰 Le cog Roulette est bien chargé !")

async def setup(bot):
    await bot.add_cog(Roulette(bot))
