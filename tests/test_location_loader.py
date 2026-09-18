import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from location_loader import LocationDataError, load_location, load_locations


class LocationLoaderTests(unittest.TestCase):
    def _book(self, rows):
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name) / "地区.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        for row in rows:
            sheet.append(row)
        workbook.save(path)
        self.addCleanup(directory.cleanup)
        return path

    def test_loads_chinese_location_headers_and_skips_blank_rows(self):
        path = self._book([
            ["省份", "州市", "县区"],
            ["云南省", "昆明市", "五华区"],
            [None, None, None],
        ])
        locations = load_locations(path)
        self.assertEqual([item.full_name for item in locations], ["云南省昆明市五华区"])

    def test_row_number_is_one_based_over_data_rows(self):
        path = self._book([
            ["省份", "州市", "县区"],
            ["云南省", "昆明市", "五华区"],
            ["四川省", "成都市", "锦江区"],
        ])
        self.assertEqual(load_location(path, 2).county, "锦江区")

    def test_missing_required_header_is_rejected(self):
        path = self._book([["省份", "城市"], ["云南省", "昆明市"]])
        with self.assertRaisesRegex(LocationDataError, "县区"):
            load_locations(path)


if __name__ == "__main__":
    unittest.main()
