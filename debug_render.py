from bot.services.image_generator import ImageGeneratorService
import os

# Initialize service
service = ImageGeneratorService()

# Mock data matching the screenshot
sound_name = "Gigachad"
requester = "startup"
play_count = 3
duration = "0:10"
download_date = "Aug 30, 2025"
is_tts = False
sts_char = None

# Replicate the logic inside generate_sound_card to get the HTML
with open(service.template_path, 'r', encoding='utf-8') as f:
    template = f.read()

import base64
def encode_svg(svg_data):
    return base64.b64encode(svg_data.encode('utf-8')).decode('utf-8')

svg_volume = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="#8b5cf6"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg>'

speaker_icon = encode_svg(svg_volume)

data = {
    "sound_name": sound_name,
    "requester": requester,
    "speaker_icon": speaker_icon,
    # Add other mock icons as empty strings for simplicity or copy from service
    "icon_timer": "",
    "icon_chart": "",
    "icon_calendar": "",
    "icon_folder": "",
    "icon_heart": "",
    "card_class": "",
    "play_count": play_count,
    "duration": duration,
    "download_date": download_date,
    "lists": "default",
    "favorited_by": "gabi",
    "similarity": None,
    "quote": None
}

# Render
rendered_html = service._render_template(template, data)

print("--- RENDERED HTML SNIPPET ---")
# Print the title section to see what happened
start_idx = rendered_html.find('<div class="title-section">')
end_idx = rendered_html.find('</div>', start_idx) + 6
print(rendered_html[start_idx:end_idx])

print("\n--- FULL HTML LENGTH ---")
print(len(rendered_html))

print("\n--- CHECKS ---")
if "PHN2" in rendered_html:
    print("Found Base64 string in HTML!")
    # Check context
    idx = rendered_html.find("PHN2")
    print(f"Context: {rendered_html[idx-20:idx+50]}")
else:
    print("Base64 string NOT found (unexpected if passing icon)")
