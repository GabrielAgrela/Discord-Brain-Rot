# 🧠 Discord Brain Rot

A feature-rich Discord bot that transforms your server into an interactive soundboard experience with AI-powered commentary, real-time voice keyword detection, and automatic sound scraping.

---

## ✨ Features

### 🔊 **Soundboard**
- **10,000+ sounds** automatically scraped from MyInstants (PT, BR, US)
- Smart fuzzy search with autocomplete suggestions
- Playback controls: speed, volume, reverse, progress bar
- Similar sounds suggestions using AI audio embeddings
- Personal sound lists and favorites

### 🗣️ **Text-to-Speech & Voice Cloning**
- **Google TTS**: English, Portuguese, Spanish, French, German, Russian, Arabic, Chinese
- **ElevenLabs voices**: Ventura, Costa, Tyson (custom character voices)
- **Speech-to-Speech (STS)**: Convert any sound to a different voice
- **Voice isolation**: Extract vocals from audio

### 🎤 **Real-time Voice Detection**
- **Vosk STT engine** for real-time speech recognition
- Keyword triggers that play sounds or lists
- Confidence-based filtering to prevent false positives

### 🤖 **AI Commentary**
- Automatic AI commentary using **Gemini** via OpenRouter
- Listens to voice conversations and provides humorous Portuguese commentary
- Configurable cooldowns and trigger phrases

### 🎬 **Brain Rot Content**
- Random Subway Surfers gameplay clips
- Family Guy clips  
- Slice All gameplay clips
- Sends video directly to chat while audio plays

### 📊 **Analytics & Web Interface**
- Flask-powered web dashboard
- Activity heatmaps (day × hour)
- Top users and sounds leaderboards
- Timeline charts and recent activity feed
- Remote sound playback queue
- **Status Icons**:
    - 🤯: Time until next random periodic sound
    - 👂🏻: AI Commentary (Ventura) cooldown status
    - 🔍: Next MyInstants sound scraper run

### ⚡ **Event System**
- Custom sounds for user join/leave events
- Per-user sound assignments
- "On This Day" - hear what played exactly one year ago

---

## 🏗️ Architecture

```
bot/
├── commands/       # Discord slash commands (Cogs)
├── downloaders/    # Sound scrapers (MyInstants, yt-dlp)
├── models/         # Data models/entities
├── repositories/   # Database access layer (SQLite)
├── services/       # Business logic layer
└── ui/             # Discord UI components (Views, Buttons, Modals)
```

The project follows **SOLID principles** with a clean separation of concerns:
- **Repository Pattern** for all database access
- **Service Layer** for business logic
- **Dependency Injection** throughout

---

## 🚀 Quick Start (Docker)

The fastest way to get the bot running is using **Docker Compose**.

### 1. Prerequisites
- [Docker](https://docs.docker.com/get-docker/)
- [Docker Compose](https://docs.docker.com/compose/install/)

### 2. Setup
1. **Clone the repository**
   ```bash
   git clone https://github.com/GabrielAgrela/Discord-Brain-Rot.git
   cd Discord-Brain-Rot
   ```

2. **Configure your environment**
   Create a `.env` file in the root directory:
   ```env
   # Required
   DISCORD_BOT_TOKEN=your-discord-bot-token

   # ElevenLabs TTS (Optional)
   EL_key=your-elevenlabs-api-key
   EL_voice_id_pt=...
   
   # AI Commentary (Optional)
   OPENROUTER_API_KEY=your-openrouter-api-key
   ```

3. **Launch**
   ```bash
   # Build and start services in the background
   docker-compose up --build -d
   ```

### 3. Usage
- **Discord Bot**: Once the container is running and logs show "Bot is ready", it will respond to commands in your server.
- **Web Dashboard**: Accessible at [http://localhost:8080](http://localhost:8080).

### 4. Management
```bash
# View logs
docker-compose logs -f

# Stop and remove containers
docker-compose down
```

---

---

## 📋 Commands

### Sound Playback
| Command | Description |
|---------|-------------|
| `/toca [sound]` | Play a sound (use `random` for random) |
| `/toca [sound] speed:[0.5-3.0] volume:[0.1-5.0] reverse:[true/false]` | Play with effects |
| `/lastsounds [n]` | Show last N downloaded sounds |
| `/change [current] [new]` | Rename a sound |

### Text-to-Speech
| Command | Description |
|---------|-------------|
| `/tts [message] [language]` | Generate TTS audio |
| `/sts [sound] [character]` | Convert sound to different voice |
| `/isolate [sound]` | Isolate vocals from audio |

### Sound Lists
| Command | Description |
|---------|-------------|
| `/createlist [name]` | Create a personal sound list |
| `/addtolist [sound] [list]` | Add sound to a list |
| `/removefromlist [sound] [list]` | Remove sound from list |
| `/deletelist [name]` | Delete a list |
| `/showlist [name]` | Display list with play buttons |

### Keywords
| Command | Description |
|---------|-------------|
| `/keyword add [word] [action]` | Add trigger keyword |
| `/keyword remove [word]` | Remove keyword |
| `/keyword list` | Show all keywords |

### Events
| Command | Description |
|---------|-------------|
| `/addevent [user] [join/leave] [sound]` | Set entrance/exit sound |
| `/listevents [user]` | Show user's event sounds |
| `/onthisday` | Hear what played one year ago today |

### Statistics
| Command | Description |
|---------|-------------|
| `/top users [n] [days]` | Top users leaderboard |
| `/top sounds [n] [days]` | Top sounds leaderboard |

### Brain Rot
| Command | Description |
|---------|-------------|
| `/subwaysurfers` | Random Subway Surfers clip |
| `/familyguy` | Random Family Guy clip |
| `/slice` | Random Slice All clip |

### Admin
| Command | Description |
|---------|-------------|
| `/reboot` | Reboot host machine |
| `/lastlogs [n]` | View service logs |
| `/commands` | Show recent bot commands from logs |

---

## 📱 Adding Sounds via DM

Send the bot a DM with a video URL:
```
https://www.tiktok.com/@user/video/123456789
```

Optional parameters:
```
<url> [time_limit_seconds] [custom_filename]
```

Supported platforms: **TikTok**, **Instagram Reels**, **YouTube**

---

## 🧪 Testing

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=bot --cov-report=term
```

---

## 🗂️ Project Structure

```
Discord-Brain-Rot/
├── PersonalGreeter.py    # Main entry point
├── WebPage.py            # Flask web interface
├── config.py             # Centralized configuration
├── bot/                  # Core bot package
│   ├── commands/         # Slash command Cogs
│   ├── services/         # Business logic
│   ├── repositories/     # Data access
│   ├── models/           # Domain entities
│   ├── ui/               # Discord components
│   └── downloaders/      # Sound scrapers
├── Sounds/               # Sound files (auto-populated)
├── Data/                 # Video clips (SubwaySurfers, FamilyGuy, etc.)
├── Downloads/            # Temporary download directory
├── Logs/                 # Daily log files
└── tests/                # Test suite
```

---

## 🔧 Configuration

Key settings in `config.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `DEFAULT_SPEED` | 1.0 | Default playback speed |
| `DEFAULT_VOLUME` | 1.0 | Default volume |
| `MIN_SPEED` / `MAX_SPEED` | 0.5 / 3.0 | Speed limits |
| `MIN_VOLUME` / `MAX_VOLUME` | 0.1 / 5.0 | Volume limits |
| `DEFAULT_MUTE_DURATION` | 1800 | Mute duration (seconds) |

---

## 📄 License

[MIT](https://choosealicense.com/licenses/mit/)

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Follow the architecture patterns in the codebase
4. Write tests for new functionality
5. Submit a Pull Request

---

<p align="center">
  <i>Made with 🧠 and lots of brain rot</i>
</p>
