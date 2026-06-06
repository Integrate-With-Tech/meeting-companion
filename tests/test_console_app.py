"""
Integration tests for the console application
"""

import unittest
import subprocess
import sys
import os
from pathlib import Path


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
        self.assertIn("Video Transcription Console Tool", result.stdout)

    def test_version_command(self):
        """Test version command"""
        result = self.run_script(["--version"], expect_success=False)
        self.assertIn("Video Transcribe", result.stderr or result.stdout)

    def test_examples_command(self):
        """Test examples command"""
        result = self.run_script(["--examples"])
        self.assertIn("Usage Examples", result.stdout)
        self.assertIn("video-transcribe", result.stdout)

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

    def test_invalid_command(self):
        """Test handling of invalid commands"""
        result = self.run_script(["invalid"], expect_success=False)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
