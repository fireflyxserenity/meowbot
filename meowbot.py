"""
Meow Bot
Author: fireflyxserenity
Description: A Discord bot that tracks "meow" counts, manages Twitch stream notifications, 
             and provides fun interactions for Discord servers.
GitHub: https://github.com/fireflyxserenity/meowbot
Ko-fi: https://ko-fi.com/fireflyxserenity
License: MIT License
"""
import os
import discord
from discord.ext import commands, tasks
from discord import app_commands
from dotenv import load_dotenv
import datetime
import asyncio
import aiohttp
from peewee import SqliteDatabase, Model, IntegerField

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

# Connect to the database and create tables
db.connect()
db.create_tables([UserInfractions, UserMeowCounts], safe=True)

# Global counter
meow_counter = 0

# Get credentials from environment variables
DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
TWITCH_CLIENT_ID = os.getenv('TWITCH_CLIENT_ID')
TWITCH_SECRET = os.getenv('TWITCH_SECRET')
TWITCH_CHANNEL_ID = os.getenv('TWITCH_CHANNEL_ID')
STREAMER_NAMES = os.getenv('STREAMER_NAMES', '').split(',')

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
        """Set up the bot's command tree and cogs."""
        print("Setting up bot...")
        try:
            # Add the Twitch cog first
            await self.add_cog(TwitchCog(self))
            print("Added Twitch cog")

            # Add the Meow cog
            await self.add_cog(MeowCog(self))
            print("Added Meow cog")

            # Force sync commands for a specific guild (faster for testing)
            guild = discord.Object(id=int(os.getenv('DISCORD_GUILD_ID')))
            print("Syncing commands for guild...")
            await self.tree.sync(guild=guild)
            print("Successfully synced commands for guild")

            # Uncomment the following line to sync globally (slower to propagate)
            # await self.tree.sync()
            # print("Successfully synced commands globally")
        except Exception as e:
            print(f"Error in setup_hook: {e}")

    async def on_ready(self):
        """Called when the bot is ready and connected to Discord."""
        global meow_counter
        
        try:
            # Load the initial global meow count from the database
            meow_counter = sum(user.meow_count for user in UserMeowCounts.select())
            
            print(f'Logged in as {self.user}')
            print(f'Bot Client ID: {self.user.id}')
            
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

        rules_channel = discord.utils.get(member.guild.text_channels, name='📜rules')
        intro_channel = discord.utils.get(member.guild.text_channels, name='🎤introdox-yourself')

        # Add a 2-second delay before sending the message
        await asyncio.sleep(2)

        message = (
            f"⭐ ⭐ ⭐ ⭐ ⭐ \n"
            f"Welcome {member.mention}!\n\n"
            f"Check out our {rules_channel.mention if rules_channel else '#📜rules'} channel. ✅\n"
            f"Feel free to introduce yourself in {intro_channel.mention if intro_channel else '#🎤introdox-yourself'}! 🙂\n"
            f"If you have any questions or need help, please reach out to @Mods. 🐱\n"
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

class TwitchCog(commands.Cog):
    def __init__(self, bot: TwitchBot):
        self.bot = bot

    @app_commands.command(name="check")
    async def check(self, interaction: discord.Interaction):
        """Check which tracked streamers are currently live"""
        try:
            # Send immediate response
            await interaction.response.send_message("🔍 Checking streams...")
            
            # Check streams
            live_streams = await self.check_streams()
            
            if not live_streams:
                await interaction.edit_original_response(content="😴 No tracked streamers are currently live.")
                return
                
            embed = discord.Embed(
                title="🎮 Live Streams",
                description="Currently live tracked streamers:",
                color=discord.Color.green()
            )
            
            for streamer, data in live_streams.items():
                embed.add_field(
                    name=f"🔴 {streamer}",
                    value=f"Playing: {data['game']}\nViewers: {data['viewers']}\n[Watch on Twitch](https://twitch.tv/{streamer})",
                    inline=False
                )
            
            await interaction.edit_original_response(content=None, embed=embed)
        except Exception as e:
            print(f"Error in check command: {e}")
            try:
                await interaction.edit_original_response(content="❌ An error occurred while checking streams.")
            except:
                await interaction.followup.send("❌ An error occurred while checking streams.", ephemeral=True)

    @app_commands.command(name="add_streamer")
    async def add_streamer(self, interaction: discord.Interaction, streamer_name: str):
        """Add a new streamer to track (Patrollers only)"""
        # Check if the user has the "Patrollers" role using the role ID
        patrollers_role_id = 1064433364997775361
        if patrollers_role_id not in [role.id for role in interaction.user.roles]:
            await interaction.response.send_message("❌ You need the 'Patrollers' role to use this command.", ephemeral=True)
            return

        try:
            # Send immediate response
            await interaction.response.send_message(f"Adding streamer: {streamer_name}...")
            
            # Check if streamer exists on Twitch
            if not self.bot.twitch_token:
                await self.bot.get_twitch_token()
                
            headers = {
                'Client-ID': TWITCH_CLIENT_ID,
                'Authorization': f'Bearer {self.bot.twitch_token}'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    'https://api.twitch.tv/helix/users',
                    params={'login': streamer_name},
                    headers=headers
                ) as response:
                    if response.status != 200:
                        await interaction.edit_original_response(content="❌ Failed to verify streamer. Please check the name and try again.")
                        return
                        
                    user_data = await response.json()
                    if not user_data.get('data'):
                        await interaction.edit_original_response(content=f"❌ Could not find Twitch user: {streamer_name}")
                        return
            
            # Add the streamer to the bot's tracked streamers
            if streamer_name not in self.bot.tracked_streamers:
                self.bot.tracked_streamers.append(streamer_name)
                
                # Update the .env file
                env_path = '.env'
                try:
                    with open(env_path, 'r') as file:
                        lines = file.readlines()
                    
                    with open(env_path, 'w') as file:
                        for line in lines:
                            if line.startswith('STREAMER_NAMES='):
                                file.write(f'STREAMER_NAMES={",".join(self.bot.tracked_streamers)}\n')
                            else:
                                file.write(line)
                    
                    await interaction.edit_original_response(content=f"✅ Successfully added {streamer_name} to tracked streamers!")
                except Exception as e:
                    print(f"Error updating .env file: {e}")
                    await interaction.edit_original_response(content="❌ Failed to update streamer list in configuration file.")
            else:
                await interaction.edit_original_response(content=f"❌ {streamer_name} is already being tracked!")
        except Exception as e:
            print(f"Error in add_streamer command: {e}")
            await interaction.followup.send("❌ An error occurred while adding the streamer.", ephemeral=True)

    @app_commands.command(name="remove_streamer")
    async def remove_streamer(self, interaction: discord.Interaction, streamer_name: str):
        """Remove a streamer from tracking (Patrollers only)"""
        # Check if the user has the "Patrollers" role using the role ID
        patrollers_role_id = 1064433364997775361
        if patrollers_role_id not in [role.id for role in interaction.user.roles]:
            await interaction.response.send_message("❌ You need the 'Patrollers' role to use this command.", ephemeral=True)
            return

        try:
            # Send immediate response
            await interaction.response.send_message(f"Removing streamer: {streamer_name}...")
            
            # Check if streamer is in the list
            if streamer_name in self.bot.tracked_streamers:
                self.bot.tracked_streamers.remove(streamer_name)
                
                # Update the .env file
                env_path = '.env'
                try:
                    with open(env_path, 'r') as file:
                        lines = file.readlines()
                    
                    with open(env_path, 'w') as file:
                        for line in lines:
                            if line.startswith('STREAMER_NAMES='):
                                file.write(f'STREAMER_NAMES={",".join(self.bot.tracked_streamers)}\n')
                            else:
                                file.write(line)
                    
                    await interaction.edit_original_response(content=f"✅ Successfully removed {streamer_name} from tracked streamers!")
                except Exception as e:
                    print(f"Error updating .env file: {e}")
                    await interaction.edit_original_response(content="❌ Failed to update streamer list in configuration file.")
            else:
                await interaction.edit_original_response(content=f"❌ {streamer_name} is not being tracked!")
        except Exception as e:
            print(f"Error in remove_streamer command: {e}")
            await interaction.followup.send("❌ An error occurred while removing the streamer.", ephemeral=True)

    async def check_streams(self):
        """Check which tracked streamers are currently live."""
        if not self.bot.twitch_token:
            await self.bot.get_twitch_token()

        try:
            async with aiohttp.ClientSession() as session:
                live_streamers = {}
                error_count = 0
                
                for streamer in self.bot.tracked_streamers:
                    streamer = streamer.strip()
                    if not streamer:
                        continue
                        
                    try:
                        headers = {
                            'Client-ID': TWITCH_CLIENT_ID,
                            'Authorization': f'Bearer {self.bot.twitch_token}'
                        }
                        
                        async with session.get(
                            'https://api.twitch.tv/helix/streams',
                            params={'user_login': streamer},
                            headers=headers
                        ) as response:
                            if response.status == 401:
                                print("Token expired, getting new token...")
                                await self.bot.get_twitch_token()
                                headers['Authorization'] = f'Bearer {self.bot.twitch_token}'
                                continue
                                
                            stream_data = await response.json()
                            
                            if stream_data.get('data'):
                                stream_info = stream_data['data'][0]
                                live_streamers[streamer] = {
                                    'name': streamer,
                                    'title': stream_info.get('title', 'No title'),
                                    'game': stream_info.get('game_name', 'Unknown'),
                                    'viewers': stream_info.get('viewer_count', 0),
                                    'thumbnail': stream_info.get('thumbnail_url', '').format(width=440, height=248)
                                }
                    except asyncio.TimeoutError:
                        print(f"Timeout while checking {streamer}")
                        error_count += 1
                    except Exception as e:
                        print(f"Error checking {streamer}: {e}")
                        error_count += 1
                
                if live_streamers:
                    return live_streamers
                else:
                    status = "😴 None of the tracked streamers are currently live."
                    if error_count > 0:
                        status += f"\n⚠️ ({error_count} errors occurred while checking)"
                    return None

        except Exception as e:
            print(f"Error checking streams: {e}")
            return None

class MeowCog(commands.Cog):
    def __init__(self, bot: TwitchBot):
        self.bot = bot

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
                    user = await self.bot.fetch_user(user_meow_count.user_id)
                    embed.add_field(
                        name=f"{i}. {user.name}",
                        value=f"Meows: {user_meow_count.meow_count}",
                        inline=False
                    )
                except:
                    continue

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
                    user = await self.bot.fetch_user(user_infraction.user_id)
                    embed.add_field(
                        name=f"{i}. {user.name}",
                        value=f"Barks/Woofs: {user_infraction.infractions}",
                        inline=False
                    )
                except:
                    continue

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

if __name__ == "__main__":
    if not DISCORD_BOT_TOKEN:
        print("Error: DISCORD_BOT_TOKEN not found in .env file!")
    else:
        try:
            print("Starting bot...")
            bot = TwitchBot()
            asyncio.run(bot.start(DISCORD_BOT_TOKEN))
        except discord.LoginFailure as e:
            print(f"Failed to log in: {e}")
        except Exception as e:
            print(f"An error occurred while starting the bot: {e}")