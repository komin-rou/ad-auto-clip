import unittest

from person_detector import PersonInterval, merge_person_samples


class PersonDetectorTests(unittest.TestCase):
    def test_merges_hits_across_short_gaps_and_drops_short_intervals(self):
        intervals = merge_person_samples(
            source="a.mp4",
            sample_times=[0.0, 0.5, 1.0, 2.0, 2.5, 5.0],
            person_hits=[True, True, False, True, True, True],
            sample_period=0.5,
            merge_gap=1.0,
            minimum_duration=1.0,
        )
        self.assertEqual(intervals, [PersonInterval("a.mp4", 0.0, 3.0)])

    def test_no_hits_returns_no_intervals(self):
        self.assertEqual(
            merge_person_samples("a.mp4", [0.0, 0.5], [False, False], 0.5, 0.5, 0.5),
            [],
        )

    def test_last_sample_interval_is_clamped_to_real_source_duration(self):
        intervals = merge_person_samples(
            source="short.mp4",
            sample_times=[12.0, 12.5],
            person_hits=[True, True],
            sample_period=0.5,
            merge_gap=0.75,
            minimum_duration=0.1,
            source_duration=12.8,
        )

        self.assertEqual(intervals, [PersonInterval("short.mp4", 12.0, 12.8)])


if __name__ == "__main__":
    unittest.main()
