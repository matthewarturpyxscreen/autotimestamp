import unittest

from ocr_fields import coordinate_from_ocr, first_nonempty_line, normalize_ocr_lines, replace_first_line

class TestOcrCoordinates(unittest.TestCase):
    def test_digits_are_not_rounded(self):
        source = "-2.9390024, 114.3637999\nKapuas, Kalimantan Tengah\n16/10/2026 16:23:46 WIB"
        self.assertEqual(coordinate_from_ocr(source), "-2.9390024, 114.3637999")
        self.assertEqual(normalize_ocr_lines(source), source)

    def test_removes_gemini_line_label_only(self):
        source = "Baris 1: Koordinat: -6.5500687, 107.4378152\nBandung"
        self.assertEqual(normalize_ocr_lines(source).splitlines()[0], "-6.5500687, 107.4378152")

    def test_rejects_bad_coordinates_without_guess(self):
        for text in ("", "11/10/2026 12:30:40 WIB", "123.7, 180.5", "Sukaratu, Lampung"):
            self.assertEqual(coordinate_from_ocr(text), "")

    def test_edits_only_coordinates(self):
        old = "-6.5, 107.1\nCipaisan, Purwakarta, Jawa Barat\n7/10/2026 13:12:08 WIB\nExtra"
        new = replace_first_line(old, "-7.001, 108.002")
        self.assertEqual(new.splitlines()[0], "-7.001, 108.002")
        self.assertEqual(new.splitlines()[1:], old.splitlines()[1:])

    def test_pasting_multiline(self):
        self.assertEqual(first_nonempty_line("\n -6.5, 106.8\nJakarta"), "-6.5, 106.8")

if __name__ == "__main__":
    unittest.main()
