"""Execution contract tests; no external renderer or network required."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class VisualExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / 'repo'
        (self.repo / 'tools').mkdir(parents=True)
        shutil.copyfile(Path(__file__).with_name('visual_tools.py'), self.repo / 'tools/visual_tools.py')
        self.home = self.base / 'home'
        self.home.mkdir()
        self.env = dict(os.environ, HOME=str(self.home), PYTHONDONTWRITEBYTECODE='1')
        self.source = self.repo / 'sample.py'
        self.source.write_text("import os\nfrom pathlib import Path\nPath(os.environ['VISUAL_OUTPUT_DIR'], 'figure.svg').write_text('<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 10 10\"/>')\n")
        self.out = self.base / 'output'

    def cli(self, *args):
        return subprocess.run([sys.executable, str(self.repo / 'tools/visual_tools.py'), *map(str, args)],
                              cwd=self.base, env=self.env, capture_output=True, text=True, timeout=10)

    def render(self, *extra, source=None):
        return self.cli('render', 'python', source or self.source, '--output', self.out, *extra)

    def test_discovery_has_no_side_effects_or_false_review_claim(self):
        before = sorted(self.base.rglob('*'))
        result = self.cli('status')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['state'], 'discovered-not-render-tested')
        self.assertEqual(sorted(self.base.rglob('*')), before)

    def test_relative_jar_resolves_from_configuration_not_cwd(self):
        (self.repo / 'plantuml.jar').write_bytes(b'not executed in discovery')
        (self.repo / 'visual-tools.local.json').write_text('{"plantuml_jar":"plantuml.jar"}')
        result = self.cli('status')
        self.assertEqual(json.loads(result.stdout)['paths']['plantuml_jar'], str(self.repo / 'plantuml.jar'))

    def test_render_records_unreviewed_hashes_and_preserves_existing_output(self):
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = self.out / 'render.json'
        record = json.loads(receipt.read_text())
        self.assertEqual(record['state'], 'rendered-awaiting-review')
        self.assertEqual(record['visual_review'], 'not-performed')
        self.assertEqual(record['subject_review'], 'not-performed')
        self.assertEqual(len(record['outputs']['figure.svg']['sha256']), 64)
        before = receipt.read_bytes()
        self.assertNotEqual(self.render().returncode, 0)
        self.assertEqual(receipt.read_bytes(), before)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_sources_outside_checkout_and_raw_sources_rejected(self):
        for parent in [self.base, self.repo / 'sources', self.repo / 'references']:
            parent.mkdir(exist_ok=True)
            source = parent / 'untrusted.py'
            source.write_text("raise Exception('must not execute')")
            self.assertNotEqual(self.render(source=source).returncode, 0)
            self.assertFalse(self.out.exists())

    def test_output_escape_and_reserved_paths_rejected(self):
        for name in ['../outside.svg', '/tmp/outside.svg', 'render.json', 'stdout.log', '.cache/test.svg']:
            self.assertNotEqual(self.render('--expect', name).returncode, 0)
            self.assertFalse(self.out.exists())

    def test_private_additional_inputs_rejected_before_render(self):
        for folder in ('sources', 'references'):
            private = self.repo / folder / 'image.png'
            private.parent.mkdir()
            private.write_bytes(b'private image')
            alias = self.repo / (folder + '-alias.png')
            alias.symlink_to(private)
            for path in (private, alias):
                with self.subTest(path=path):
                    result = self.render('--input', path)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('input cannot be inside raw sources/references', result.stderr)
                    self.assertFalse(self.out.exists())

    def test_authored_additional_input_is_recorded(self):
        data = self.repo / 'data.csv'
        data.write_text('x,y\n1,2\n')
        result = self.render('--input', data)
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads((self.out / 'render.json').read_text())
        self.assertEqual(list(record['additional_inputs']), [str(data)])

    def test_exit_zero_without_requested_artifact_is_failure(self):
        self.source.write_text('pass\n')
        self.assertNotEqual(self.render().returncode, 0)
        self.assertEqual(json.loads((self.out / 'render.json').read_text())['state'], 'failed')

    def test_renderer_failure_even_with_artifact(self):
        self.source.write_text(self.source.read_text() + 'raise SystemExit(3)\n')
        self.assertNotEqual(self.render().returncode, 0)
        record = json.loads((self.out / 'render.json').read_text())
        self.assertEqual(record['exit_code'], 3)
        self.assertEqual(record['state'], 'failed')

    def test_timeout_is_bounded_and_recorded(self):
        self.source.write_text('import time\ntime.sleep(30)\n')
        self.assertNotEqual(self.render('--timeout', 1).returncode, 0)
        self.assertEqual(json.loads((self.out / 'render.json').read_text())['state'], 'failed')
        self.assertIn('timeout', (self.out / 'stderr.log').read_text())

    def test_symlink_artifact_is_rejected(self):
        self.source.write_text("import os\nfrom pathlib import Path\nPath(os.environ['VISUAL_OUTPUT_DIR'], 'figure.svg').symlink_to(__file__)\n")
        self.assertNotEqual(self.render().returncode, 0)
        self.assertIn('escapes', json.loads((self.out / 'render.json').read_text())['error'])


if __name__ == '__main__':
    unittest.main()


PNG = bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082')


class AnimationTests(unittest.TestCase):
    """POV-Ray animation → figure.mp4 + figure.png."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.repo = base / 'repo'
        (self.repo / 'tools').mkdir(parents=True)
        shutil.copyfile(Path(__file__).with_name('visual_tools.py'), self.repo / 'tools/visual_tools.py')
        self.source = self.repo / 'scene.pov'
        self.source.write_text('camera { location <0,1,-3> look_at 0 }\nlight_source { <2,4,-3> rgb 1 }\n'
                               'sphere { <clock*2-1,0,0>, 0.5 pigment { rgb <1,0.4,0> } }\n')
        self.out = base / 'anim'
        self.base = base

    def fakes(self):
        povray = self.base / 'povray'
        povray.write_text('#!/usr/bin/env python3\nimport sys\nfrom pathlib import Path\n'
                          'a = sys.argv[1:]\nout = Path(next(x[2:] for x in a if x.startswith("+O")))\n'
                          'n = int(next(x[4:] for x in a if x.startswith("+KFF")))\n'
                          f'png = bytes.fromhex("{PNG.hex()}")\n'
                          'for i in range(1, n + 1):\n    (out.parent / f"f{i:02d}.png").write_bytes(png)\n')
        ffmpeg = self.base / 'ffmpeg'
        ffmpeg.write_text('#!/usr/bin/env python3\nimport sys\nfrom pathlib import Path\n'
                          'Path(sys.argv[-1]).write_bytes(b"\\x00\\x00\\x00\\x18ftypisom" + b"\\x00" * 16)\n')
        for f in (povray, ffmpeg):
            f.chmod(0o755)
        config = self.base / 'visual.json'
        config.write_text(json.dumps({'povray': str(povray), 'ffmpeg': str(ffmpeg)}))
        return config

    def run_cli(self, config, *extra):
        cmd = [sys.executable, str(self.repo / 'tools/visual_tools.py'), *(['--config', str(config)] if config else []),
               'render', 'povray', str(self.source), '--output', str(self.out), *map(str, extra)]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    def test_frames_become_mp4_and_poster_and_are_deleted(self):
        result = self.run_cli(self.fakes(), '--frames', 5, '--fps', 10)
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads((self.out / 'render.json').read_text())
        self.assertEqual(sorted(record['outputs']), ['figure.mp4', 'figure.png'])
        self.assertEqual(record['animation'], {'frames': 5, 'fps': 10})
        self.assertFalse((self.out / 'frames').exists())

    def test_expect_is_refused_for_an_animation(self):
        result = self.run_cli(self.fakes(), '--frames', 3, '--expect', 'x.mp4')
        self.assertNotEqual(result.returncode, 0)

    @unittest.skipUnless(shutil.which('povray') and shutil.which('ffmpeg'), 'povray/ffmpeg not installed')
    def test_real_tiny_animation_is_byte_stable(self):
        hashes = []
        for n in range(2):
            self.out = self.base / f'real{n}'
            result = self.run_cli(None, '--frames', 4, '--width', 96, '--height', 64, '--threads', 1)
            self.assertEqual(result.returncode, 0, result.stderr)
            hashes.append(json.loads((self.out / 'render.json').read_text())['outputs'])
        self.assertEqual(hashes[0], hashes[1])
