# Meow Bot

Meow Bot is a fun Discord bot we made in our spare time to track "meow" counts for cat lovers and yell at people who bark.
It also manages Twitch stream notifications and provides a welcome message for Discord servers.

Any questions can be sent to my Discord at: fireflyxserenity

## Features
- Tracks how many times users say "meow" in chat.
- Issues playful infractions for "woof" or "bark" messages.
- Notifies when tracked Twitch streamers go live.
- Customizable welcome messages for new members.

## Getting Started
1. Clone the repository:
   ```bash
   git clone https://github.com/fireflyxserenity/meowbot.git
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Create a `.env` file in the project directory and add the following:
   ```
   DISCORD_BOT_TOKEN=your_discord_bot_token
   TWITCH_CLIENT_ID=your_twitch_client_id
   TWITCH_SECRET=your_twitch_secret
   TWITCH_CHANNEL_ID=your_discord_channel_id
   STREAMER_NAMES=streamer1,streamer2,streamer3
   DISCORD_GUILD_ID=your_discord_guild_id
   ```

4. Run the bot:
   ```bash
   python meow_bot_real_supreme.py
   ```

## Support Me
If you enjoy using Meow Bot and want to support its development, consider donating on Ko-fi:
[![Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/fireflyxserenity)

## License
This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Author
Created by [fireflyxserenity](https://github.com/fireflyxserenity).
