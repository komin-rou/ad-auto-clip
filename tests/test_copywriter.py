import unittest

from copywriter import FactLibrary, ScriptValidationError, build_local_script, validate_ad_script
from location_loader import Location


class CopywriterTests(unittest.TestCase):
    def setUp(self):
        self.location = Location("贵州省", "毕节市", "七星关区")
        self.facts = FactLibrary(
            required_phrases=("2000 平", "上门测量", "专业设计师", "3D 效果图", "上门安装"),
            forbidden_claims=("全国最低价", "免费", "当天安装"),
            forbidden_number_pattern=True,
            target_chars=160,
        )

    def test_local_script_contains_location_and_every_required_fact(self):
        text = build_local_script(self.location, self.facts)
        validate_ad_script(text, self.location, self.facts)

    def test_missing_location_is_rejected(self):
        text = build_local_script(self.location, self.facts).replace("贵州省毕节市七星关区", "本地")
        with self.assertRaisesRegex(ScriptValidationError, "地点"):
            validate_ad_script(text, self.location, self.facts)

    def test_forbidden_claim_and_unknown_number_are_rejected(self):
        text = build_local_script(self.location, self.facts) + "全国最低价，十年质保。"
        with self.assertRaises(ScriptValidationError) as caught:
            validate_ad_script(text, self.location, self.facts)
        self.assertIn("全国最低价", str(caught.exception))
        self.assertIn("十年", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
