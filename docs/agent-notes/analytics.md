# Analytics And Wrapped Agent Notes

Read this when changing action analytics, `/top`, on-this-day/year-review queries, voice activity tracking, `/yearreview`, or `/weeklywrapped`.

## Action Analytics

- For action rows representing sound play, store the sound database `id` in `actions.target`, not the filename.
- Stats, top, year-review, and on-this-day queries join `actions.target` back to `sounds.id`; filename targets disappear from those analytics.
- Standardize list playback under action `play_from_list`.
- Do not invent per-list action names such as `play_random_from_<list_name>` unless every stats query is updated.

## Voice Activity

- Voice analytics for `/top` and year-review depend on `voice_activity` session rows written from `on_voice_state_update` in `PersonalGreeter.py`.
- AFK transitions are session boundaries for active channels only; joining AFK is not counted as active voice time.
- Voice session rows store `member.name`, not `name#discriminator`, to match existing stats queries.

## Year Review And Weekly Wrapped

- `/yearreview` and `/weeklywrapped` send compact animated GIFs generated from a Remotion MP4 render.
- `YearReviewVideoService` prepares props from stats payloads, invokes the local Remotion CLI from `trailer/node_modules/.bin/remotion`, then converts/compresses with ffmpeg.
- `/yearreview` should edit the original progress response into a file-only GIF message instead of sending a separate captioned follow-up.
- Keep the animated top-sounds scene capped to four rows unless the layout is redesigned; five rows clip at `960x540`.
- Keep the Remotion background visually seamless with Discord chat (`#313338`) and avoid decorative confetti/equalizer/glow layers.
- The Docker bot image must include Node.js because Remotion's CLI is a Node executable. If it fails with `env: 'node': No such file or directory`, rebuild/recreate the bot image; restart alone is not enough.
- Runtime Remotion source lives under `bot/remotion_year_review/` because `bot/` is volume-mounted into the Docker bot container. Do not move required runtime composition files into unmounted `trailer/src` unless deploy flow changes.
- Keep Remotion/GIF generation in the service layer and Discord progress edits in `StatsCog`; the renderer should not import Discord APIs or query repositories directly.
- GIF output is capped by the guild upload limit with a conservative margin, or by `YEAR_REVIEW_GIF_MAX_MB` / `WEEKLY_WRAPPED_GIF_MAX_MB`. If the GIF exceeds the cap, fall back to the text embed.
