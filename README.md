# Discord Brain Rot

A versatile Discord bot that serves as a personal butler, playing sound effects based on user-defined events and more brain rot.

## Prerequisites

- Python 3.7 or higher installed
- [FFmpeg](https://ffmpeg.org/) installed and added to the system's PATH environment variable
- A Discord bot token obtained from the Discord Developer Portal
- An ElevenLabs API Key (optional, for STS, voice isolation, and some TTS features)
- Google Chrome (or Chromium) and the corresponding ChromeDriver installed.

## Installation

1.  Clone this repository to your local machine.
2.  Install the required dependencies by running the following command:
    ```bash
    pip install -r requirements.txt
    ```
3.  Create a file named `.env` in the project directory and add the following environment variables:

    ```dotenv
    DISCORD_BOT_TOKEN=<your-discord-bot-token>
    FFMPEG_PATH=<path-to-ffmpeg-executable> # e.g., C:\\ffmpeg\\bin\\ffmpeg.exe or /usr/bin/ffmpeg
    CHROMEDRIVER_PATH=<path-to-chromedriver> # e.g., C:\\chromedriver\\chromedriver.exe or /usr/bin/chromedriver
    # Optional: ElevenLabs API Key and Voice IDs for advanced features, examples:
    EL_key=<your-elevenlabs-api-key>
    EL_voice_id_pt=<your-elevenlabs-pt-voice-id>
    EL_voice_id_en=<your-elevenlabs-en-voice-id>
    EL_voice_id_costa=<your-elevenlabs-costa-voice-id>
    ```
    *Note: The bot uses a database file (`database.db`). It should be created automatically on the first run if it doesn't exist, based on the `Database.py` setup.*

4.  Run the bot by executing the following command:
    ```bash
    python PersonalGreeter.py
    ```
    The bot will automatically handle sound downloading and database management in the background.

## Usage

Interact with the bot using slash commands (`/`) in your Discord server.

### Key Features & Commands

*   **Sound Playback:**
    *   `/toca [message]` : Play a sound by name. Use the autocomplete suggestions or type 'random'. Supports finding similar sounds.
    *   `/subwaysurfers`, `/familyguy`: Play specific themed sounds/videos.
*   **Text-to-Speech (TTS):**
    *   `/tts [message] [language]`: Generate TTS using Google Translate or ElevenLabs (depending on language/setup). Supports languages like `en`, `pt`, `br`, `es`, `fr`, `de`, `ar`, `ru`, `ch`.
*   **Speech-to-Speech (STS):** (Requires ElevenLabs API Key)
    *   `/sts [sound] [char]`: Convert an existing sound to a different voice (e.g., 'tyson', 'ventura', 'costa').
*   **Voice Isolation:** (Requires ElevenLabs API Key)
    *   `/isolate [sound]`: Attempt to isolate vocals from a sound file.
*   **Sound Management:**
    *   `/change [current] [new]`: Rename a sound file.
    *   `/lastsounds [number]`: List the most recently downloaded sounds.
*   **Sound Lists:**
    *   `/createlist [list_name]`: Create a personal sound list.
    *   `/addtolist [sound] [list_name]`: Add a sound to a list.
    *   `/removefromlist [sound] [list_name]`: Remove a sound from one of your lists.
    *   `/deletelist [list_name]`: Delete one of your lists.
    *   `/showlist [list_name]`: Display a specific sound list with playback buttons.
    *   `/mylists`: Show all lists created by you.
    *   `/showlists`: Show all lists created by anyone.
*   **Event Sounds:**
    *   `/addevent [username] [event] [sound]`: Assign a sound to play when a specific user joins or leaves a voice channel.
    *   `/listevents [username]`: List the join/leave sounds assigned to a user (defaults to you).
*   **Statistics:**
    *   `/top [option] [number] [numberdays]`: Show leaderboards for top played sounds or top users ('users' or 'sounds').

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

## License

[MIT](https://choosealicense.com/licenses/mit/)
