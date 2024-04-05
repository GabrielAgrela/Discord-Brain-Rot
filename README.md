
# Discord Brain Rot

A versatile Discord bot that serves as a personal butler, playing sound effects based on user-defined events and more brain rot.

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

4. Create the users data file for the users in your server:

   - Create a JSON file named `Data/Users.json` and define the user-specific sound events. For example:

     ```json
     {
       "user1#1111": 
       [
         {
           "event": "leave",
           "sound": "XFART"
         },
         {
           "event": "join",
           "sound": "MEXI"
         }
       ],
       "user2#2222": 
       [
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

   Run the sound scrapper by executing the following command:

    ```
    python SoundScrapper.py
    ```

## Usage

The Discord Brain Rot bot listens for voice state updates in the connected Discord server and plays the corresponding sound effects based on user-defined events.

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

  Replace `"user#1234"` with the user's Discord username and discriminator, and `"sound"` with one of the available sounds available in `Data/soundsDB.csv`.

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

  Replace `"user#1234"` with the user's Discord username and discriminator, and `"sound"` with one of the available sounds available in `Data/soundsDB.csv`.

- All available commands are found by typing '/'.

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.


## License

[MIT](https://choosealicense.com/licenses/mit/)
