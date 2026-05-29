"""
Tests for static frontend assets (JavaScript, CSS, etc.).

Ensures static assets are syntactically valid so they don't break in the browser.
"""

import os
import subprocess
import pytest

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bot", "web", "static")

ALL_JS_FILES = [
    "soundboard.js",
    "speech_training.js",
]

SPEECH_TRAINING_ONLY = ["speech_training.js"]


def _node_available():
    """Check whether Node.js is available on PATH."""
    try:
        subprocess.run(
            ["node", "--version"],
            capture_output=True,
            timeout=10,
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


@pytest.mark.skipif(not _node_available(), reason="Node.js not available on PATH")
class TestJavaScriptSyntax:
    """Verify JavaScript files are parseable."""

    @pytest.mark.parametrize("filename", ALL_JS_FILES)
    def test_syntax(self, filename):
        filepath = os.path.join(STATIC_DIR, filename)
        assert os.path.exists(filepath), f"JS file not found: {filepath}"
        result = subprocess.run(
            ["node", "--check", filepath],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, (
            f"Syntax error in {filename}:\n{result.stderr}"
        )

    @pytest.mark.parametrize("filename", ["soundboard.js"])
    def test_control_room_event_driven(self, filename):
        """Verify control room polls network every 1s regardless of SSE health with local progress tick."""
        filepath = os.path.join(STATIC_DIR, filename)
        assert os.path.exists(filepath), f"JS file not found: {filepath}"
        with open(filepath, "r", encoding="utf-8") as fh:
            content = fh.read()
        # Local progress tick function must exist
        assert "function _controlRoomProgressTick" in content
        # isSseHealthy() must exist for other paths
        assert "isSseHealthy()" in content
        # Reset on network fetch
        assert "_controlRoomLocalElapsed = null" in content
        # _scheduleStatusPoll must call refreshControlRoomStatus().then(_scheduleStatusPoll)
        # without an isSseHealthy() skip — verified by the pattern existing
        assert "refreshControlRoomStatus().then(_scheduleStatusPoll)" in content
        # MUST NOT have an SSE-healthy early-return branch in _scheduleStatusPoll
        # The old pattern checked isSseHealthy and returned early.
        # Ensure there's no "if (isSseHealthy())" before _controlRoomProgressTick
        # inside _scheduleStatusPoll.
        schedule_poll_body = content[content.index("function _scheduleStatusPoll"):]
        schedule_poll_body = schedule_poll_body[:schedule_poll_body.index("function _scheduleWebCtrlPoll")]
        # The old skip pattern used: if (isSseHealthy()) { ... _controlRoomProgressTick(); _scheduleStatusPoll(); return; }
        # Verify this pattern is NOT present in _scheduleStatusPoll.
        assert "if (isSseHealthy())" not in schedule_poll_body, (
            "_scheduleStatusPoll must not skip network fetch when SSE is healthy"
        )

    @pytest.mark.parametrize("filename", ["soundboard.js"])
    def test_actions_table_refresh_paths(self, filename):
        """Verify actions table refreshes via SSE events only (no local post-play fallbacks)."""
        filepath = os.path.join(STATIC_DIR, filename)
        assert os.path.exists(filepath), f"JS file not found: {filepath}"
        with open(filepath, "r", encoding="utf-8") as fh:
            content = fh.read()
        # SSE payloads arrive as {type, data: {...}}; handlers must extract
        # the nested payload before checking fields.
        assert "typeof data.data === 'object'" in content
        # playback_queued handler checks both action and play_action on the
        # extracted detail object (backward-compatible with top-level too).
        assert "detail.action || detail.play_action" in content
        # control_room_changed handler triggers delayed actions refresh
        assert "detail.reason === 'playback_started'" in content
        # Authoritative actions_changed helper cancels/skips delayed fallbacks
        assert "_scheduleAuthoritativeActionsRefresh" in content
        # Delayed fallback helper for playback_queued / playback_started
        assert "_scheduleActionsFallbackRefresh" in content
        # Fallback skips when actions_changed already arrived since scheduling
        assert "_lastActionsChangedAt" in content
        # No local post-play fallbacks — tables are strictly SSE-driven
        assert "actionsPostPlay" not in content, (
            "Local post-play fallback actionsPostPlay must be removed"
        )
        assert "actionsPostPlaySimilar" not in content, (
            "Local post-play similar fallback actionsPostPlaySimilar must be removed"
        )
        # Old standalone debounce keys removed — replaced by coordinated helpers
        assert "actionsDelayedPlayback" not in content, (
            "actionsDelayedPlayback debounce key must be removed"
        )
        assert "actionsDelayed'" not in content, (
            "actionsDelayed debounce key must be removed"
        )

    @pytest.mark.parametrize("filename", ["soundboard.js"])
    def test_tables_are_strictly_sse_driven(self, filename):
        """Verify tables are strictly SSE-driven: no passive polling, no reconnect resync fallback."""
        filepath = os.path.join(STATIC_DIR, filename)
        assert os.path.exists(filepath), f"JS file not found: {filepath}"
        with open(filepath, "r", encoding="utf-8") as fh:
            content = fh.read()
        # No connected handler table resync (no scheduleSseRefresh with resync* keys)
        assert "scheduleSseRefresh('resyncActions'" not in content, (
            "SSE connected handler must NOT schedule fetchActions resync"
        )
        assert "scheduleSseRefresh('resyncFavorites'" not in content, (
            "SSE connected handler must NOT schedule fetchFavorites resync"
        )
        assert "scheduleSseRefresh('resyncAllSounds'" not in content, (
            "SSE connected handler must NOT schedule fetchAllSounds resync"
        )
        # No _scheduleTablePoll function (passive table polling removed)
        assert "function _scheduleTablePoll" not in content, (
            "_scheduleTablePoll passive table polling must be removed"
        )
        # No _tableFetchers[_tablePollIndex]() passive table fetcher
        assert "_tableFetchers[_tablePollIndex]()" not in content, (
            "Passive table fetcher invocation must be removed"
        )
        # No startup call to _scheduleTablePoll
        assert "_scheduleTablePoll();" not in content, (
            "Startup _scheduleTablePoll() call must be removed"
        )
        # SSE event handlers must still exist
        assert "es.addEventListener('actions_changed'" in content, (
            "SSE actions_changed handler must exist"
        )
        assert "es.addEventListener('sounds_changed'" in content, (
            "SSE sounds_changed handler must exist"
        )

    @pytest.mark.parametrize("filename", ["soundboard.js"])
    def test_system_monitor_constant_1s_visible(self, filename):
        """Verify system monitor polls at 1/s when visible."""
        filepath = os.path.join(STATIC_DIR, filename)
        assert os.path.exists(filepath), f"JS file not found: {filepath}"
        with open(filepath, "r", encoding="utf-8") as fh:
            content = fh.read()
        # Old paranoia constants removed
        assert "SYS_MON_SUMMARY_PARANOIA_MS" not in content
        assert "SYS_MON_DETAILED_PARANOIA_MS" not in content
        assert "SYS_MON_HIDDEN_PARANOIA_MS" not in content
        assert "sseAdjustedInterval" not in content
        # New constant present
        assert "SYS_MON_VISIBLE_MS" in content
        assert "SYS_MON_HIDDEN_MS" in content
        assert "SYSTEM_MONITOR_CPU_HISTORY_SECONDS = 60" in content
        assert "renderSystemMonitorHoverChart" in content
        assert "updateSystemMonitorChartReadout" in content

    @pytest.mark.parametrize("filename", SPEECH_TRAINING_ONLY)
    def test_keyword_confidence_wording(self, filename):
        """Verify keyword scan confidence chips show keyword name and percentage."""
        filepath = os.path.join(STATIC_DIR, filename)
        assert os.path.exists(filepath), f"JS file not found: {filepath}"
        with open(filepath, "r", encoding="utf-8") as fh:
            content = fh.read()
        # The chip should use explicit null/undefined guard, not truthiness
        assert "keyword_confidence !== undefined" in content
        # The chip should show keyword name + middot + percentage (not bare "% certainty")
        assert " &middot; " in content
        assert "'%</span>'" in content or '"%</span>"' in content
        # The title should use escaped keyword reference, not hardcoded "Chapada certainty"
        assert "certainty:" in content
        assert "Chapada certainty" not in content

    @pytest.mark.parametrize("filename", SPEECH_TRAINING_ONLY)
    def test_transcript_job_functions_exist(self, filename):
        """Verify transcribe button handling functions are present."""
        filepath = os.path.join(STATIC_DIR, filename)
        assert os.path.exists(filepath), f"JS file not found: {filepath}"
        with open(filepath, "r", encoding="utf-8") as fh:
            content = fh.read()
        assert "runTranscriptJob" in content
        assert "pollTranscriptJob" in content
        assert "onTranscriptDone" in content
        assert "onTranscriptError" in content
        assert "cancelTranscriptPoll" in content
        assert "transcribeBtn" in content

    @pytest.mark.parametrize("filename", SPEECH_TRAINING_ONLY)
    def test_trim_keyword_uses_persisted_timing(self, filename):
        """Verify Trim kw button uses both scan (keyword_*) and persisted (detected_*) timing fields."""
        filepath = os.path.join(STATIC_DIR, filename)
        assert os.path.exists(filepath), f"JS file not found: {filepath}"
        with open(filepath, "r", encoding="utf-8") as fh:
            content = fh.read()
        # Helper that resolves timing from either source
        assert "getClipKeywordTiming" in content
        # Must reference persisted fields so Trim kw appears on normal list rows
        assert "detected_start_seconds" in content
        assert "detected_end_seconds" in content
        # Must also still reference scan-only fields for scan-mode rows
        assert "keyword_start_seconds" in content
        assert "keyword_end_seconds" in content
        # Scan-mode-only comment should be removed
        assert "scan results only" not in content

    @pytest.mark.parametrize("filename", SPEECH_TRAINING_ONLY)
    def test_trim_updates_row_in_place(self, filename):
        """Verify trimClipToKeyword updates the row in-place with cache-busting instead of full reload."""
        filepath = os.path.join(STATIC_DIR, filename)
        assert os.path.exists(filepath), f"JS file not found: {filepath}"
        with open(filepath, "r", encoding="utf-8") as fh:
            content = fh.read()
        # In-place row update helper must exist
        assert "function updateTrimmedClipRow" in content
        # Audio source must use cache-busting query param after trim
        assert "audio?v=" in content
        # Must call audio.load() after replacing source
        assert "audio.load()" in content
        # Must pause audio before replacing source
        assert "audio.pause()" in content
        # Must reset quick progress after trim
        assert "resetQuickProgress(audio)" in content
        # Normal-mode full loadClips() reload should not be the primary path;
        # it should only appear as a fallback inside an else block
        assert "loadClips();" in content

    @pytest.mark.parametrize("filename", SPEECH_TRAINING_ONLY)
    def test_passive_refresh_suppresses_reveal_animation(self, filename):
        """Verify speech-training passive refreshes do not replay list reveal animations."""
        js_path = os.path.join(STATIC_DIR, filename)
        css_path = os.path.join(STATIC_DIR, "web.css")
        assert os.path.exists(js_path), f"JS file not found: {js_path}"
        assert os.path.exists(css_path), f"CSS file not found: {css_path}"

        with open(js_path, "r", encoding="utf-8") as fh:
            js_content = fh.read()
        with open(css_path, "r", encoding="utf-8") as fh:
            css_content = fh.read()

        assert "renderUsers({ animate: !opts.passive })" in js_content
        assert "renderClips(data.items || [], { animate: !opts.passive })" in js_content
        assert "dataset-no-reveal" in js_content
        assert ".dataset-user-list:not(.dataset-no-reveal) .dataset-user-item" in css_content
        assert ".dataset-clips:not(.dataset-no-reveal) .dataset-clip" in css_content
        assert ".dataset-clips:not(.dataset-no-reveal) .dataset-empty" in css_content
