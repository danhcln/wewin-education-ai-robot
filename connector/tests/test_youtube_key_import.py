"""Credential parsing tests use synthetic files only, never real credentials."""
from pathlib import Path
import tempfile
import unittest
from scripts.configure_youtube_key import parse_key_file


class KeyImportTests(unittest.TestCase):
    def check(self,text):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'credential';p.write_text(text,encoding='utf-8')
            return parse_key_file(p)

    def test_bare(self):
        self.assertEqual(self.check('sample-key-'+'x'*24+'\n'),'sample-key-'+'x'*24)

    def test_assignment_and_bom(self):
        self.assertEqual(self.check('\ufeffYOUTUBE_API_KEY = "'+'x'*32+'"\n'),'x'*32)

    def test_reject_multiple_records(self):
        with self.assertRaises(ValueError):self.check('KEY='+'x'*32+'\nOTHER=value')

    def test_reject_invalid_label(self):
        with self.assertRaises(ValueError):self.check('bad label='+'x'*32)

    def test_reject_oversize(self):
        with self.assertRaises(ValueError):self.check('x'*4097)

    def test_no_input_in_error(self):
        marker='PRIVATE_SAMPLE_MARKER'
        try:self.check(marker+'%invalid')
        except ValueError as error:self.assertNotIn(marker,str(error))
        else:self.fail('Invalid file accepted')


if __name__=='__main__':unittest.main()
