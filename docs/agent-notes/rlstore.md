# Rocket League Store Agent Notes

Read this when changing `/rlstore`, Rocket League store fetching, store image cards, RL store notifications, or related templates.

## Data Source

- `/rlstore` uses `https://rlshop.gg/__data.json` for the featured shop and `https://rlshop.gg/<shop_id>/__data.json` for other active shops.
- Do not assume every active shop with `Type == "Featured"` uses the root `__data.json` node. The homepage node maps only to the shop whose `activeShops[].Name` matches decoded `shopName`; other featured-type sections still need their own `/<shop_id>/__data.json` fetch.
- Payloads are SvelteKit/devalue-encoded: decode node `0` for `activeShops`/`lastUpdated` and node `1` for the selected shop body.
- The linked `dank/rlapi` repo is the upstream behind `rlshop.gg`; using `rlshop.gg` avoids adding Epic auth/PsyNet session handling for read-only shop browsing.

## Discord UI And Cards

- The interactive RL store UI sends file attachments, not embeds, for the normal path.
- `RocketLeagueStoreView` renders image cards through `ImageGeneratorService.generate_rl_store_card()`.
- Page buttons must replace the attached file using `attachments=[]` plus `file=...` when editing.
- Pages are pre-rendered up front via `RocketLeagueStoreView.prepare_all_pages()`. Keep pagination tile-based and cache image bytes so direct-jump buttons do not re-render on every press.
- Paint badges in `templates/rl_store_card.html` are driven by per-paint style tokens from `RocketLeagueStoreView`; do not hard-code one badge color.
- `RocketLeagueStoreView` uses `timeout=None` so page-jump buttons do not expire after five minutes unless explicitly requested.
- Store cards can exceed simple `rows * constant height` estimates when item names wrap. Keep Selenium measuring the real `.store-board` bounds and resizing the viewport before `Page.captureScreenshot` to avoid clipping.

## Notifications

- Notifications include shared Merc-status text from `RocketLeagueStoreService.build_merc_status_text()`. Scheduled notifications and `/rlstore` both notify the configured target user about that result.
- Notifications and `/rlstore` include the source URL from `RocketLeagueStoreService.build_source_url_text()`, wrapped as `<https://rlshop.gg>` so Discord does not unfurl it.
- The daily notification in `BackgroundService` is a one-send-per-day catch-up window after configured reset+5 time, default `19:05 UTC`; it is not exact-minute-only.
- Dedupe is stored through `ActionRepository` with action `rlstore_daily_notification_sent`, so restarts later that day still send once instead of skipping.
- The daily notification prefers a text channel named `botrl`; if absent, it falls back to the configured bot text channel via `MessageService.get_bot_channel()`.
