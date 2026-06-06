"""
Tests for transcript-to-notes helpers.
"""

from datetime import date
from pathlib import Path
import tempfile
import unittest

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.meeting_notes import generate_notes_payload, load_transcript_payload, write_notes_exports  # noqa: E402


class TestLoadTranscriptPayload(unittest.TestCase):
    def test_loads_plain_text_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "meeting.txt"
            transcript.write_text("Agenda review. Action item: send update.", encoding="utf-8")
            payload = load_transcript_payload(transcript)
            self.assertEqual(payload["source_type"], "plain_text")
            self.assertIn("Agenda review.", payload["full_text"])

    def test_loads_vtt_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "meeting.vtt"
            transcript.write_text(
                "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\n<v Alex>Agenda review\n",
                encoding="utf-8",
            )
            payload = load_transcript_payload(transcript)
            self.assertEqual(payload["source_type"], "teams_native")
            self.assertEqual(payload["segments"][0].speaker, "Alex")
            self.assertEqual(payload["full_text"], "Agenda review")


class TestGenerateNotesPayload(unittest.TestCase):
    def test_generates_structured_notes_without_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "weekly-sync.txt"
            transcript.write_text(
                "Agenda: review roadmap. Action item: Maya will send the deck. Decision: ship on Friday.",
                encoding="utf-8",
            )
            payload = generate_notes_payload(
                transcript_path=transcript,
                meeting_title="Weekly Sync",
                summarizer="none",
                summary_max=8,
            )
            self.assertEqual(payload.title, "Weekly Sync")
            self.assertEqual(payload.meeting_date, date.fromtimestamp(transcript.stat().st_mtime))
            self.assertIn("review roadmap.", payload.structured_notes["agenda"][0].lower())
            self.assertIn("ship on friday", payload.structured_notes["decisions"][0].lower())
            self.assertIn("maya will send the deck", payload.structured_notes["action_items"][0].lower())
            self.assertIn("## Agenda", payload.markdown_notes)
            self.assertIn("## Action Items", payload.markdown_notes)
            self.assertIn("## Decisions", payload.markdown_notes)

    def test_rejects_empty_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "empty.txt"
            transcript.write_text("   \n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Transcript is empty"):
                generate_notes_payload(
                    transcript_path=transcript,
                    meeting_title="Empty Meeting",
                    summarizer="none",
                    summary_max=8,
                )


class TestWriteNotesExports(unittest.TestCase):
    def test_writes_markdown_and_json_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "meeting.txt"
            transcript.write_text(
                "Agenda: roadmap review. Action item: send recap. Decision: keep current release date.",
                encoding="utf-8",
            )
            output_dir = Path(tmp) / "notes"
            result = write_notes_exports(
                transcript_path=transcript,
                output_dir=output_dir,
                meeting_title="Roadmap Review",
                summarizer="none",
                summary_max=8,
            )
            filenames = sorted(path.name for path in result["files"])
            self.assertEqual(len(filenames), 2)
            self.assertTrue(any(name.endswith(".md") for name in filenames))
            self.assertTrue(any(name.endswith(".json") for name in filenames))


if __name__ == "__main__":
    unittest.main()
