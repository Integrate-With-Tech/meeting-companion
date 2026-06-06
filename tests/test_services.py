"""
Tests for the services package (transcription, summarization, artifacts).
"""

import tempfile
import types
import unittest
from unittest.mock import patch
from pathlib import Path
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestTranscriptionService(unittest.TestCase):
    """Tests for services.transcription that don't require ML dependencies."""

    def test_srt_timestamp(self):
        from services.transcription import srt_timestamp

        self.assertEqual(srt_timestamp(0.0), "00:00:00,000")
        self.assertEqual(srt_timestamp(1.5), "00:00:01,500")
        self.assertEqual(srt_timestamp(61.123), "00:01:01,122")
        self.assertEqual(srt_timestamp(3661.456), "01:01:01,456")
        self.assertEqual(srt_timestamp(0.999), "00:00:00,999")
        self.assertEqual(srt_timestamp(7322.0 + 0.1), "02:02:02,100")

    def test_create_progress_bar_zero_total(self):
        from services.transcription import create_progress_bar

        bar = create_progress_bar(0, 0)
        self.assertIn("?", bar)

    def test_create_progress_bar_progress(self):
        from services.transcription import create_progress_bar

        bar = create_progress_bar(50, 100)
        self.assertIn("50%", bar)

    def test_create_progress_bar_complete(self):
        from services.transcription import create_progress_bar

        bar = create_progress_bar(100, 100)
        self.assertIn("100%", bar)

    def test_load_whisper_uses_cached_model_class(self):
        import services.transcription as transcription

        class FakeWhisperModel:
            def __init__(self, model_size, compute_type):
                self.model_size = model_size
                self.compute_type = compute_type

        fake_module = types.SimpleNamespace(WhisperModel=FakeWhisperModel)
        original_model_class = transcription._WM
        try:
            transcription._WM = None
            with patch.dict(sys.modules, {"faster_whisper": fake_module}):
                model = transcription.load_whisper("tiny", "int8")

            self.assertIsInstance(model, FakeWhisperModel)
            self.assertEqual(model.model_size, "tiny")
            self.assertEqual(model.compute_type, "int8")
            self.assertIs(transcription._WM, FakeWhisperModel)
        finally:
            transcription._WM = original_model_class

    def test_transcribe_audio_collects_segments(self):
        from services.transcription import transcribe_audio

        class FakeSegment:
            def __init__(self, start, end, text):
                self.start = start
                self.end = end
                self.text = text

        class FakeInfo:
            duration = 20.0
            language = "en"

        class FakeModel:
            def transcribe(self, media_path, **kwargs):
                self.media_path = media_path
                self.kwargs = kwargs
                return [FakeSegment(0.0, 5.0, " Hello "), FakeSegment(5.0, 12.0, "team")], FakeInfo()

        model = FakeModel()
        segments, full_text, info = transcribe_audio(
            model,
            Path("meeting.mp4"),
            language="auto",
            beam_size=3,
            progress_timeout=0,
            verbose=True,
        )

        self.assertEqual(segments, [(0.0, 5.0, "Hello"), (5.0, 12.0, "team")])
        self.assertEqual(full_text, "Hello team")
        self.assertIsInstance(info, FakeInfo)
        self.assertEqual(model.media_path, "meeting.mp4")
        self.assertIsNone(model.kwargs["language"])
        self.assertEqual(model.kwargs["beam_size"], 3)
        self.assertTrue(model.kwargs["vad_filter"])

    def test_transcribe_audio_raises_progress_timeout(self):
        from services.transcription import transcribe_audio

        class FakeSegment:
            start = 0.0
            end = 0.1
            text = "stalled"

        class FakeModel:
            def transcribe(self, media_path, **kwargs):
                return [FakeSegment()], object()

        with patch("services.transcription.time.time", side_effect=[0.0, 0.0, 2.0]):
            with self.assertRaisesRegex(RuntimeError, "progress-timeout"):
                transcribe_audio(
                    FakeModel(),
                    Path("meeting.mp4"),
                    language="en",
                    beam_size=1,
                    progress_timeout=1,
                    verbose=False,
                )

    def test_transcribe_with_feedback_uses_verbose_transcription(self):
        import services.transcription as transcription

        class FakeModel:
            pass

        with patch.object(transcription, "transcribe_audio", return_value=("segments", "text", "info")) as mock_transcribe:
            result = transcription.transcribe_with_feedback(
                FakeModel(),
                Path("meeting.mp4"),
                language="en",
                beam_size=5,
                progress_timeout=30,
            )

        self.assertEqual(result, ("segments", "text", "info"))
        mock_transcribe.assert_called_once_with(
            mock_transcribe.call_args.args[0],
            Path("meeting.mp4"),
            language="en",
            beam_size=5,
            progress_timeout=30,
            verbose=True,
        )


class TestSummarizationService(unittest.TestCase):
    """Tests for services.summarization that don't require ML dependencies."""

    def test_chunk_short_text(self):
        from services.summarization import _chunk

        text = "Hello world."
        chunks = _chunk(text, max_chars=3500)
        self.assertEqual(chunks, ["Hello world."])

    def test_chunk_long_text(self):
        from services.summarization import _chunk

        # Build a text that will exceed max_chars when repeated
        sentence = "This is a sentence. "
        text = sentence * 200  # well over 3500 chars
        chunks = _chunk(text, max_chars=3500)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 3500 + len(sentence))  # allow one sentence overhang

    def test_summarize_text_empty(self):
        from services.summarization import summarize_text

        result = summarize_text("")
        self.assertEqual(result, [])

    def test_summarize_text_whitespace_only(self):
        from services.summarization import summarize_text

        result = summarize_text("   \n  ")
        self.assertEqual(result, [])

    def test_load_summarizer_initializes_pipeline(self):
        import services.summarization as summarization

        calls = []

        def fake_pipeline(*args, **kwargs):
            calls.append((args, kwargs))
            return "fake-pipeline"

        fake_module = types.SimpleNamespace(pipeline=fake_pipeline)
        original_summarizer = summarization._summ
        try:
            summarization._summ = None
            with patch.dict(sys.modules, {"transformers": fake_module}):
                summarization._load_summarizer()

            self.assertEqual(summarization._summ, "fake-pipeline")
            self.assertEqual(calls[0][0], ("summarization",))
            self.assertEqual(calls[0][1]["model"], "facebook/bart-large-cnn")
        finally:
            summarization._summ = original_summarizer

    def test_summarize_text_uses_cached_pipeline(self):
        import services.summarization as summarization

        calls = []

        def fake_summarizer(text, **kwargs):
            calls.append((text, kwargs))
            if len(calls) == 1:
                return [{"summary_text": "Agenda was reviewed. Decision was made."}]
            return [{"summary_text": "Agenda was reviewed. Decision was made. Action item assigned."}]

        original_summarizer = summarization._summ
        try:
            summarization._summ = fake_summarizer
            result = summarization.summarize_text("Agenda discussion. Decision discussion.", max_sentences=2)

            self.assertEqual(result, ["Agenda was reviewed.", "Decision was made."])
            self.assertEqual(len(calls), 2)
        finally:
            summarization._summ = original_summarizer


class TestArtifactsService(unittest.TestCase):
    """Tests for services.artifacts."""

    def test_ensure_dirs_creates_directory(self):
        from services.artifacts import ensure_dirs

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "a" / "b" / "c"
            self.assertFalse(target.exists())
            ensure_dirs(target)
            self.assertTrue(target.is_dir())

    def test_ensure_dirs_idempotent(self):
        from services.artifacts import ensure_dirs

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "existing"
            target.mkdir()
            ensure_dirs(target)  # should not raise
            self.assertTrue(target.is_dir())

    def test_outputs_present_missing_dir(self):
        from services.artifacts import outputs_present

        self.assertFalse(outputs_present(Path("/nonexistent/path/xyz")))

    def test_outputs_present_empty_dir(self):
        from services.artifacts import outputs_present

        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(outputs_present(Path(tmp)))

    def test_outputs_present_partial(self):
        from services.artifacts import outputs_present

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "transcript.txt").write_text("x")
            self.assertFalse(outputs_present(p))

    def test_outputs_present_complete(self):
        from services.artifacts import outputs_present

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "transcript.txt").write_text("x")
            (p / "summary.md").write_text("x")
            self.assertTrue(outputs_present(p))

    def test_write_artifacts_no_summary(self):
        from services.artifacts import write_artifacts

        segments = [(0.0, 1.0, "Hello"), (1.0, 2.5, "World")]
        full_text = "Hello World"

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_artifacts(
                out_dir=out,
                segments=segments,
                full_text=full_text,
                stem="test_video",
                do_summary=False,
                summary_max=8,
            )
            self.assertTrue((out / "transcript.txt").exists())
            self.assertTrue((out / "captions.srt").exists())
            self.assertTrue((out / "captions.vtt").exists())
            self.assertTrue((out / "full.txt").exists())
            self.assertTrue((out / "summary.md").exists())

            # Verify transcript format
            transcript = (out / "transcript.txt").read_text()
            self.assertIn("[00:00:00,000 - 00:00:01,000] Hello", transcript)
            self.assertIn("[00:00:01,000 - 00:00:02,500] World", transcript)

            # Verify SRT format
            srt = (out / "captions.srt").read_text()
            self.assertIn("1\n00:00:00,000 --> 00:00:01,000\nHello", srt)

            # Verify VTT format
            vtt = (out / "captions.vtt").read_text()
            self.assertTrue(vtt.startswith("WEBVTT"))
            self.assertIn("00:00:00.000 --> 00:00:01.000", vtt)

            # Verify full.txt
            self.assertEqual((out / "full.txt").read_text(), full_text)

            # No-summary placeholder
            summary = (out / "summary.md").read_text()
            self.assertIn("# Summary", summary)

    def test_write_artifacts_no_summary_skips_existing(self):
        """If summary.md already exists and do_summary=False, don't overwrite it."""
        from services.artifacts import write_artifacts

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            existing_content = "# Existing summary\n\n- Already here.\n"
            (out / "summary.md").write_text(existing_content)

            write_artifacts(
                out_dir=out,
                segments=[],
                full_text="",
                stem="test",
                do_summary=False,
                summary_max=8,
            )

            # Should not have overwritten the existing summary
            self.assertEqual((out / "summary.md").read_text(), existing_content)

    def test_write_artifacts_with_summary(self):
        from services.artifacts import write_artifacts

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch(
                "services.artifacts.summarize_text", return_value=["Agenda reviewed.", "Decision made."]
            ) as mock_summary:
                write_artifacts(
                    out_dir=out,
                    segments=[(0.0, 1.0, "Hello")],
                    full_text="Hello",
                    stem="meeting",
                    do_summary=True,
                    summary_max=2,
                )

            summary = (out / "summary.md").read_text()
            self.assertIn("# Summary: meeting", summary)
            self.assertIn("- Agenda reviewed.", summary)
            self.assertIn("- Decision made.", summary)
            mock_summary.assert_called_once_with("Hello", max_sentences=2)

    def test_write_artifacts_with_summary_handles_empty_bullets(self):
        from services.artifacts import write_artifacts

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch("services.artifacts.summarize_text", return_value=[]):
                write_artifacts(
                    out_dir=out,
                    segments=[],
                    full_text="",
                    stem="empty",
                    do_summary=True,
                    summary_max=2,
                )

            self.assertIn("- No content to summarize.", (out / "summary.md").read_text())

    def test_srt_timestamp_accessible_from_transcription(self):
        """srt_timestamp should be importable from services.transcription."""
        from services.transcription import srt_timestamp  # noqa: F401


class TestServicesImportedInCLI(unittest.TestCase):
    """Verify that transcribe_batch re-exports the service symbols."""

    def test_srt_timestamp_in_cli_module(self):
        from transcribe_batch import srt_timestamp

        self.assertEqual(srt_timestamp(0.0), "00:00:00,000")

    def test_outputs_present_in_cli_module(self):
        from transcribe_batch import outputs_present

        self.assertFalse(outputs_present(Path("/nonexistent")))

    def test_ensure_dirs_in_cli_module(self):
        from transcribe_batch import ensure_dirs

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "new"
            ensure_dirs(target)
            self.assertTrue(target.is_dir())


if __name__ == "__main__":
    unittest.main()
