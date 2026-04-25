"""Tests for bot/services/year_review_video.py - YearReviewVideoService."""

from pathlib import Path


class TestYearReviewVideoService:
    """Tests for year review GIF generation helpers."""

    def test_build_remotion_props_uses_year_review_stats(self, tmp_path):
        """Remotion props should mirror the existing /yearreview stats payload."""
        from bot.services.year_review_video import YearReviewVideoService

        service = YearReviewVideoService(output_dir=str(tmp_path))
        stats = {
            "total_plays": 42,
            "requested_plays": 30,
            "random_plays": 8,
            "favorite_plays": 4,
            "unique_sounds": 12,
            "top_sounds": [("airhorn.mp3", 10), ("hello_there.mp3", 7)],
            "most_active_day": "Friday",
            "most_active_hour": 23,
            "first_sound": "airhorn.mp3",
            "first_sound_date": "2025-01-03 12:00:00",
            "last_sound": "hello_there.mp3",
            "last_sound_date": "2025-12-30 20:00:00",
            "total_voice_hours": 5.5,
            "longest_streak": 3,
            "total_active_days": 9,
            "user_rank": 2,
            "total_users": 8,
        }

        props = service._build_remotion_props(
            username="gabi",
            display_name="Gabi",
            year=2025,
            stats=stats,
            avatar_url="https://cdn.example/avatar.png",
        )

        assert props["displayName"] == "Gabi"
        assert props["year"] == 2025
        assert props["headlineStats"][0] == {"label": "plays", "value": "42", "tone": "blurple"}
        assert props["rankText"] == "Rank #2 of 8"
        assert props["topSounds"] == [{"name": "airhorn", "plays": 10}, {"name": "hello there", "plays": 7}]
        assert props["timing"]["peakHour"] == "23:00"
        assert props["journey"]["firstDate"] == "2025-01-03"
        assert props["avatarUrl"] == "https://cdn.example/avatar.png"

    def test_render_year_review_gif_uses_remotion_then_gif_conversion(self, tmp_path, monkeypatch):
        """The renderer should invoke the Remotion stage before GIF conversion."""
        from bot.services.year_review_video import YearReviewVideoService

        service = YearReviewVideoService(output_dir=str(tmp_path))
        progress = []
        calls = []
        stats = {
            "total_plays": 5,
            "requested_plays": 3,
            "random_plays": 1,
            "favorite_plays": 1,
            "unique_sounds": 4,
            "top_sounds": [("clip.mp3", 3)],
            "total_voice_hours": 1,
            "total_active_days": 2,
        }

        def fake_render(props_path, mp4_path):
            calls.append(("render", props_path, mp4_path))
            assert props_path.exists()
            payload = props_path.read_text(encoding="utf-8")
            assert '"displayName": "Tester"' in payload
            mp4_path.write_bytes(b"fake mp4")

        def fake_convert(mp4_path, output_stem, max_bytes, progress_callback):
            calls.append(("convert", mp4_path, output_stem, max_bytes))
            assert mp4_path.exists()
            gif_path = tmp_path / f"{output_stem}-gif.gif"
            gif_path.write_bytes(b"GIF89a")
            return gif_path, False

        monkeypatch.setattr(service, "_render_remotion_mp4", fake_render)
        monkeypatch.setattr(service, "_convert_mp4_to_gif", fake_convert)

        result = service.render_year_review_gif(
            username="tester",
            display_name="Tester",
            year=2025,
            stats=stats,
            max_bytes=7 * 1024 * 1024,
            progress_callback=lambda percent, label: progress.append((percent, label)),
        )

        assert Path(result.path).exists()
        assert result.path.endswith(".gif")
        assert result.size_bytes > 0
        assert result.size_bytes < 7 * 1024 * 1024
        assert progress[0][0] == 8
        assert progress[-1][0] == 96
        assert calls[0][0] == "render"
        assert calls[1][0] == "convert"

    def test_build_weekly_wrapped_props_uses_weekly_stats(self, tmp_path):
        """Weekly wrapped props should reuse the Remotion composition with weekly labels."""
        from bot.services.year_review_video import YearReviewVideoService

        service = YearReviewVideoService(output_dir=str(tmp_path))
        props = service._build_weekly_wrapped_props(
            guild_name="Chaos Server",
            days=7,
            stats={
                "year": 2026,
                "total_plays": 55,
                "active_users": 4,
                "voice_hours": 12.5,
                "new_sounds": 3,
                "top_sounds": [("weekly_clip.mp3", 11)],
                "top_users": [("gabi", 20)],
                "top_voice_users": [{"username": "sopustos", "total_hours": 5}],
                "peak_window": "Fri 22:00",
                "favorite_day": "Friday",
            },
        )

        assert props["commandLabel"] == "/weeklywrapped"
        assert props["title"] == "Chaos Server weekly wrapped"
        assert props["headlineStats"][0] == {"label": "plays", "value": "55", "tone": "blurple"}
        assert props["topSounds"] == [{"name": "weekly clip", "plays": 11}]
        assert props["timing"]["peakHour"] == "Fri 22:00"
        assert props["journey"]["firstSound"] == "gabi"
        assert props["journey"]["latestSound"] == "sopustos"

    def test_render_remotion_mp4_builds_cli_command(self, tmp_path, monkeypatch):
        """The MP4 stage should call Remotion's local CLI with props."""
        from bot.services.year_review_video import YearReviewVideoService

        trailer_dir = tmp_path / "trailer"
        remotion_bin = trailer_dir / "node_modules" / ".bin" / "remotion"
        remotion_bin.parent.mkdir(parents=True)
        remotion_bin.write_text("#!/bin/sh\n", encoding="utf-8")
        entry = tmp_path / "index.tsx"
        entry.write_text("export {}", encoding="utf-8")
        service = YearReviewVideoService(
            output_dir=str(tmp_path / "out"),
            trailer_dir=str(trailer_dir),
            composition_entry=str(entry),
        )
        commands = []

        def fake_run(command, cwd, timeout):
            commands.append((command, cwd, timeout))

        monkeypatch.setattr(service, "_run_command", fake_run)
        service._render_remotion_mp4(
            props_path=tmp_path / "props.json",
            mp4_path=tmp_path / "review.mp4",
        )

        command, cwd, _timeout = commands[0]
        assert command[:4] == [str(remotion_bin), "render", str(entry), "YearReview"]
        assert "--codec=h264" in command
        assert "--pixel-format=yuv420p" in command
        assert cwd == trailer_dir
