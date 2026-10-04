#!/usr/bin/env python3
"""Last gate of a public build: no secret and no machine path in the rendered files
(including decompressed search data and PDF text). The wiki goes out 1:1, so source
footnotes and `sources/` link texts are allowed; the patterns live in public-patterns.json,
which the tool's Markdown check reads too. The report records counts and offending
filenames, never the matched text. Run: python3 check-public.py BUILD
"""
import gzip, json, re, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def patterns():
    spec = json.loads((HERE / 'public-patterns.json').read_text(encoding='utf-8'))
    return [re.compile(p, re.I) for key in ('secrets', 'machine_paths', 'output_only') for p in spec[key]]


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


def main(root):
    payload = json.loads((root / 'payload.json').read_text())
    assert payload['mode'] == 'public'
    compiled, errors = patterns(), []
    counts = {'files': 0, 'pdfs': 0, 'search_chunks': 0}
    site = root / 'site'
    for path in sorted(site.rglob('*')):
        if not path.is_file():
            continue
        counts['files'] += 1
        name = path.relative_to(site).as_posix()
        text = text_of(path, counts)
        if text is not None:
            errors += [{'file': name, 'pattern': p.pattern} for p in compiled if p.search(text)]
        if (path.suffix in ('.md', '.pptx', '.docx') or 'receipt' in path.name
                or name.startswith(('sources/', 'references/', 'docs/'))):
            errors.append({'file': name, 'pattern': 'private file type'})
    result = {'mode': 'public', **counts, 'errors': errors}
    (root / 'privacy-report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False))
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main(Path(sys.argv[1])))
