#!/usr/bin/env python3
"""Run trusted, repository-owned visual sources with already installed tools.

No installer, agent integration, public renderer, automatic fallback or publication.
Rendering success never means subject-matter or visual review passed.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = {'dot': 'dot', 'java': 'java', 'plantuml_jar': None,
            'povray': 'povray', 'freecad': 'freecadcmd', 'freecad_app_run': None,
            'ffmpeg': 'ffmpeg'}
SYSTEM_PLANTUML = '/usr/share/plantuml/plantuml.jar'
ENGINES = ('python', 'graphviz', 'plantuml', 'povray', 'freecad')
SUFFIXES = {'python': '.py', 'graphviz': '.dot', 'plantuml': '.puml',
            'povray': '.pov', 'freecad': '.py'}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def load_config(path=None):
    p = Path(path).expanduser().resolve() if path else ROOT / 'visual-tools.local.json'
    data = json.loads(p.read_text()) if p.exists() else {}
    if path and not p.exists():
        raise ValueError(f'Configuration not found: {p}')
    if not isinstance(data, dict) or set(data) - set(DEFAULTS):
        raise ValueError('Configuration must contain only documented runtime path keys')
    result = DEFAULTS | data
    if not result['plantuml_jar'] and Path(SYSTEM_PLANTUML).is_file():
        result['plantuml_jar'] = SYSTEM_PLANTUML   # the Debian package's jar (container image)
    for key, value in result.items():
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f'{key} must be a path/name string or null')
        if value:
            expanded = Path(value).expanduser()
            if key == 'plantuml_jar' or '/' in value or '\\' in value or expanded.is_absolute():
                result[key] = str((p.parent / expanded).resolve())
    return result


def executable(value):
    return shutil.which(value) if value else None


def versions():
    result = {'python': sys.version.split()[0]}
    for name in ('matplotlib', 'numpy', 'scipy'):
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = None
    return result


def availability(config):
    paths = {k: executable(v) for k, v in config.items() if k != 'plantuml_jar'}
    jar = config['plantuml_jar']
    jar = str(Path(jar).resolve()) if jar and Path(jar).is_file() else None
    pkg = versions()
    return {'state': 'discovered-not-render-tested', 'python_packages': pkg,
            'paths': paths | {'plantuml_jar': jar},
            'engines': {'python': True, 'graphviz': bool(paths['dot']),
                        'plantuml': bool(paths['java'] and jar),
                        'povray': bool(paths['povray']),
                        'povray_animation': bool(paths['povray'] and paths['ffmpeg']),
                        'freecad': bool(paths['freecad_app_run'] or paths['freecad'])},
            'plotting_packages_present': bool(pkg['matplotlib'] and pkg['numpy']),
            'note': 'Availability is not diagram support or content validation; PlantUML families may also need Graphviz.'}


def run_process(command, cwd, env, timeout, input_bytes=None):
    start = time.perf_counter()
    p = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=os.name == 'posix')
    try:
        stdout, stderr = p.communicate(input=input_bytes, timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == 'posix':
            os.killpg(p.pid, signal.SIGKILL)
        else:
            p.kill()
        stdout, stderr = p.communicate()
        return -1, stdout, stderr + b'\nRenderer timeout\n', time.perf_counter() - start
    return p.returncode, stdout, stderr, time.perf_counter() - start


def check_output(path):
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f'Missing or empty requested artifact: {path.name}')
    info = {'bytes': path.stat().st_size, 'sha256': digest(path)}
    if path.suffix.lower() == '.svg':
        root = ET.parse(path).getroot()
        if root.tag != '{http://www.w3.org/2000/svg}svg':
            raise ValueError('Output is not an SVG document')
        info['viewBox'] = root.get('viewBox')
    elif path.suffix.lower() == '.png':
        with path.open('rb') as f:
            head = f.read(24)
        if len(head) != 24 or head[:8] != b'\x89PNG\r\n\x1a\n' or head[12:16] != b'IHDR':
            raise ValueError('Output is not a PNG with an IHDR header')
        info['dimensions'] = list(struct.unpack('>II', head[16:24]))
    elif path.suffix.lower() == '.mp4':
        with path.open('rb') as f:
            if f.read(12)[4:8] != b'ftyp':
                raise ValueError('Output is not an MP4 file')
    elif path.suffix.lower() == '.pdf':
        with path.open('rb') as f:
            if f.read(5) != b'%PDF-':
                raise ValueError('Output is not a PDF')
    return info


VOLATILE_PNG_CHUNKS = (b'tIME', b'tEXt', b'zTXt', b'iTXt')


def strip_png_metadata(path):
    """Drop POV-Ray's render date and other text/time chunks: the same scene must give the
    same bytes on every run."""
    data = path.read_bytes()
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        return
    out, i = [data[:8]], 8
    while i + 8 <= len(data):
        length = struct.unpack('>I', data[i:i + 4])[0]
        chunk = data[i:i + 12 + length]
        if chunk[4:8] not in VOLATILE_PNG_CHUNKS:
            out.append(chunk)
        i += 12 + length
    path.write_bytes(b''.join(out))


def relative_file(value):
    p = Path(value)
    if p.is_absolute() or '..' in p.parts or not p.parts:
        raise ValueError('Expected artifact must be a relative file below the output directory')
    if p.parts[0] in ('render.json', 'stdout.log', 'stderr.log', 'freecad-user.cfg',
                      'freecad-system.cfg', '.matplotlib', '.cache'):
        raise ValueError('Expected artifact conflicts with a reserved execution file')
    return p


def render(args, config):
    source = Path(args.source).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != SUFFIXES[args.engine]:
        raise ValueError(f'{args.engine} needs an existing {SUFFIXES[args.engine]} source')
    if not source.is_relative_to(ROOT) or source.relative_to(ROOT).parts[0] in ('sources', 'references', '.git'):
        raise ValueError('Execute reviewed visual source inside this Git checkout, outside raw sources/references/.git')
    extra = [Path(p).expanduser().resolve() for p in args.input]
    if any(p.is_relative_to(ROOT / folder) for p in extra for folder in ('sources', 'references')):
        raise ValueError('Additional input cannot be inside raw sources/references')
    if any(not p.is_file() for p in extra):
        raise ValueError('Every declared additional input must be an existing file')
    out = Path(args.output).expanduser().resolve()
    if any(out.is_relative_to(ROOT / x) for x in ('sources', 'references', '.git')):
        raise ValueError('Output cannot be inside raw sources/references/.git')
    if out.exists():
        raise ValueError('Choose a new output directory; existing work is never overwritten')
    state = availability(config)
    if not state['engines'][args.engine]:
        raise ValueError(f'{args.engine} is unavailable; run status and follow the installation guide')
    if args.frames:
        return render_animation(args, source, extra, out, state)
    outputs = [relative_file(p) for p in args.expect]
    if not outputs:
        outputs = [Path('figure.png' if args.engine == 'povray' else 'figure.svg')]
    if len(set(outputs)) != len(outputs):
        raise ValueError('Expected artifact names must be unique')
    if args.engine in ('graphviz', 'plantuml', 'povray') and len(outputs) != 1:
        raise ValueError('This renderer invocation produces one expected image')
    target = out / outputs[0]
    suffix = target.suffix.lower()
    if args.engine in ('graphviz', 'plantuml') and suffix not in ('.svg', '.png'):
        raise ValueError('Graphviz/PlantUML output must be SVG or PNG')
    if args.engine == 'povray' and suffix != '.png':
        raise ValueError('POV-Ray output must be PNG')
    paths = state['paths']
    out.mkdir(parents=True, exist_ok=False)
    for file in outputs:
        (out / file).parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(VISUAL_OUTPUT_DIR=str(out), PYTHONDONTWRITEBYTECODE='1', MPLBACKEND='Agg')
    stdin = None
    if args.engine == 'python':
        command = [sys.executable, str(source)]
    elif args.engine == 'graphviz':
        command = [paths['dot'], '-T' + suffix[1:], str(source), '-o', str(target)]
    elif args.engine == 'plantuml':
        command = [paths['java'], '-Djava.awt.headless=true', '-DPLANTUML_SECURITY_PROFILE=SANDBOX',
                   '-jar', paths['plantuml_jar'], '--format', suffix[1:], '--charset', 'UTF-8',
                   '--no-error-image', '--disable-metadata', '-pipe']
        env['PLANTUML_SECURITY_PROFILE'] = 'SANDBOX'
        if paths['dot']:
            env['GRAPHVIZ_DOT'] = paths['dot']
        stdin = source.read_bytes()
    elif args.engine == 'povray':
        command = [paths['povray'], '+I' + str(source), '+O' + str(target), '+FN', '-D',
                   '+W' + str(args.width), '+H' + str(args.height), '+Q9', '+A0.1', '+WT' + str(args.threads)]
    else:
        command = [paths['freecad_app_run'], 'freecadcmd'] if paths['freecad_app_run'] else [paths['freecad']]
        command += ['-u', str(out / 'freecad-user.cfg'), '-s', str(out / 'freecad-system.cfg'), str(source)]
    record = {'state': 'running', 'engine': args.engine, 'command': command,
              'source': str(source.relative_to(ROOT)), 'source_sha256': digest(source),
              'additional_inputs': {str(p): digest(p) for p in extra},
              'driver_sha256': digest(__file__), 'python_packages': state['python_packages'],
              'runtime_executable_sha256': digest(command[0]),
              'outputs': {}, 'visual_review': 'not-performed', 'subject_review': 'not-performed'}
    if args.engine == 'plantuml':
        record['plantuml_jar_sha256'] = digest(paths['plantuml_jar'])
    receipt = out / 'render.json'
    # Font and matplotlib caches go to a private temporary directory outside the output and
    # are removed afterwards: the output usually lies in the wiki, where a cache file would be
    # a stray change (fix-50: fontconfig wrote wiki/assets/**/.cache/fontconfig/*.cache-9).
    cache = Path(tempfile.mkdtemp(prefix='visual-cache-'))
    env.update(MPLCONFIGDIR=str(cache / 'matplotlib'), XDG_CACHE_HOME=str(cache / 'xdg'))
    try:
        code, stdout, stderr, seconds = run_process(command, out, env, args.timeout, stdin)
        (out / 'stderr.log').write_bytes(stderr)
        if args.engine == 'plantuml' and code == 0:
            target.write_bytes(stdout)
        elif args.engine == 'povray' and code == 0 and target.is_file():
            (out / 'stdout.log').write_bytes(stdout)
            strip_png_metadata(target)
        else:
            (out / 'stdout.log').write_bytes(stdout)
        record.update(exit_code=code, seconds=seconds)
        if code:
            raise ValueError(f'Renderer exited {code}; inspect {out}/stderr.log and stdout.log')
        for name in outputs:
            path = out / name
            if path.is_symlink() or not path.resolve().is_relative_to(out):
                raise ValueError('Expected output escapes its directory')
            record['outputs'][str(name)] = check_output(path)
        record['state'] = 'rendered-awaiting-review'
    except (OSError, ValueError, ET.ParseError) as exc:
        record.update(state='failed', error=str(exc))
        raise
    finally:
        shutil.rmtree(cache, ignore_errors=True)
        receipt.write_text(json.dumps(record, indent=2, ensure_ascii=False) + '\n')
    return {'state': record['state'], 'receipt': str(receipt), 'outputs': list(record['outputs'])}


def render_animation(args, source, extra, out, state):
    """POV-Ray frames (clock 0..1) → figure.mp4 (H.264, bit-exact flags) plus figure.png, the
    middle frame, as the static counterpart for print. The frames are deleted afterwards."""
    if args.engine != 'povray' or args.expect:
        raise ValueError('Animation is a POV-Ray render with the fixed outputs figure.mp4 and figure.png')
    if not state['engines']['povray_animation']:
        raise ValueError('POV-Ray animation needs povray and ffmpeg; run status')
    paths = state['paths']
    frames = out / 'frames'
    frames.mkdir(parents=True)
    env = os.environ.copy()
    env.update(VISUAL_OUTPUT_DIR=str(out))
    povray = [paths['povray'], '+I' + str(source), '+O' + str(frames / 'f.png'), '+FN', '-D',
              '+W' + str(args.width), '+H' + str(args.height), '+Q9', '+A0.1', '+WT' + str(args.threads),
              '+KFI1', '+KFF' + str(args.frames), '+KI0.0', '+KF1.0']
    record = {'state': 'running', 'engine': 'povray', 'animation': {'frames': args.frames, 'fps': args.fps},
              'command': povray, 'source': str(source.relative_to(ROOT)), 'source_sha256': digest(source),
              'additional_inputs': {str(p): digest(p) for p in extra}, 'driver_sha256': digest(__file__),
              'python_packages': state['python_packages'],
              'runtime_executable_sha256': digest(povray[0]), 'ffmpeg_sha256': digest(paths['ffmpeg']),
              'outputs': {}, 'visual_review': 'not-performed', 'subject_review': 'not-performed'}
    receipt = out / 'render.json'
    try:
        code, stdout, stderr, seconds = run_process(povray, out, env, args.timeout)
        (out / 'stdout.log').write_bytes(stdout)
        (out / 'stderr.log').write_bytes(stderr)
        if code:
            raise ValueError(f'POV-Ray exited {code}; inspect {out}/stderr.log')
        rendered = sorted(frames.glob('f*.png'))
        if len(rendered) != args.frames:
            raise ValueError(f'POV-Ray produced {len(rendered)} of {args.frames} frames')
        for n, frame in enumerate(rendered, start=1):
            frame.rename(frames / f'frame{n:04d}.png')
        encode = [paths['ffmpeg'], '-hide_banner', '-loglevel', 'error', '-y', '-framerate', str(args.fps),
                  '-i', str(frames / 'frame%04d.png'), '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                  '-threads', '1', '-fflags', '+bitexact', '-flags:v', '+bitexact', '-map_metadata', '-1',
                  '-movflags', '+faststart', str(out / 'figure.mp4')]
        record['encode_command'] = encode
        code, _, err, more = run_process(encode, out, env, args.timeout)
        if code:
            (out / 'stderr.log').write_bytes(stderr + err)
            raise ValueError(f'FFmpeg exited {code}; inspect {out}/stderr.log')
        shutil.copyfile(frames / f'frame{(args.frames + 1) // 2:04d}.png', out / 'figure.png')
        strip_png_metadata(out / 'figure.png')
        record.update(exit_code=0, seconds=seconds + more)
        for name in ('figure.mp4', 'figure.png'):
            record['outputs'][name] = check_output(out / name)
        record['state'] = 'rendered-awaiting-review'
    except (OSError, ValueError) as exc:
        record.update(state='failed', error=str(exc))
        raise
    finally:
        shutil.rmtree(frames, ignore_errors=True)
        receipt.write_text(json.dumps(record, indent=2, ensure_ascii=False) + '\n')
    return {'state': record['state'], 'receipt': str(receipt), 'outputs': list(record['outputs'])}


def bounded_int(low, high):
    def parse(value):
        n = int(value)
        if not low <= n <= high:
            raise argparse.ArgumentTypeError(f'Expected {low}..{high}')
        return n
    return parse


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config', help='Optional local runtime paths; relative paths resolve beside this file')
    sub = ap.add_subparsers(dest='action', required=True)
    sub.add_parser('status', help='Read-only discovery; imports no renderers and installs nothing')
    rp = sub.add_parser('render', help='Execute a trusted visual source; a successful render still needs review')
    rp.add_argument('engine', choices=ENGINES)
    rp.add_argument('source')
    rp.add_argument('--output', required=True, help='New directory, never an existing one')
    rp.add_argument('--expect', action='append', default=[], help='Expected relative artifact; repeat for script outputs')
    rp.add_argument('--input', action='append', default=[], help='Additional data/include dependency to hash; repeat as needed')
    rp.add_argument('--timeout', type=bounded_int(1, 3600), default=180)
    rp.add_argument('--width', type=bounded_int(64, 8192), default=1200)
    rp.add_argument('--height', type=bounded_int(64, 8192), default=800)
    rp.add_argument('--threads', type=bounded_int(1, 64), default=2)
    rp.add_argument('--frames', type=bounded_int(2, 240), default=None,
                    help='POV-Ray animation: number of frames (clock 0..1) → figure.mp4 + figure.png')
    rp.add_argument('--fps', type=bounded_int(1, 60), default=12)
    args = ap.parse_args()
    try:
        cfg = load_config(args.config)
        result = availability(cfg) if args.action == 'status' else render(args, cfg)
    except (OSError, ValueError, ET.ParseError) as exc:
        ap.exit(1, str(exc) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
