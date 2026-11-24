import contextlib
import io
import unittest

from greet import greet, main


class TestGreet(unittest.TestCase):
    def test_greet(self):
        self.assertEqual(greet('Ada'), 'Hello, Ada!')

    def test_blank_name(self):
        self.assertEqual(greet('  '), 'Hello, world!')

    def test_language(self):
        self.assertEqual(greet('Ada', 'fr'), 'Bonjour, Ada!')

    def test_unknown_language(self):
        with self.assertRaisesRegex(ValueError, 'de, en, fr'):
            greet('Ada', 'xx')

    def test_command_line(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(['Ada', '--lang', 'de']), 0)
        self.assertEqual(out.getvalue(), 'Hallo, Ada!\n')


if __name__ == '__main__':
    unittest.main()
