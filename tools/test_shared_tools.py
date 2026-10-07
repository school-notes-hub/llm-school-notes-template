"""Behavioral regression checks for shared-tool migration and divergence detection."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import book_index
import check_shared
import sync_wording


class SharedToolsTest(unittest.TestCase):
    def test_checker_detects_drift_and_ignores_local_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            template, child = base / 'template', base / 'child'
            for root in (template, child):
                root.mkdir()
                (root / 'shared-files.json').write_text(json.dumps({'version': 'test', 'files': ['AGENTS.md']}))
                (root / 'AGENTS.md').write_text('same rules\n')
            (child / 'PROFILE.md').write_text('different learner\n')
            self.assertEqual(check_shared.compare(template, child)[1], [])
            (child / 'AGENTS.md').write_text('local drift\n')
            self.assertEqual(check_shared.compare(template, child)[1], ['Different shared file: AGENTS.md'])
            (child / 'AGENTS.md').unlink()
            self.assertEqual(check_shared.compare(template, child)[1], ['Missing shared file: AGENTS.md'])

    def test_checker_rejects_path_outside_repo(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'shared-files.json').write_text(json.dumps({'version': 'test', 'files': ['../private']}))
            with self.assertRaises(ValueError):
                check_shared.read_manifest(root)

    def test_offset_formats_remain_supported(self):
        for text, expected in [('printed-page offset: 4', [(1, 4)]), ('one less', [(1, 1)]), ('eggyel kisebb', [(1, 1)])]:
            self.assertEqual(book_index.readme_bands(text), expected)

    def test_two_offset_bands(self):
        """Four unnumbered plates after PDF 20: PDF 1-20 print as PDF-1, from PDF 25 as PDF-5."""
        readme = 'printed-page offset: 1 from PDF 1\nprinted-page offset: 5 from PDF 25\n'
        bands = book_index.readme_bands(readme)
        self.assertEqual(bands, [(1, 1), (25, 5)])
        self.assertEqual([book_index.printed_of(bands, p) for p in (2, 20, 21, 24, 25, 30)], [1, 19, None, None, 20, 25])
        self.assertEqual([book_index.pdf_of(bands, n) for n in (1, 19, 20, 25)], [2, 20, 25, 30])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script = root / 'book_index.py'
            script.write_bytes(Path(book_index.__file__).read_bytes())
            (root / 'book-index.json').write_bytes(Path(book_index.__file__).with_name('book-index.json').read_bytes())
            book = root / 'book'; book.mkdir()
            (book / 'README.md').write_text('# Két sáv\n\n' + readme + '<!-- book-index: readme -->\n\n'
                                            '| Lecke | Oldal |\n|---|---|\n| Első | 1 |\n| Második | 20 |\n')
            (book / 'document.md').write_text(''.join(f'<!-- element:p{i:03}-e001 kind=text page={i} -->\nText {i}\n'
                                                      for i in range(1, 31)))
            subprocess.run([sys.executable, str(script), str(book)], check=True, capture_output=True)
            index = (book / 'index.md').read_text()
            self.assertIn('| Első | 1-19 | 3-48 |', index)          # PDF 2-24 (the plates belong to it)
            self.assertIn('| Második | 20-25 | 49-61 |', index)     # PDF 25-30
            self.assertIn('19: 39 · 20: 49', index)             # the plates have no printed number
            self.assertIn('20: 49', index)
            self.assertIn('1 (PDF 1-), 5 (PDF 25-)', index)

    def test_checked_readme_overrides_plausible_but_incomplete_toc(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script = root / 'book_index.py'
            script.write_bytes(Path(book_index.__file__).read_bytes())
            config = Path(book_index.__file__).with_name('book-index.json')
            (root / 'book-index.json').write_bytes(config.read_bytes())
            book = root / 'book'; book.mkdir()
            toc = '<table>' + ''.join(f'<tr><td>Unverified {i}</td><td>{i}</td></tr>' for i in range(1, 7)) + '</table>'
            doc = '<!-- element:p001-e001 kind=heading page=1 -->\n# Tartalom\n' + toc + '\n'
            doc += ''.join(f'<!-- element:p{i:03}-e001 kind=text page={i} -->\nText\n' for i in range(2, 9))
            (book / 'document.md').write_text(doc)
            readme = '# Example\nprinted-page offset: 0\n| Checked lesson | 2-8 |\n'
            for flag in ('--readme', 'marker'):
                (book / 'README.md').write_text(readme + ('<!-- book-index: readme -->\n' if flag == 'marker' else ''))
                args = [sys.executable, str(script), str(book)] + ([flag] if flag == '--readme' else [])
                subprocess.run(args, check=True, capture_output=True)
                result = (book / 'index.md').read_text()
                self.assertIn('| Checked lesson | 2-8 |', result)
                self.assertNotIn('Unverified', result)
                self.assertEqual((book / 'document.md').read_text(), doc)


    def test_wording_sync_replaces_only_the_wording_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            head = '| Key | English | Magyar |\n|---|---|---|\n'
            (base / 't').mkdir()
            (base / 'c').mkdir()
            (base / 't' / 'PROFILE.md').write_text('# T\n\n' + head + '| a | A | Á |\n| b | B | B2 |\n\nTemplate tail\n')
            (base / 'c' / 'PROFILE.md').write_text('# Tanuló\n\nown text\n\n' + head + '| a | old | régi |\n\nLocal decisions\n')
            args = ['--template', str(base / 't'), '--target', str(base / 'c')]
            self.assertEqual(sync_wording.main(args + ['--check']), 1)
            self.assertEqual(sync_wording.main(args), 0)
            self.assertEqual((base / 'c' / 'PROFILE.md').read_text(),
                             '# Tanuló\n\nown text\n\n' + head + '| a | A | Á |\n| b | B | B2 |\n\nLocal decisions\n')
            self.assertEqual(sync_wording.main(args + ['--check']), 0)

    def test_the_template_wording_has_no_old_question_mark_date_form(self):
        profile = (Path(__file__).resolve().parents[1] / 'PROFILE.md').read_text(encoding='utf-8')
        row = next(line for line in profile.splitlines() if line.startswith('| undated lesson |'))
        self.assertNotIn('? (', row)
        self.assertIn('~szept. vége', row)


if __name__ == '__main__':
    unittest.main()
