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
        """Verify keyword scan confidence chips show percentage certainty text."""
        filepath = os.path.join(STATIC_DIR, filename)
        assert os.path.exists(filepath), f"JS file not found: {filepath}"
        with open(filepath, "r", encoding="utf-8") as fh:
            content = fh.read()
        # The chip should use explicit null/undefined guard, not truthiness
        assert "keyword_confidence !== undefined" in content
        # The chip should display "N% certainty" (not just bare "N%")
        assert "% certainty</span>" in content
        # The title should reference "Chapada certainty"
        assert "Chapada certainty" in content

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
