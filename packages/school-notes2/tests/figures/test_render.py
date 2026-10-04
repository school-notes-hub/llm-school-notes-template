"""The host Renderer protocol, without Chromium or network calls."""

import io
import json
import sys

import pytest
from PIL import Image

from school_notes2.figures.render import Renderer


@pytest.mark.parametrize("kind", ["svg", "mermaid"])
def test_renderer_invokes_node_and_reads_exact_output(tmp_path, kind):
    node = tmp_path / "fake-node"
    node.write_text(f'''#!{sys.executable}
import json, sys
from pathlib import Path
from PIL import Image
script, kind, source, output, browser, fid = sys.argv[1:]
assert not Path(output).exists(), "stale output must be removed before rendering"
Path(source + '.args').write_text(json.dumps(sys.argv[1:]))
Image.new("RGB", (120, 60), "white").save(output)
''')
    node.chmod(0o755)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / "forces.png").write_bytes(b"stale")
    renderer = Renderer(tmp_path / "site", tmp_path / "browser", scratch, node=str(node))
    data = b"<svg/>" if kind == "svg" else b"graph LR\n A --> B\n"
    output = renderer(kind, data, "forces")
    assert (scratch / f"forces.{kind}").read_bytes() == data
    assert json.loads((scratch / f"forces.{kind}.args").read_text()) == [
        str(tmp_path / "site/figure-render.mjs"), kind, str(scratch / f"forces.{kind}"),
        str(scratch / "forces.png"), str(tmp_path / "browser"), "forces"]
    assert Image.open(io.BytesIO(output)).size == (120, 60)


@pytest.mark.parametrize("mode", ["failure", "missing", "invalid"])
def test_renderer_never_reuses_old_output(tmp_path, mode):
    node = tmp_path / "fake-node"
    body = {'failure': 'sys.stderr.write("bad svg"); sys.exit(1)',
            'missing': 'pass', 'invalid': 'Path(sys.argv[4]).write_bytes(b"invalid")'}[mode]
    node.write_text(f"#!{sys.executable}\nimport sys\nfrom pathlib import Path\n{body}\n")
    node.chmod(0o755)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / "forces.png").write_bytes(b"old")
    renderer = Renderer(tmp_path / "site", tmp_path / "browser", scratch, node=str(node))
    with pytest.raises((OSError, ValueError)):
        renderer("svg", b"<svg/>", "forces")
