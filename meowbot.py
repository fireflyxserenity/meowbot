import os
import discord
from discord.ext import commands, tasks
from discord import app_commands
from dotenv import load_dotenv
import datetime
import asyncio
import aiohttp
from peewee import SqliteDatabase, Model, IntegerField, TextField, BooleanField
import parsedatetime
import re

# Load environment variables
load_dotenv()

# Database setup
db_file = 'bot_data.db'
if not os.path.exists(db_file):
    with open(db_file, 'w') as f:
        pass

absolute_db_path = os.path.abspath(db_file)
print(f"Database file path: {absolute_db_path}")

# Define the SQLite database
db = SqliteDatabase(db_file)

# Define models for data storage
class UserInfractions(Model):
    user_id = IntegerField(unique=True)
    infractions = IntegerField(default=0)

    class Meta:
        database = db

class UserMeowCounts(Model):
    user_id = IntegerField(unique=True)
    meow_count = IntegerField(default=0)

    class Meta:
        database = db

class ConfessionCounter(Model):
    id = IntegerField(primary_key=True)
    count = IntegerField(default=0)

    class Meta:
        database = db

# Connect to the database and create tables
db.connect()
db.create_tables([UserInfractions, UserMeowCounts, ConfessionCounter], safe=True)

# Global counter
meow_counter = 0

# Get credentials from environment variables
DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
# Twitch credentials
TWITCH_CLIENT_ID = os.getenv('TWITCH_CLIENT_ID')
TWITCH_SECRET = os.getenv('TWITCH_SECRET')
TWITCH_CHANNEL_ID = os.getenv('TWITCH_CHANNEL_ID')
# Streamer names
STREAMER_NAMES = os.getenv('STREAMER_NAMES', '').split(',')
# Confession channels
CONFESS_CHANNEL_ID = os.getenv('CONFESS_CHANNEL_ID')
CONFESS_LOG_CHANNEL_ID = os.getenv('CONFESS_LOG_CHANNEL_ID')
# Quotes channel
QUOTES_CHANNEL_ID = os.getenv('QUOTES_CHANNEL_ID')

# Initialize bot with necessary intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

class TwitchBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=intents,
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="Twitch streams 👀"
            )
        )
        self.twitch_token = None
        self.streamer_status = {}
        self.tracked_streamers = [s.strip() for s in STREAMER_NAMES if s.strip()]

    async def setup_hook(self):
        print("Setting up bot...")
        try:
            # Add cogs first so commands are registered to the tree
            await self.add_cog(TwitchCog(self))
            print("Added Twitch cog")
            await self.add_cog(MeowCog(self))
            print("Added Meow cog")
            await self.add_cog(RemindersCog(self))
            print("Added Reminders cog")
            await self.add_cog(ConfessCog(self))
            print("Added Confess cog")
            
            # Check what commands are in the tree
            tree_commands = self.tree.get_commands()
            print(f"Commands in tree: {[cmd.name for cmd in tree_commands]}")
            
        except Exception as e:
            print(f"Error in setup_hook: {e}")

    async def close(self):
        """Clean shutdown of the bot."""
        print("Bot is shutting down...")
        
        # Cancel all running tasks
        if hasattr(self, 'check_twitch_streams') and not self.check_twitch_streams.is_cancelled():
            self.check_twitch_streams.cancel()
            print("Cancelled Twitch stream checking task")
        
        # Cancel reminder tasks in all cogs
        for cog in self.cogs.values():
            if hasattr(cog, 'check_reminders') and not cog.check_reminders.is_cancelled():
                cog.check_reminders.cancel()
                print("Cancelled reminder checking task")
        
        # Call parent close method
        await super().close()
        print("Bot shutdown complete")

    async def on_ready(self):
        """Called when the bot is ready and connected to Discord."""
        global meow_counter
        
        try:
            # Load the initial global meow count from the database
            meow_counter = sum(user.meow_count for user in UserMeowCounts.select())
            
            print(f'Logged in as {self.user}')
            print(f'Bot Client ID: {self.user.id}')
            
            # Use global command sync for multi-server support
            print("Using global command sync for multi-server support...")
            try:
                global_synced = await self.tree.sync()
                print(f"✅ Global sync successful: {len(global_synced)} commands")
                if len(global_synced) > 0:
                    print("🎉 Commands synced globally! Bot ready for any server!")
                else:
                    print("❌ Global sync failed")
            except Exception as global_error:
                print(f"❌ Global sync failed: {global_error}")
            
            # Get initial Twitch token
            if await self.get_twitch_token():
                print("Successfully obtained initial Twitch token")
                # Start Twitch checking
                self.check_twitch_streams.start()
            else:
                print("Failed to obtain initial Twitch token")
        except Exception as e:
            print(f"Error in on_ready: {e}")
            return

    async def on_member_join(self, member):
        """Welcome message for new members."""
        channel = member.guild.system_channel
        if channel is None:
            channel = member.guild.text_channels[0]

        general_roles_channel = discord.utils.get(member.guild.text_channels, name='general-roles')
        game_ping_roles_channel = discord.utils.get(member.guild.text_channels, name='game-ping-roles')
        valorant_roles_channel = discord.utils.get(member.guild.text_channels, name='valorant-roles')
        intro_channel = discord.utils.get(member.guild.text_channels, name='🎤introdox-yourself')
        rules_channel = discord.utils.get(member.guild.text_channels, name='📜rules')
        patrollers_role = discord.utils.get(member.guild.roles, name="Patrollers")

        # Add a 2-second delay before sending the message
        await asyncio.sleep(2)

        message = (
            f"⭐ ⭐ ⭐ ⭐ ⭐ \n"
            f"Welcome {member.mention}!\n\n"
            f"Check out our {rules_channel.mention if rules_channel else '#📜rules'} channel. ✅\n"
            f"You can grab roles from:\n"
            f"⭐ {general_roles_channel.mention if general_roles_channel else '#general-roles'}\n"
            f"⭐ {game_ping_roles_channel.mention if game_ping_roles_channel else '#game-ping-roles'}\n\n"
            f"Feel free to head into {intro_channel.mention if intro_channel else '#🎤introdox-yourself'} as well. 🙂\n"
            f"If you have any questions or need help, please let one of us {patrollers_role.mention if patrollers_role else '@Patrollers'} know. 🐱\n"
            f"⭐ ⭐ ⭐ ⭐ ⭐"
        )
        await channel.send(message)

    async def on_message(self, message):
        """Handle message events."""
        if message.author == self.user:
            return

        content = message.content.lower()
        global meow_counter

        # Handle meow counting
        if 'meow' in content:
            meow_count = content.count('meow')
            meow_counter += meow_count

            try:
                user_meow_count, created = UserMeowCounts.get_or_create(user_id=message.author.id)
                user_meow_count.meow_count += meow_count
                user_meow_count.save()

                response = f'Meow count: {meow_counter}'
                await message.channel.send(response)
            except Exception as e:
                print(f"Error handling meow count: {e}")

        # Handle woof/bark infractions
        if 'woof' in content or 'bark' in content:
            total_woof_bark_count = content.count('woof') + content.count('bark')

            try:
                user_infraction, created = UserInfractions.get_or_create(user_id=message.author.id)
                user_infraction.infractions += total_woof_bark_count
                user_infraction.save()

                response = f"HISS.. Yeah, don't do that. We're cat people... Your Barks and Woofs: {user_infraction.infractions}"
                await message.channel.send(response)
            except Exception as e:
                print(f"Error handling bark count: {e}")

        await self.process_commands(message)

    async def get_twitch_token(self):
        """Get Twitch access token."""
        if not TWITCH_CLIENT_ID or not TWITCH_SECRET:
            print("Error: Twitch credentials not found in .env file!")
            return None

        try:
            async with aiohttp.ClientSession() as session:
                params = {
                    'client_id': TWITCH_CLIENT_ID.strip(),
                    'client_secret': TWITCH_SECRET.strip(),
                    'grant_type': 'client_credentials'
                }
                async with session.post(
                    'https://id.twitch.tv/oauth2/token',
                    params=params
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        print(f"Failed to get Twitch token. Status: {response.status}, Response: {error_text}")
                        return None

                    data = await response.json()
                    self.twitch_token = data.get('access_token')
                    if not self.twitch_token:
                        print(f"No access token in response: {data}")
                        return None

                    print("Successfully obtained Twitch token")
                    return self.twitch_token
        except aiohttp.ClientError as e:
            print(f"HTTP error while fetching Twitch token: {e}")
        except Exception as e:
            print(f"Unexpected error while fetching Twitch token: {e}")
        return None

    @tasks.loop(minutes=5)
    async def check_twitch_streams(self):
        """Check if followed streamers are live."""
        if not self.twitch_token:
            await self.get_twitch_token()

        try:
            async with aiohttp.ClientSession() as session:
                for streamer in self.tracked_streamers:
                    if not streamer.strip():
                        continue

                    headers = {
                        'Client-ID': TWITCH_CLIENT_ID,
                        'Authorization': f'Bearer {self.twitch_token}'
                    }

                    # Get user ID
                    async with session.get(
                        'https://api.twitch.tv/helix/users',
                        params={'login': streamer.strip()},
                        headers=headers
                    ) as response:
                        if response.status == 401:  # Token expired
                            await self.get_twitch_token()
                            headers['Authorization'] = f'Bearer {self.twitch_token}'
                            continue

                        user_data = await response.json()
                        if not user_data.get('data'):
                            print(f"Streamer {streamer} not found.")
                            continue
                        user_id = user_data['data'][0]['id']

                    # Check if stream is live
                    async with session.get(
                        'https://api.twitch.tv/helix/streams',
                        params={'user_id': user_id},
                        headers=headers
                    ) as response:
                        if response.status == 401:  # Token expired
                            await self.get_twitch_token()
                            headers['Authorization'] = f'Bearer {self.twitch_token}'
                            continue

                        stream_data = await response.json()
                        is_live = bool(stream_data.get('data'))

                        # Notify only if the streamer just went live
                        if is_live and not self.streamer_status.get(streamer, False):
                            stream_info = stream_data['data'][0]
                            channel = self.get_channel(int(TWITCH_CHANNEL_ID))
                            if channel:
                                embed = discord.Embed(
                                    title=f"🔴 {streamer} is now live!",
                                    url=f"https://twitch.tv/{streamer}",
                                    description=stream_info.get('title', 'No title'),
                                    color=discord.Color.purple(),
                                    timestamp=datetime.datetime.utcnow()
                                )
                                embed.add_field(name="🎮 Game", value=stream_info.get('game_name', 'Unknown'))
                                embed.add_field(name="👥 Viewers", value=str(stream_info.get('viewer_count', 0)))
                                embed.set_thumbnail(url=stream_info.get('thumbnail_url', '').format(width=440, height=248))
                                await channel.send(
                                    content=f"🔔 **{streamer}** just went live! Check them out at https://twitch.tv/{streamer}",
                                    embed=embed
                                )

                        # Update the live status
                        self.streamer_status[streamer] = is_live

        except aiohttp.ClientError as e:
            print(f"HTTP error while checking Twitch streams: {e}")
        except Exception as e:
            print(f"Unexpected error while checking Twitch streams: {e}")

class MeowCog(commands.Cog):
    def __init__(self, bot: TwitchBot):
        super().__init__()
        self.bot = bot

    async def cog_load(self):
        guild = discord.Object(id=int(os.getenv('DISCORD_GUILD_ID')))
        # Remove explicit registration, let discord.py auto-discover
        pass

    @app_commands.command(name="top_meows")
    async def top_meows(self, interaction: discord.Interaction):
        """Check the top meow users"""
        try:
            await interaction.response.defer()
            
            all_meow_counts = UserMeowCounts.select().order_by(UserMeowCounts.meow_count.desc())

            if not all_meow_counts:
                await interaction.followup.send("No users have said 'meow' yet.")
                return

            embed = discord.Embed(
                title="🏆 Top Meow Users",
                description="Here are the top 10 meow users:",
                color=discord.Color.blue()
            )

            for i, user_meow_count in enumerate(all_meow_counts[:10], 1):
                try:
                    # Try to get guild member first (for better mention rendering)
                    guild_member = interaction.guild.get_member(user_meow_count.user_id)
                    if guild_member:
                        embed.add_field(
                            name=f"{i}. {guild_member.display_name}",
                            value=f"Meows: {user_meow_count.meow_count}",
                            inline=False
                        )
                    else:
                        # Fallback to fetching user
                        user = await self.bot.fetch_user(user_meow_count.user_id)
                        embed.add_field(
                            name=f"{i}. {user.display_name}",
                            value=f"Meows: {user_meow_count.meow_count}",
                            inline=False
                        )
                except:
                    # Final fallback - show user ID
                    embed.add_field(
                        name=f"{i}. User ID: {user_meow_count.user_id}",
                        value=f"Meows: {user_meow_count.meow_count}",
                        inline=False
                    )

            await interaction.followup.send(embed=embed)
        except Exception as e:
            print(f"Error in top_meows command: {e}")
            await interaction.followup.send("❌ An error occurred while fetching top meows.", ephemeral=True)

    @app_commands.command(name="top_barks")
    async def top_barks(self, interaction: discord.Interaction):
        """Check the top bark users"""
        try:
            await interaction.response.defer()
            
            all_infractions = UserInfractions.select().order_by(UserInfractions.infractions.desc())

            if not all_infractions:
                await interaction.followup.send("No barks recorded yet.")
                return

            embed = discord.Embed(
                title="😾 Top Bark/Woof Users",
                description="Here are the top 10 users who need to remember we're cat people:",
                color=discord.Color.red()
            )

            for i, user_infraction in enumerate(all_infractions[:10], 1):
                try:
                    # Try to get guild member first (for better mention rendering)
                    guild_member = interaction.guild.get_member(user_infraction.user_id)
                    if guild_member:
                        embed.add_field(
                            name=f"{i}. {guild_member.display_name}",
                            value=f"Barks/Woofs: {user_infraction.infractions}",
                            inline=False
                        )
                    else:
                        # Fallback to fetching user
                        user = await self.bot.fetch_user(user_infraction.user_id)
                        embed.add_field(
                            name=f"{i}. {user.display_name}",
                            value=f"Barks/Woofs: {user_infraction.infractions}",
                            inline=False
                        )
                except:
                    # Final fallback - show user ID
                    embed.add_field(
                        name=f"{i}. User ID: {user_infraction.user_id}",
                        value=f"Barks/Woofs: {user_infraction.infractions}",
                        inline=False
                    )

            await interaction.followup.send(embed=embed)
        except Exception as e:
            print(f"Error in top_barks command: {e}")
            await interaction.followup.send("❌ An error occurred while fetching top barks.", ephemeral=True)

    @app_commands.command(name="meow_count")
    async def meow_count(self, interaction: discord.Interaction):
        """Check your meow count"""
        try:
            await interaction.response.defer()
            
            user_meow_count = UserMeowCounts.get_or_none(user_id=interaction.user.id)

            if user_meow_count:
                embed = discord.Embed(
                    title="😺 Your Meow Stats",
                    description=f"You have meowed {user_meow_count.meow_count} times!",
                    color=discord.Color.green()
                )
            else:
                embed = discord.Embed(
                    title="😿 Your Meow Stats",
                    description="You haven't meowed yet! Try saying meow in chat!",
                    color=discord.Color.orange()
                )

            await interaction.followup.send(embed=embed)
        except Exception as e:
            print(f"Error in meow_count command: {e}")
            await interaction.followup.send("❌ An error occurred while fetching your meow count.", ephemeral=True)

class TwitchCog(commands.Cog):
    def __init__(self, bot: TwitchBot):
        super().__init__()
        self.bot = bot

    async def cog_load(self):
        guild = discord.Object(id=int(os.getenv('DISCORD_GUILD_ID')))
        # Remove explicit registration, let discord.py auto-discover
        pass

    @app_commands.command(name="check")
    async def check(self, interaction: discord.Interaction):
        """Check if the bot is working."""
        await interaction.response.send_message("Bot is working!", ephemeral=True)

    @app_commands.command(name="help")
    async def help(self, interaction: discord.Interaction):
        """Shows all available bot commands and their descriptions."""
        embed = discord.Embed(
            title="🐱 Meow Bot Commands",
            description="Here are all the commands you can use:",
            color=discord.Color.blue()
        )
        
        # General Commands
        embed.add_field(
            name="🔧 General Commands",
            value=(
                "`/check` - Check if the bot is working\n"
                "`/help` - Show this help message\n"
                "`/avatar [user]` - Show a user's avatar in full size\n"
                "`/clear <amount>` - Delete messages (1-100, requires Manage Messages permission)"
            ),
            inline=False
        )
        
        # Meow Commands
        embed.add_field(
            name="😺 Meow Commands",
            value=(
                "`/top_meows` - See the top 10 meow users\n"
                "`/top_barks` - See the top 10 bark/woof users\n"
                "`/meow_count` - Check your personal meow count"
            ),
            inline=False
        )
        
        # Twitch Commands
        embed.add_field(
            name="🎮 Twitch Commands",
            value=(
                "`/add_streamer <name>` - Add a streamer to track\n"
                "`/remove_streamer <name>` - Remove a streamer from tracking"
            ),
            inline=False
        )
        
        # Utility Commands
        embed.add_field(
            name="⏰ Utility Commands",
            value=(
                "`/reminder <text> <time>` - Set a reminder\n"
                "`/view_reminders` - View all your active reminders\n"
                "`/confess <message>` - Send an anonymous confession\n"
                "`/poll <question> <choices>` - Create a poll with reaction voting\n"
                "`/randomquote` - Get a random quote from the quotes channel"
            ),
            inline=False
        )
        
        # Additional Info
        embed.add_field(
            name="ℹ️ Additional Info",
            value=(
                "• Say 'meow' in chat to increase the global meow counter!\n"
                "• Saying 'woof' or 'bark' will give you infractions (we're cat people!)\n"
                "• Confessions can only be used in the confessions channel\n"
                "• Bot automatically tracks Twitch streamers and announces when they go live"
            ),
            inline=False
        )
        
        embed.set_footer(text="Meow Bot - Keeping the server purr-fectly managed! 🐾")
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="avatar")
    async def avatar(self, interaction: discord.Interaction, user: discord.User = None):
        """Show a user's avatar in full size."""
        # Default to the command user if no user is specified
        target_user = user or interaction.user
        
        # Get the avatar URL (supports animated GIFs)
        avatar_url = target_user.display_avatar.url
        
        # Create embed with the avatar
        embed = discord.Embed(
            title=f"🖼️ {target_user.display_name}'s Avatar",
            color=discord.Color.blue()
        )
        embed.set_image(url=avatar_url)
        embed.set_footer(text=f"User ID: {target_user.id}")
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="clear")
    @app_commands.describe(amount="Number of messages to delete (1-100)")
    async def clear(self, interaction: discord.Interaction, amount: int):
        """Clear/purge messages from the current channel."""
        # Check if user has manage messages permission
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("❌ You need the 'Manage Messages' permission to use this command.", ephemeral=True)
            return
        
        # Check if bot has manage messages permission
        if not interaction.guild.me.guild_permissions.manage_messages:
            await interaction.response.send_message("❌ I need the 'Manage Messages' permission to delete messages.", ephemeral=True)
            return
        
        # Validate amount
        if amount < 1 or amount > 100:
            await interaction.response.send_message("❌ Please specify a number between 1 and 100.", ephemeral=True)
            return
        
        # Defer the response since purging might take a moment
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Delete messages
            deleted = await interaction.channel.purge(limit=amount)
            
            # Send confirmation (ephemeral so it doesn't clutter chat)
            await interaction.followup.send(
                f"✅ Successfully deleted {len(deleted)} message{'s' if len(deleted) != 1 else ''}.",
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ I don't have permission to delete messages in this channel.", ephemeral=True)
        except discord.HTTPException as e:
            await interaction.followup.send(f"❌ An error occurred: {e}", ephemeral=True)
        except Exception as e:
            print(f"Error in clear command: {e}")
            await interaction.followup.send("❌ An unexpected error occurred while deleting messages.", ephemeral=True)

    @app_commands.command(name="add_streamer")
    async def add_streamer(self, interaction: discord.Interaction, streamer_name: str):
        """Add a streamer to the tracked list."""
        streamer_name = streamer_name.strip().lower()
        if not streamer_name:
            await interaction.response.send_message("Streamer name cannot be empty.", ephemeral=True)
            return

        if streamer_name in self.bot.tracked_streamers:
            await interaction.response.send_message("This streamer is already being tracked.", ephemeral=True)
            return

        # Add the streamer to the tracked list
        self.bot.tracked_streamers.append(streamer_name)

        # Respond to the user
        await interaction.response.send_message(f"✅ Now tracking streamer: **{streamer_name}**", ephemeral=True)

        # Optionally, you can immediately check and notify if the newly added streamer is live
        await self.check_and_notify_streamer(interaction, streamer_name)

    @app_commands.command(name="remove_streamer")
    async def remove_streamer(self, interaction: discord.Interaction, streamer_name: str):
        """Remove a streamer from the tracked list."""
        streamer_name = streamer_name.strip().lower()
        if not streamer_name:
            await interaction.response.send_message("Streamer name cannot be empty.", ephemeral=True)
            return

        if streamer_name not in self.bot.tracked_streamers:
            await interaction.response.send_message("This streamer is not being tracked.", ephemeral=True)
            return

        # Remove the streamer from the tracked list
        self.bot.tracked_streamers.remove(streamer_name)

        await interaction.response.send_message(f"🚫 Stopped tracking streamer: **{streamer_name}**", ephemeral=True)

    async def check_and_notify_streamer(self, interaction, streamer_name):
        """Check if a specific streamer is live and notify the channel."""
        headers = {
            'Client-ID': TWITCH_CLIENT_ID,
            'Authorization': f'Bearer {self.bot.twitch_token}'
        }

        # Get user ID
        async with aiohttp.ClientSession() as session:
            async with session.get(
                'https://api.twitch.tv/helix/users',
                params={'login': streamer_name},
                headers=headers
            ) as response:
                if response.status != 200:
                    await interaction.response.send_message("Error checking streamer status.", ephemeral=True)
                    return

                user_data = await response.json()
                if not user_data.get('data'):
                    await interaction.response.send_message("Streamer not found.", ephemeral=True)
                    return
                user_id = user_data['data'][0]['id']

            # Check if stream is live
            async with session.get(
                'https://api.twitch.tv/helix/streams',
                params={'user_id': user_id},
                headers=headers
            ) as response:
                if response.status != 200:
                    await interaction.response.send_message("Error checking stream status.", ephemeral=True)
                    return

                stream_data = await response.json()
                is_live = bool(stream_data.get('data'))

                if is_live:
                    stream_info = stream_data['data'][0]
                    channel = self.bot.get_channel(int(TWITCH_CHANNEL_ID))
                    if channel:
                        embed = discord.Embed(
                            title=f"🔴 {streamer_name} is now live!",
                            url=f"https://twitch.tv/{streamer_name}",
                            description=stream_info.get('title', 'No title'),
                            color=discord.Color.purple(),
                            timestamp=datetime.datetime.utcnow()
                        )
                        embed.add_field(name="🎮 Game", value=stream_info.get('game_name', 'Unknown'))
                        embed.add_field(name="👥 Viewers", value=str(stream_info.get('viewer_count', 0)))
                        embed.set_thumbnail(url=stream_info.get('thumbnail_url', '').format(width=440, height=248))
                        await channel.send(
                            content=f"🔔 **{streamer_name}** just went live! Check them out at https://twitch.tv/{streamer_name}",
                            embed=embed
                        )
                    await interaction.response.send_message(f"✅ Notified that **{streamer_name}** is live.", ephemeral=True)
                else:
                    await interaction.response.send_message(f"**{streamer_name}** is not live right now.", ephemeral=True)

    @app_commands.command(name="poll")
    @app_commands.describe(
        question="The poll question",
        choices="Poll choices separated by commas (max 10 choices)"
    )
    async def poll(self, interaction: discord.Interaction, question: str, choices: str):
        """Create a poll with reaction voting."""
        # Parse choices by splitting on commas and cleaning up
        choice_list = [choice.strip() for choice in choices.split(',') if choice.strip()]
        
        # Validate number of choices
        if len(choice_list) < 2:
            await interaction.response.send_message(
                "❌ You need at least 2 choices for a poll. Separate choices with commas.",
                ephemeral=True
            )
            return
        
        if len(choice_list) > 10:
            await interaction.response.send_message(
                "❌ Maximum 10 choices allowed per poll.",
                ephemeral=True
            )
            return
        
        # Number emojis for reactions (using Discord's number emojis)
        number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        
        # Create the poll embed
        embed = discord.Embed(
            title="📊 Poll",
            description=f"**{question}**",
            color=discord.Color.blue(),
            timestamp=datetime.datetime.utcnow()
        )
        
        # Add choices to embed
        choices_text = ""
        for i, choice in enumerate(choice_list):
            choices_text += f"{number_emojis[i]} {choice}\n"
        
        embed.add_field(
            name="Choices:",
            value=choices_text,
            inline=False
        )
        
        embed.set_footer(text=f"Poll created by {interaction.user.display_name}")
        
        # Send the poll
        await interaction.response.send_message(embed=embed)
        
        # Get the message to add reactions
        poll_message = await interaction.original_response()
        
        # Add reactions for each choice
        for i in range(len(choice_list)):
            try:
                await poll_message.add_reaction(number_emojis[i])
            except discord.HTTPException as e:
                print(f"Error adding reaction {number_emojis[i]}: {e}")
                # Continue adding other reactions even if one fails

    @app_commands.command(name="randomquote")
    async def randomquote(self, interaction: discord.Interaction):
        """Get a random quote from the quotes channel."""
        await interaction.response.defer()
        
        # Get the quotes channel ID from environment variables
        if not QUOTES_CHANNEL_ID:
            await interaction.followup.send(
                "❌ Quotes channel not configured. Please contact an administrator.",
                ephemeral=True
            )
            return
            
        quotes_channel = self.bot.get_channel(int(QUOTES_CHANNEL_ID))
        
        if not quotes_channel:
            await interaction.followup.send(
                "❌ Could not access the quotes channel. Make sure the bot has permission to read that channel.",
                ephemeral=True
            )
            return
        
        try:
            # Collect messages from the channel (limit to recent messages for performance)
            messages = []
            async for message in quotes_channel.history(limit=1000):
                # Only include messages from bots (the quote bot)
                if message.author.bot and (message.content or message.embeds):
                    messages.append(message)
            
            if not messages:
                await interaction.followup.send(
                    "❌ No quotes found in the quotes channel.",
                    ephemeral=True
                )
                return
            
            # Pick a random message
            import random
            random_message = random.choice(messages)
            
            # Since quotes are images, extract and display the image directly
            quote_embed = discord.Embed(
                title="🎲 Random Quote",
                color=discord.Color.blue()
            )
            
            # Check if the message has embeds with images
            if random_message.embeds:
                original_embed = random_message.embeds[0]
                
                # Set the image from the original embed
                if original_embed.image:
                    quote_embed.set_image(url=original_embed.image.url)
                elif original_embed.thumbnail:
                    quote_embed.set_image(url=original_embed.thumbnail.url)
                
                # Add any text content if available
                if original_embed.description:
                    quote_embed.description = original_embed.description
                elif original_embed.title:
                    quote_embed.description = original_embed.title
                
                # Copy color if available
                if original_embed.color:
                    quote_embed.color = original_embed.color
            
            # If there's message content, add it
            elif random_message.content:
                quote_embed.description = random_message.content
            else:
                quote_embed.description = "*(Image quote)*"
            
            # Add footer with attribution
            quote_embed.set_footer(
                text=f"From #{quotes_channel.name} • Originally by {random_message.author.display_name}",
                icon_url=random_message.author.display_avatar.url
            )
            
            # Add timestamp
            quote_embed.timestamp = random_message.created_at
            
            await interaction.followup.send(embed=quote_embed)
            
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ I don't have permission to read messages from the quotes channel.",
                ephemeral=True
            )
        except Exception as e:
            print(f"Error in randomquote command: {e}")
            await interaction.followup.send(
                "❌ An error occurred while fetching a random quote.",
                ephemeral=True
            )

class RemindersCog(commands.Cog):
    def __init__(self, bot: TwitchBot):
        super().__init__()
        self.bot = bot
        self.cal = parsedatetime.Calendar()
        self.reminders = []
        self.check_reminders.start()

    async def cog_load(self):
        guild = discord.Object(id=int(os.getenv('DISCORD_GUILD_ID')))
        # Remove explicit registration, let discord.py auto-discover
        pass

    @app_commands.command(
        name="reminder",
        description="Set a reminder. Example: /reminder text:Take a break time:in 10 minutes"
    )
    @app_commands.describe(
        text="What do you want to be reminded about?",
        time="When should I remind you? (e.g. 'in 10 minutes', '2 hours', 'next Saturday')"
    )
    async def reminder(self, interaction: discord.Interaction, text: str, time: str):
        """Set a reminder for yourself."""
        await interaction.response.defer()
        now = datetime.datetime.now()
        # Try to parse the time string
        time_struct, parse_status = self.cal.parse(time, now)
        remind_time = datetime.datetime(*time_struct[:6])
        if parse_status == 0 or remind_time <= now:
            await interaction.followup.send(
                "❌ Sorry, I couldn't understand the time frame. Try something like 'in 10 minutes', '2 hours', or 'next Saturday'.",
                ephemeral=True
            )
            return

        # Store the reminder
        self.reminders.append({
            "user_id": interaction.user.id,
            "channel_id": interaction.channel_id,
            "remind_time": remind_time,
            "text": text
        })

        # Confirm to the user (post in chat, not private)
        embed = discord.Embed(
            title="⏰ Reminder Set!",
            description=f"I'll remind {interaction.user.mention} to **{text}** at <t:{int(remind_time.timestamp())}:F>.",
            color=discord.Color.gold()
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(
        name="view_reminders",
        description="View all your active reminders"
    )
    async def view_reminders(self, interaction: discord.Interaction):
        """View all your active reminders."""
        await interaction.response.defer(ephemeral=True)
        
        # Filter reminders for the current user
        user_reminders = [r for r in self.reminders if r["user_id"] == interaction.user.id]
        
        if not user_reminders:
            await interaction.followup.send(
                "📝 You don't have any active reminders set.",
                ephemeral=True
            )
            return
        
        # Sort reminders by time (earliest first)
        user_reminders.sort(key=lambda x: x["remind_time"])
        
        embed = discord.Embed(
            title="⏰ Your Active Reminders",
            description=f"You have {len(user_reminders)} active reminder{'s' if len(user_reminders) != 1 else ''}:",
            color=discord.Color.gold()
        )
        
        for i, reminder in enumerate(user_reminders[:10], 1):  # Show max 10 reminders
            remind_time = reminder["remind_time"]
            text = reminder["text"]
            
            # Calculate time remaining
            now = datetime.datetime.now()
            time_diff = remind_time - now
            
            if time_diff.total_seconds() > 0:
                # Future reminder
                days = time_diff.days
                hours, remainder = divmod(time_diff.seconds, 3600)
                minutes, _ = divmod(remainder, 60)
                
                if days > 0:
                    time_remaining = f"in {days}d {hours}h {minutes}m"
                elif hours > 0:
                    time_remaining = f"in {hours}h {minutes}m"
                else:
                    time_remaining = f"in {minutes}m"
            else:
                # Overdue reminder (shouldn't happen but just in case)
                time_remaining = "⚠️ Overdue"
            
            embed.add_field(
                name=f"{i}. {text[:50]}{'...' if len(text) > 50 else ''}",
                value=f"📅 <t:{int(remind_time.timestamp())}:F>\n⏱️ {time_remaining}",
                inline=False
            )
        
        if len(user_reminders) > 10:
            embed.add_field(
                name="📝 Note",
                value=f"Showing first 10 reminders. You have {len(user_reminders) - 10} more.",
                inline=False
            )
        
        embed.set_footer(text="Reminders are checked every 30 seconds")
        
        await interaction.followup.send(embed=embed, ephemeral=True)

    @tasks.loop(seconds=30)
    async def check_reminders(self):
        now = datetime.datetime.now()
        to_remove = []
        for reminder in self.reminders:
            if now >= reminder["remind_time"]:
                user = self.bot.get_user(reminder["user_id"])
                channel = self.bot.get_channel(reminder["channel_id"])
                embed = discord.Embed(
                    title="🔔 Reminder!",
                    description=f"You asked to be reminded: **{reminder['text']}**",
                    color=discord.Color.purple(),
                    timestamp=datetime.datetime.utcnow()
                )
                if channel:
                    await channel.send(content=f"{user.mention}", embed=embed)
                elif user:
                    try:
                        await user.send(embed=embed)
                    except:
                        pass
                to_remove.append(reminder)
        for r in to_remove:
            self.reminders.remove(r)

    @check_reminders.before_loop
    async def before_reminders(self):
        await self.bot.wait_until_ready()

class ConfessionButtons(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)  # Persistent view
        self.bot = bot

    @discord.ui.button(label="Submit a confession!", style=discord.ButtonStyle.blurple, emoji="💭")
    async def submit_confession(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Button to submit a new confession"""
        # Check if we're in the confessions channel
        if str(interaction.channel_id) != str(CONFESS_CHANNEL_ID):
            await interaction.response.send_message(
                "❌ You can only submit confessions in the confessions channel.",
                ephemeral=True
            )
            return
        
        # Create a modal for confession input
        modal = ConfessionModal(self.bot)
        await interaction.response.send_modal(modal)

class ConfessionModal(discord.ui.Modal):
    def __init__(self, bot):
        super().__init__(title="Submit Anonymous Confession")
        self.bot = bot

    confession_text = discord.ui.TextInput(
        label="Your Confession",
        placeholder="Type your anonymous confession here...",
        style=discord.TextStyle.paragraph,
        max_length=2000,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        # Get the confession cog to access the counter methods
        confess_cog = self.bot.get_cog('ConfessCog')
        if not confess_cog:
            await interaction.response.send_message("❌ Error: Confession system not available.", ephemeral=True)
            return

        # Increment confession counter and save to database
        current_count = confess_cog.increment_confession_count()
        
        # Send anonymous confession to the confessions channel
        confess_channel = self.bot.get_channel(int(CONFESS_CHANNEL_ID))
        if confess_channel:
            embed = discord.Embed(
                title=f"💭 Anonymous Confession (#{current_count})",
                description=self.confession_text.value,
                color=discord.Color.blurple()
            )
            
            # Add the buttons to the confession embed
            view = ConfessionButtons(self.bot)
            await confess_channel.send(embed=embed, view=view)
        else:
            await interaction.response.send_message(
                "❌ Confessions channel not found.",
                ephemeral=True
            )
            return

        # Log confession with username to the log channel
        log_channel = self.bot.get_channel(int(CONFESS_LOG_CHANNEL_ID))
        if log_channel:
            log_embed = discord.Embed(
                title=f"Confession Log (#{current_count})",
                description=self.confession_text.value,
                color=discord.Color.red()
            )
            log_embed.set_footer(text=f"User: {interaction.user} ({interaction.user.id})")
            await log_channel.send(embed=log_embed)

        await interaction.response.send_message(
            "✅ Your confession has been sent anonymously.",
            ephemeral=True
        )

class ConfessCog(commands.Cog):
    def __init__(self, bot: TwitchBot):
        super().__init__()
        self.bot = bot
        # Load confession count from database on startup
        self.load_confession_count()

    def load_confession_count(self):
        """Load the current confession count from database."""
        try:
            # Get or create the confession counter record
            counter, created = ConfessionCounter.get_or_create(id=1, defaults={'count': 0})
            self.confession_count = counter.count
            print(f"Loaded confession count: {self.confession_count}")
        except Exception as e:
            print(f"Error loading confession count: {e}")
            self.confession_count = 0

    def increment_confession_count(self):
        """Increment and save the confession count to database."""
        try:
            self.confession_count += 1
            # Update the database
            counter, created = ConfessionCounter.get_or_create(id=1, defaults={'count': self.confession_count})
            counter.count = self.confession_count
            counter.save()
            return self.confession_count
        except Exception as e:
            print(f"Error updating confession count: {e}")
            return self.confession_count

    async def cog_load(self):
        guild = discord.Object(id=int(os.getenv('DISCORD_GUILD_ID')))
        # Remove explicit registration, let discord.py auto-discover
        pass

    @app_commands.command(
        name="confess",
        description="Send an anonymous confession to the confessions channel."
    )
    @app_commands.describe(
        message="What do you want to confess?"
    )
    async def confess(self, interaction: discord.Interaction, message: str):
        # Only allow in the confessions channel
        if str(interaction.channel_id) != str(CONFESS_CHANNEL_ID):
            await interaction.response.send_message(
                "❌ You can only use this command in the confessions channel.",
                ephemeral=True
            )
            return

        # Increment confession counter and save to database
        current_count = self.increment_confession_count()
        
        # Send anonymous confession to the confessions channel
        confess_channel = self.bot.get_channel(int(CONFESS_CHANNEL_ID))
        if confess_channel:
            embed = discord.Embed(
                title=f"💭 Anonymous Confession (#{current_count})",
                description=message,
                color=discord.Color.blurple()
            )
            # Add the buttons to the confession embed
            view = ConfessionButtons(self.bot)
            await confess_channel.send(embed=embed, view=view)
        else:
            await interaction.response.send_message(
                "❌ Confessions channel not found.",
                ephemeral=True
            )
            return

        # Log confession with username to the log channel
        log_channel = self.bot.get_channel(int(CONFESS_LOG_CHANNEL_ID))
        if log_channel:
            log_embed = discord.Embed(
                title=f"Confession Log (#{current_count})",
                description=message,
                color=discord.Color.red()
            )
            log_embed.set_footer(text=f"User: {interaction.user} ({interaction.user.id})")
            await log_channel.send(embed=log_embed)

        await interaction.response.send_message(
            "✅ Your confession has been sent anonymously.",
            ephemeral=True
        )

if __name__ == "__main__":
    if not DISCORD_BOT_TOKEN:
        print("Error: DISCORD_BOT_TOKEN not found in .env file!")
    else:
        try:
            print("Starting bot...")
            bot = TwitchBot()
            asyncio.run(bot.start(DISCORD_BOT_TOKEN))
        except KeyboardInterrupt:
            print("\n🛑 Bot stopped by user (Ctrl+C)")
        except discord.LoginFailure as e:
            print(f"Failed to log in: {e}")
        except Exception as e:
            print(f"An error occurred while starting the bot: {e}")
        finally:
            print("Bot process ended")
