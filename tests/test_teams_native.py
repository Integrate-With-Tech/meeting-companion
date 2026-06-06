import unittest
from unittest.mock import MagicMock

from services.teams_native import (
    TeamsGraphPermissionError,
    ingest_teams_native_artifacts,
    parse_vtt_segments,
)


class TestParseVttSegments(unittest.TestCase):
    def test_parses_segments_and_speaker_tags(self):
        vtt = """WEBVTT

00:00:01.000 --> 00:00:03.000
<v Alex>Welcome everyone

2
00:00:03.500 --> 00:00:05.000
Priya: Let us begin
"""
        segments = parse_vtt_segments(vtt)
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0].speaker, "Alex")
        self.assertEqual(segments[0].text, "Welcome everyone")
        self.assertEqual(segments[0].start_seconds, 1.0)
        self.assertEqual(segments[1].speaker, "Priya")
        self.assertEqual(segments[1].end_seconds, 5.0)


class TestIngestTeamsNativeArtifacts(unittest.TestCase):
    def _repos(self):
        return MagicMock(), MagicMock(), MagicMock()

    def test_ingests_transcript_and_records_hash(self):
        graph = MagicMock()
        graph.get_transcript_vtt.return_value = "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello\n"
        graph.list_recording_artifacts.return_value = []
        jobs, artifacts, audits = self._repos()

        result = ingest_teams_native_artifacts(
            meeting_id="m1",
            meeting_job_id="j1",
            tenant_id="t1",
            meeting_completed=True,
            graph_client=graph,
            jobs_repo=jobs,
            artifacts_repo=artifacts,
            audit_repo=audits,
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["source"], "teams_native")
        self.assertTrue(result["hash"])
        jobs.update_status.assert_any_call("j1", "processing")
        jobs.update_status.assert_any_call("j1", "completed")
        inserted = artifacts.create.call_args[0][0]
        self.assertEqual(inserted.artifact_type, "transcript_vtt")
        self.assertTrue(inserted.checksum)

    def test_marks_missing_source_artifact_for_completed_meeting(self):
        graph = MagicMock()
        graph.get_transcript_vtt.return_value = None
        graph.list_recording_artifacts.return_value = []
        jobs, artifacts, audits = self._repos()

        result = ingest_teams_native_artifacts(
            meeting_id="m1",
            meeting_job_id="j1",
            tenant_id="t1",
            meeting_completed=True,
            graph_client=graph,
            jobs_repo=jobs,
            artifacts_repo=artifacts,
            audit_repo=audits,
        )

        self.assertEqual(result["status"], "missing_source_artifact")
        jobs.update_status.assert_any_call("j1", "missing_source_artifact")
        artifacts.create.assert_not_called()

    def test_marks_authorization_failed_on_permission_errors(self):
        graph = MagicMock()
        graph.get_transcript_vtt.side_effect = TeamsGraphPermissionError("forbidden")
        jobs, artifacts, audits = self._repos()

        result = ingest_teams_native_artifacts(
            meeting_id="m1",
            meeting_job_id="j1",
            tenant_id="t1",
            meeting_completed=True,
            graph_client=graph,
            jobs_repo=jobs,
            artifacts_repo=artifacts,
            audit_repo=audits,
        )

        self.assertEqual(result["status"], "authorization_failed")
        jobs.update_status.assert_any_call("j1", "authorization_failed", error_message="forbidden")
        artifacts.create.assert_not_called()

    def test_records_skipped_recording_artifacts_without_paths(self):
        graph = MagicMock()
        graph.get_transcript_vtt.return_value = None
        graph.list_recording_artifacts.return_value = [{"id": ""}, {"download_url": "https://example.com/a.mp4"}]
        jobs, artifacts, audits = self._repos()

        result = ingest_teams_native_artifacts(
            meeting_id="m1",
            meeting_job_id="j1",
            tenant_id="t1",
            meeting_completed=True,
            graph_client=graph,
            jobs_repo=jobs,
            artifacts_repo=artifacts,
            audit_repo=audits,
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(artifacts.create.call_count, 1)
        event_types = [call.args[0].event_type for call in audits.append.call_args_list]
        self.assertIn("meeting_job.recording_artifact_skipped", event_types)


if __name__ == "__main__":
    unittest.main()
