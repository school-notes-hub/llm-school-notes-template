#!/usr/bin/env python3
"""Last gate of a public build: no secret and no machine path in the rendered files
(including decompressed search data, PDF text and the ID3 text of a podcast MP3, which may
carry only its title and album tags). The wiki goes out 1:1, so source
footnotes and `sources/` link texts are allowed; the patterns live in public-patterns.json,
which the tool's Markdown check reads too. The report records counts and offending
filenames, never the matched text. Run: python3 check-public.py BUILD
"""
import gzip, json, re, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


WEB_URL = re.compile(r"https?://[^\s\"'<>)]+", re.I)


def patterns():
    spec = json.loads((HERE / 'public-patterns.json').read_text(encoding='utf-8'))
    return [re.compile(p, re.I) for key in ('secrets', 'machine_paths', 'output_only') for p in spec[key]]


def visible_patterns():
    """Matched after the web URLs (href/src values too) are left out: a public address may
    contain any path. The tool's page check strips the same way."""
    spec = json.loads((HERE / 'public-patterns.json').read_text(encoding='utf-8'))
    return [re.compile(p, re.I) for p in spec.get('visible_text', [])]


def text_of(path, counts):
    data = path.read_bytes()
    if path.suffix == '.pdf':
        counts['pdfs'] += 1
        return subprocess.check_output(['pdftotext', str(path), '-'], text=True)
    if path.suffix in ('.html', '.svg', '.xml', '.json', '.txt', '.js', '.css'):
        return data.decode('utf8', errors='replace')
    if path.suffix.startswith('.pf_'):
        # Pagefind compressed chunks are gzip streams.
        try:
            text = gzip.decompress(data).decode('utf8', errors='replace')
        except (OSError, EOFError):
            raise ValueError('Uninspected search chunk: ' + path.name)
        counts['search_chunks'] += 1
        return text
    return None


ID3_TEXT = {0: 'latin-1', 1: 'utf-16', 2: 'utf-16-be', 3: 'utf-8'}
ID3_ALLOWED = {'TIT2', 'TALB'}     # sn podcast writes the episode title and the show, nothing else


def id3(data):
    """(the decoded text of an MP3's ID3v2 text frames, its frame ids, has an ID3v1 tag)."""
    texts, frames = [], []
    if data[:3] == b'ID3' and len(data) >= 10:
        major = data[3]
        size = (data[6] << 21) | (data[7] << 14) | (data[8] << 7) | data[9]
        pos, end = 10, min(len(data), 10 + size)
        while pos + 10 <= end and data[pos:pos + 4] != b'\0\0\0\0':
            raw = data[pos + 4:pos + 8]
            length = ((raw[0] << 21) | (raw[1] << 14) | (raw[2] << 7) | raw[3]) if major == 4 else int.from_bytes(raw, 'big')
            name, body = data[pos:pos + 4].decode('latin-1'), data[pos + 10:pos + 10 + length]
            frames.append(name)
            if name.startswith('T') and body:
                texts.append(body[1:].decode(ID3_TEXT.get(body[0], 'latin-1'), errors='replace').strip('\0'))
            pos += 10 + length
    return '\n'.join(texts), frames, data[-128:-125] == b'TAG'


def main(root):
    payload = json.loads((root / 'payload.json').read_text())
    assert payload['mode'] == 'public'
    compiled, visible, errors = patterns(), visible_patterns(), []
    counts = {'files': 0, 'pdfs': 0, 'search_chunks': 0}
    site = root / 'site'
    for path in sorted(site.rglob('*')):
        if not path.is_file():
            continue
        counts['files'] += 1
        name = path.relative_to(site).as_posix()
        text = text_of(path, counts)
        if path.suffix == '.mp3':
            # a podcast episode: its tags are public text too, and only the expected ones
            text, frames, v1 = id3(path.read_bytes())
            extra = sorted(set(frames) - ID3_ALLOWED) + (['ID3v1'] if v1 else [])
            if extra:
                errors.append({'file': name, 'pattern': 'unexpected MP3 tag: ' + ', '.join(extra)})
        if text is not None:
            errors += [{'file': name, 'pattern': p.pattern} for p in compiled if p.search(text)]
            shown = WEB_URL.sub(' ', text)
            errors += [{'file': name, 'pattern': p.pattern} for p in visible if p.search(shown)]
        if (path.suffix in ('.md', '.pptx', '.docx') or 'receipt' in path.name
                or name.startswith(('sources/', 'references/', 'docs/'))):
            errors.append({'file': name, 'pattern': 'private file type'})
    result = {'mode': 'public', **counts, 'errors': errors}
    (root / 'privacy-report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False))
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main(Path(sys.argv[1])))
