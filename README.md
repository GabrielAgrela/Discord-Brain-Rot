
# Discord Personal Butler

A versatile Discord bot that serves as a personal butler, playing sound effects based on user-defined events.

## Prerequisites

Before running the bot, make sure you have the following:

- Python 3.7 or higher installed
- [FFmpeg](https://ffmpeg.org/) installed and added to the system's PATH environment variable
- Discord bot token obtained from the Discord Developer Portal

## Installation

1. Clone this repository to your local machine.
2. Install the required dependencies by running the following command:

   ```
   pip install -r requirements.txt
   ```

3. Create a file named `.env` in the project directory and add the following environment variables:

   ```
   DISCORD_BOT_TOKEN=<your-discord-bot-token>
   FFMPEG_PATH=<path-to-ffmpeg-executable>
   ```

   Additionally, for each sound key defined in `Data/Sounds.json`, add an environment variable with the format `SOUND_<sound_key>=<sound_file_path>`. For example:

   ```
   SOUND_ALERT=/path/to/alert.mp3
   SOUND_GOODBYE=/path/to/goodbye.mp3
   SOUND_FART=/path/to/fart.mp3
   ...
   ```

4. Create the necessary data files:

   - Create a JSON file named `Data/Sounds.json` and define the available sound keys. For example:

     ```json
     [
       "ALERT",
       "GOODBYE",
       "FART",
       "ALLAH",
       "XFART",
       "MEXI",
       "HELLO"
     ]
     ```

   - Create a JSON file named `Data/Users.json` and define the user-specific sound events. For example:

     ```json
     {
       "user1#1111": [
         {
           "event": "leave",
           "sound": "XFART"
         },
         {
           "event": "join",
           "sound": "MEXI"
         }
       ],
       "user2#2222": [
         {
           "event": "join",
           "sound": "HELLO"
         }
       ]
     }
     ```

5. Run the bot by executing the following command:

   ```
   python PersonalGreeter.py
   ```

## Usage

The Discord Personal Butler bot listens for voice state updates in the connected Discord server and plays the corresponding sound effects based on user-defined events.

- To trigger a sound effect when a user joins a voice channel, add an entry in `Data/Users.json` for the specific user:

  ```json
  {
    "user#1234": [
      {
        "event": "join",
        "sound": "SOUND_KEY"
      }
    ]
  }
  ```

  Replace `"user#1234"` with the user's Discord username and discriminator, and `"SOUND_KEY"` with one of the available sound keys defined in `Data/Sounds.json`.

- To trigger a sound effect when a user leaves a voice channel, add an entry in `Data/Users.json` for the specific user:

  ```json
  {
    "user#1234": [
      {
        "event": "leave",
        "sound": "SOUND_KEY"
      }
    ]
  }
  ```

  Replace `"user#1234"` with the user's Discord username and discriminator, and `"SOUND_KEY"` with one of the available sound keys defined in `Data/Sounds.json`.

- To stop the bot and disconnect it from all voice channels, use the command prefix `!` followed by `stop`:

  ```
  !stop
  ```

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

Please make sure to update tests as appropriate.

## License

[MIT](https://choosealicense.com/licenses/mit/)
