"""
Integration tests for the console application
"""

import unittest
import subprocess
import sys
import os
from pathlib import Path
import tempfile


class TestConsoleApplication(unittest.TestCase):
    """Test the console application without requiring ML dependencies"""

    def setUp(self):
        """Set up test environment"""
        self.script_path = Path(__file__).parent.parent / "transcribe_batch.py"
        self.assertTrue(self.script_path.exists(), "Script file not found")

    def run_script(self, args, expect_success=True):
        """Helper to run the script with given arguments"""
        cmd = [sys.executable, str(self.script_path)] + args
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", env=env, timeout=30)

        if expect_success and result.returncode != 0:
            self.fail(
                f"Command failed: {' '.join(cmd)}\n"
                f"Exit code: {result.returncode}\n"
                f"Stdout: {result.stdout}\n"
                f"Stderr: {result.stderr}"
            )

        return result

    def test_help_command(self):
        """Test that help command works"""
        result = self.run_script(["--help"], expect_success=False)
        # Help exits with code 0 but argparse uses SystemExit
        self.assertIn("Meeting Companion Console Tool", result.stdout)

    def test_version_command(self):
        """Test version command"""
        result = self.run_script(["--version"], expect_success=False)
        self.assertIn("Meeting Companion", result.stderr or result.stdout)

    def test_examples_command(self):
        """Test examples command"""
        result = self.run_script(["--examples"])
        self.assertIn("Usage Examples", result.stdout)
        self.assertIn("meeting-companion", result.stdout)

    def test_models_command(self):
        """Test models info command"""
        result = self.run_script(["--models"])
        self.assertIn("Available Whisper Models", result.stdout)
        self.assertIn("tiny", result.stdout)
        self.assertIn("large-v3", result.stdout)

    def test_no_args_welcome(self):
        """Test welcome message when no arguments provided"""
        result = self.run_script([])
        self.assertIn("Welcome", result.stdout)
        self.assertIn("Quick Start", result.stdout)

    def test_run_help(self):
        """Test run command help"""
        result = self.run_script(["run", "--help"], expect_success=False)
        self.assertIn("Batch Transcription", result.stdout)

    def test_file_help(self):
        """Test file command help"""
        result = self.run_script(["file", "--help"], expect_success=False)
        self.assertIn("Single File", result.stdout)

    def test_notes_help(self):
        """Test notes command help"""
        result = self.run_script(["notes", "--help"], expect_success=False)
        self.assertIn("Notes Mode", result.stdout)

    def test_notes_command_with_plain_text_transcript(self):
        """Test notes command using a plain text transcript without ML dependencies."""
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "meeting.txt"
            output_dir = Path(tmp) / "out"
            transcript.write_text(
                "Agenda: roadmap review. Action item: Sam will send notes. Decision: keep the release date.",
                encoding="utf-8",
            )
            result = self.run_script(
                [
                    "notes",
                    "--transcript",
                    str(transcript),
                    "--output",
                    str(output_dir),
                    "--summarizer",
                    "none",
                ]
            )
            self.assertIn("Notes generated successfully", result.stdout)
            self.assertTrue(any(path.suffix == ".md" for path in output_dir.iterdir()))
            self.assertTrue(any(path.suffix == ".json" for path in output_dir.iterdir()))

    def test_notes_command_with_vtt_transcript(self):
        """Test notes command using a Teams VTT transcript without ML dependencies."""
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "meeting.vtt"
            output_dir = Path(tmp) / "out"
            transcript.write_text(
                "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\n<v Alex>Agenda: kickoff\n\n"
                "00:00:03.000 --> 00:00:05.000\nDecision: move ahead\n",
                encoding="utf-8",
            )
            result = self.run_script(
                [
                    "notes",
                    "--transcript",
                    str(transcript),
                    "--output",
                    str(output_dir),
                    "--summarizer",
                    "none",
                ]
            )
            self.assertIn("Source:", result.stdout)
            self.assertTrue(any(path.suffix == ".md" for path in output_dir.iterdir()))
            self.assertTrue(any(path.suffix == ".json" for path in output_dir.iterdir()))

    def test_invalid_command(self):
        """Test handling of invalid commands"""
        result = self.run_script(["invalid"], expect_success=False)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
