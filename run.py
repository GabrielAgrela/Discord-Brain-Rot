import sys
import argparse
import os

# Add src to python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def run_bot():
    from src.bot.main import bot, Config
    if Config.DISCORD_BOT_TOKEN:
        bot.run(Config.DISCORD_BOT_TOKEN)
    else:
        print("Error: DISCORD_BOT_TOKEN not found.")

def run_web():
    from src.web.app import app
    app.run(debug=True, host='0.0.0.0', port=8080)

def run_scraper():
    from src.scraper.service import ScraperService
    ScraperService().run()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Discord Brain Rot components")
    parser.add_argument('component', choices=['bot', 'web', 'scraper'], help="Component to run")

    args = parser.parse_args()

    if args.component == 'bot':
        run_bot()
    elif args.component == 'web':
        run_web()
    elif args.component == 'scraper':
        run_scraper()
