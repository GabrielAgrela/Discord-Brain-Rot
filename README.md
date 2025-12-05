# Discord Brain Rot

A structured Discord bot project.

## Structure

- `src/bot`: Discord bot logic (Cogs, Services).
- `src/web`: Web interface (Flask).
- `src/scraper`: Sound scraping logic.
- `src/common`: Shared configuration and database logic.

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Configure environment variables in `.env`.

3. Run the project:
   ```bash
   # Run the bot
   python run.py bot

   # Run the web interface
   python run.py web

   # Run the scraper
   python run.py scraper
   ```
