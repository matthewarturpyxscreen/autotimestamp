"""Tes parser multi-baris tanpa API key / Streamlit server."""
import importlib
import sys
import types
import unittest

if 'streamlit_paste_button' not in sys.modules:
    stub = types.ModuleType('streamlit_paste_button')
    stub.paste_image_button = lambda *args, **kwargs: None
    sys.modules['streamlit_paste_button'] = stub

batch_manual = importlib.import_module('batch_manual')


class BatchMultilineParserTests(unittest.TestCase):
    def test_4_lines_with_two_address_rows(self):
        raw = ('3.2060390, 99.2981530\n'
               'Desa Panombean Baru, Bandar Masilam,\n'
               'Simalungun, Sumatera Utara\n'
               '24/10/2026 14:36:41 WIB')
        lat, lng, locations, timestamp = batch_manual.parse_batch_timestamp_reference(raw)
        self.assertAlmostEqual(lat, 3.2060390)
        self.assertAlmostEqual(lng, 99.2981530)
        self.assertEqual(locations, ['Desa Panombean Baru, Bandar Masilam,',
                                     'Simalungun, Sumatera Utara'])
        self.assertEqual(timestamp, '24/10/2026 14:36:41 WIB')
        assembled = '\n'.join([f'{lat:.7f}, {lng:.7f}', *locations, timestamp])
        self.assertEqual(len(assembled.splitlines()), 4)
        self.assertEqual(assembled.splitlines()[-2], 'Simalungun, Sumatera Utara')

    def test_3_line_backward_compatibility(self):
        *_, locations, timestamp = batch_manual.parse_batch_timestamp_reference(
            '-2.9390024, 114.3637999\nPangkalan Sari, Kapuas, Kalimantan Tengah\n16/10/2026 16:23:46 WIB'
        )
        self.assertEqual(len(locations), 1)
        self.assertTrue(timestamp.endswith('WIB'))

    def test_5_lines_and_no_date(self):
        base = '3.2060390, 99.2981530\nDesa A\nKecamatan B\nKabupaten C'
        *_, locations, timestamp = batch_manual.parse_batch_timestamp_reference(base)
        self.assertEqual(len(locations), 3)
        self.assertEqual(timestamp, '')
        *_, locations, timestamp = batch_manual.parse_batch_timestamp_reference(base + '\n24-10-2026 14:36 WITA')
        self.assertEqual(len(locations), 3)
        self.assertEqual(timestamp, '24-10-2026 14:36 WITA')

    def test_timezone_from_all_address_rows(self):
        *_, locations, timestamp = batch_manual.parse_batch_timestamp_reference(
            '3.2060390, 99.2981530\nDesa Panombean Baru, Bandar Masilam\nSimalungun, Sumatera Utara\n24/10/2026 14:36:41 WIB'
        )
        inferred = batch_manual._infer_indonesia_timezone_from_location(' '.join(locations))
        self.assertEqual(inferred['indonesia_label'], 'WIB')

    def test_reject_duplicate_time_rows(self):
        with self.assertRaisesRegex(ValueError, 'lebih dari satu'):
            batch_manual.parse_batch_timestamp_reference(
                '3.2060390, 99.2981530\nDesa A\n24/10/2026 13:00 WIB\n24/10/2026 14:00 WIB'
            )

if __name__ == '__main__':
    unittest.main()
