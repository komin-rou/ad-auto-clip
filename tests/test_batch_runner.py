import csv
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from batch_runner import BatchOptions, TransientBatchError, run_batch
from location_loader import Location


class FakePipeline:
    def __init__(self, behavior, calls):
        self.behavior = behavior
        self.calls = calls

    def run(self, output_name, **kwargs):
        self.calls.append((output_name, kwargs))
        outcome = self.behavior()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class BatchRunnerTests(unittest.TestCase):
    def test_failure_does_not_stop_later_locations_and_deterministic_error_is_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            locations = [
                Location("云南省", "昆明市", "五华区"),
                Location("四川省", "成都市", "锦江区"),
            ]
            calls = []
            outcomes = {
                1: lambda: ValueError("素材不足"),
                2: lambda: SimpleNamespace(
                    final_output=str(root / "ok.mp4"),
                    jianying_draft_dir=str(root / "draft"),
                ),
            }

            report = run_batch(
                locations,
                lambda row: FakePipeline(outcomes[row], calls),
                BatchOptions(root, root / "jobs", max_retries=3),
            )

            self.assertEqual([item.status for item in report.items], ["failed", "completed"])
            self.assertEqual(report.items[0].attempts, 1)
            self.assertEqual(len(calls), 2)

    def test_transient_failure_retries_until_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            attempts = {1: 0}
            calls = []

            def behavior():
                attempts[1] += 1
                if attempts[1] < 3:
                    return TransientBatchError("temporary network problem")
                return SimpleNamespace(final_output="final.mp4", jianying_draft_dir="draft")

            report = run_batch(
                [Location("贵州省", "毕节市", "七星关区")],
                lambda row: FakePipeline(behavior, calls),
                BatchOptions(root, root / "jobs", max_retries=2),
            )

            self.assertEqual(report.items[0].status, "completed")
            self.assertEqual(report.items[0].attempts, 3)
            self.assertEqual([entry[1]["resume"] for entry in calls], [False, False, False])

    def test_completed_resume_is_skipped_and_reports_write_json_and_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            location = Location("贵州省", "贵阳市", "南明区")
            output = root / location.full_name
            draft = output / "jianying_draft" / "editable"
            job = root / "jobs" / location.full_name
            draft.mkdir(parents=True)
            job.mkdir(parents=True)
            (output / "final_video_with_tts.mp4").write_bytes(b"video")
            (draft / "draft_manifest.json").write_text("{}", encoding="utf-8")
            (job / "status.json").write_text(
                json.dumps({"status": "completed"}), encoding="utf-8"
            )

            report = run_batch(
                [location],
                lambda row: self.fail("completed resume must not create a pipeline"),
                BatchOptions(root, root / "jobs", resume=True),
            )
            json_path = report.write_json(root / "batch_report.json")
            csv_path = report.write_csv(root / "batch_report.csv")

            self.assertEqual(report.items[0].status, "skipped")
            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8"))["items"][0]["status"], "skipped")
            with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["location"], location.full_name)
            self.assertTrue(row["preview_path"].endswith("final_video_with_tts.mp4"))

    def test_keyboard_interrupt_is_not_swallowed_as_a_failed_location(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls = []
            with self.assertRaises(KeyboardInterrupt):
                run_batch(
                    [Location("云南省", "昆明市", "五华区")],
                    lambda row: FakePipeline(lambda: KeyboardInterrupt(), calls),
                    BatchOptions(root, root / "jobs"),
                )


if __name__ == "__main__":
    unittest.main()
