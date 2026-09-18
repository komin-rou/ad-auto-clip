import unittest

from clip_planner import InsufficientPersonFootage, plan_person_timeline
from person_detector import PersonInterval


class ClipPlannerTests(unittest.TestCase):
    def test_keeps_two_x_when_person_source_duration_is_sufficient(self):
        intervals = [PersonInterval("a.mp4", 0.0, 20.0)]
        plan = plan_person_timeline(intervals, narration_duration=8.0)
        self.assertEqual(plan.speed, 2.0)
        self.assertAlmostEqual(plan.output_duration, 8.0, places=6)
        self.assertAlmostEqual(plan.items[0].source_duration, 16.0, places=6)

    def test_adapts_speed_continuously_when_two_x_is_not_possible(self):
        intervals = [PersonInterval("a.mp4", 0.0, 15.0)]
        plan = plan_person_timeline(intervals, narration_duration=10.0)
        self.assertEqual(plan.speed, 1.5)
        self.assertAlmostEqual(plan.output_duration, 10.0, places=6)

    def test_fails_at_one_x_and_reports_shortage_without_reuse(self):
        intervals = [PersonInterval("a.mp4", 0.0, 8.0)]
        with self.assertRaises(InsufficientPersonFootage) as caught:
            plan_person_timeline(intervals, narration_duration=10.0)
        self.assertAlmostEqual(caught.exception.shortage_seconds, 2.0)
        self.assertIn("2.00", str(caught.exception))

    def test_consumes_each_interval_once_and_trims_last_item(self):
        intervals = [
            PersonInterval("a.mp4", 0.0, 7.0),
            PersonInterval("b.mp4", 3.0, 10.0),
        ]
        plan = plan_person_timeline(intervals, narration_duration=8.0, preferred_speed=1.5)
        self.assertEqual(len(plan.items), 2)
        self.assertEqual(len({(x.source, x.source_start, x.source_end) for x in plan.items}), 2)
        self.assertAlmostEqual(plan.output_duration, 8.0, places=6)


if __name__ == "__main__":
    unittest.main()
