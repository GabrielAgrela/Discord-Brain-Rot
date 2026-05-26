"""
Tests for static frontend assets (JavaScript, CSS, etc.).

Ensures static assets are syntactically valid so they don't break in the browser.
"""

import os
import subprocess
import pytest

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bot", "web", "static")

JS_FILES = [
    "speech_training.js",
]


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

    @pytest.mark.parametrize("filename", JS_FILES)
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

    @pytest.mark.parametrize("filename", JS_FILES)
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

    @pytest.mark.parametrize("filename", JS_FILES)
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

    @pytest.mark.parametrize("filename", JS_FILES)
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

    @pytest.mark.parametrize("filename", JS_FILES)
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
