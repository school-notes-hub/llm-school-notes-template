#!/usr/bin/env python3
"""Bounded, resumable OpenRouter image executor. Linux, Python 3.10+, Pillow.

The LLM plans and inspects; this CLI validates paths/versions, renders prompts,
serializes spending, persists attempts, and publishes only hash-reviewed assets.
It is a cooperative guard, not an OS security boundary for unrestricted agents.
"""
import argparse
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import socket
import sys
import urllib.error
import urllib.request

from PIL import Image

API = 'https://openrouter.ai/api/v1/images'
MODEL = 'openai/gpt-image-2.5-sunburst'
CHECKS = ('sources', 'context', 'text', 'visual_claims', 'arrows', 'learning_goal', 'phone', 'a4')


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    with temp.open('w') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


def money(value):
    result = Decimal(str(value))
    if not result.is_finite() or result < 0:
        raise ValueError('Invalid nonnegative amount')
    return result


def within(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(root):
        raise ValueError('Path escapes configured root')
    return path


def nonempty(obj, keys):
    for key in keys:
        if not obj.get(key):
            raise ValueError('Required field: ' + key)


def load_job(config, job_path):
    job = read(job_path)
    nonempty(job, ['id', 'request_id', 'learner', 'target', 'role', 'sources', 'plan'])
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,99}', job['id']):
        raise ValueError('Invalid stable job ID')
    if job['request_id'] != config['request_id']:
        raise ValueError('Request not authorized by this configuration')
    repo = Path(config['learners'][job['learner']]['repo']).resolve()
    target = within(repo, job['target'])
    allowed = config['learners'][job['learner']]['targets']
    if job['target'] not in allowed or not target.is_file():
        raise ValueError('Target outside authorized page allowlist')
    if job['role'] not in ('banner', 'infographic', 'infographic-2'):
        raise ValueError('Unsupported visual role')
    if len(job['sources']) > 30:
        raise ValueError('Excessive source list')
    if job['target'] not in [s['path'] for s in job['sources']]:
        raise ValueError('Target version missing')
    for source in job['sources']:
        if sha(within(repo, source['path'])) != source['sha256']:
            raise ValueError('Stale source: ' + source['path'])
    plan = job['plan']
    nonempty(plan, ['goal', 'scope', 'decision_reason', 'context', 'composition', 'visible_text', 'claims', 'style', 'aspect_ratio', 'constraints'])
    if plan['aspect_ratio'] not in ('21:9', '3:2', '2:3', '4:3', '3:4'):
        raise ValueError('Unsupported aspect ratio')
    if job['role'] == 'banner' and plan['aspect_ratio'] != '21:9':
        raise ValueError('Banner must remain wide and low')
    if not isinstance(plan['visible_text'], list) or not all(isinstance(x, str) for x in plan['visible_text']):
        raise ValueError('Exact visible text must be a list of strings')
    for claim in plan['claims']:
        nonempty(claim, ['text', 'source'])
    return job, repo


def compile_prompt(job):
    p = job['plan']
    kind = 'széles, alacsony tanulási fejlécet' if job['role'] == 'banner' else 'önállóan érthető tanító infografikát'
    language = p.get('language', 'magyar')
    lines = [f'Készíts {kind}, {language} nyelven.', 'Tanulási cél: ' + p['goal'],
             'Tartalmi háttér a rajzhoz, nem felirat (ne írd a képre): ' + p['context'],
             'Kompozíció és olvasási sorrend: ' + p['composition'],
             'Kizárólag az alábbi szövegek jelenjenek meg feliratként, pontosan, ebben az olvasási sorrendben. Minden más tervmező rajzolási utasítás, nem képfelirat; ne másold a képre a munkafolyamatot vagy az ellenőrzési szempontokat:',
             *[json.dumps(t, ensure_ascii=False) for t in p['visible_text']],
             'Képi állítások: ' + '; '.join(c['text'] for c in p['claims'])]
    for key, label in [('relationships', 'Kapcsolatok és irányok'), ('sequence', 'Sorrend és időskála'),
                       ('comparison', 'Közös összehasonlítási szempontok'), ('metaphor', 'Metafora megfeleltetése és korlátja'),
                       ('example', 'Ellenőrzött példa és megengedett tanulság'), ('optional', 'Elhagyható motívumok')]:
        if p.get(key):
            lines.append(label + ': ' + json.dumps(p[key], ensure_ascii=False))
    lines += ['Stílus: ' + p['style'], 'Képarány: ' + p['aspect_ratio'],
              'Pontossági korlátok: ' + p['constraints'],
              'A kép legyen szép és elnézegethető, világos fő olvasattal. A feliratok legyenek nagyok, hibátlan magyar ékezetekkel. Ne adj hozzá új tényt, feliratot vagy kapcsolatot. A kötelező tartalom elé helyezd a megértéshez szükséges kontextust. Ne bízd a hiányzó magyarázatot külső szövegre.']
    if job['role'] != 'banner':
        lines.append('A4-es elhelyezéshez a tartalom körül legalább 10 mm biztonsági margó. A rajz legyen nyomtatható, torzítás nélküli illesztéssel; ne apró betűvel próbáld elhelyezni a lényeget.')
    return '\n\n'.join(lines) + '\n'


def load_config(path):
    path = Path(path).resolve()
    config = read(path)
    nonempty(config, ['request_id', 'state_dir', 'learners'])
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,99}', config['request_id']):
        raise ValueError('Invalid request ID')
    for field in ('state_dir', 'env_file'):
        if config.get(field):
            config[field] = str((path.parent / Path(config[field]).expanduser()).resolve())
    for learner in config['learners'].values():
        learner['repo'] = str((path.parent / Path(learner['repo']).expanduser()).resolve())
        money(learner['max_usd'])
    money(config['max_total_usd'])
    money(config['reservation_usd'])
    if not 1 <= int(config.get('max_attempts', 3)) <= 3:
        raise ValueError('Executor supports at most three attempts')
    return config


def initialize_state(config):
    """Explicitly initialize a NEW request. Never reset or replace existing state."""
    state = Path(config['state_dir']).resolve()
    ledger = state / 'ledger.json'
    if ledger.exists():
        if read(ledger)['request_id'] != config['request_id']:
            raise ValueError('Existing state belongs to another request')
        return {'state': 'already-initialized', 'request_id': config['request_id']}
    if state.exists() and any(state.iterdir()):
        raise ValueError('State artifacts exist without ledger; restore the ledger, do not reset')
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with ledger.open('x') as stream:
        json.dump({'request_id': config['request_id'], 'jobs': {}}, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    return {'state': 'initialized', 'request_id': config['request_id']}


def read_ledger(config):
    ledger_path = Path(config['state_dir']) / 'ledger.json'
    if not ledger_path.is_file():
        raise ValueError('State missing: restore existing request state, or explicitly init-state for a NEW request')
    ledger = read(ledger_path)
    if ledger['request_id'] != config['request_id']:
        raise ValueError('Existing state belongs to another request; do not reset it')
    return ledger


@contextmanager
def locked(config):
    state = Path(config['state_dir']).resolve()
    read_ledger(config)  # A missing ledger must never silently grant a fresh budget.
    with (state / 'executor.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield state, state / 'ledger.json', read_ledger(config)


def attempt_folder(config, job, attempt):
    number = attempt['number']
    if type(number) is not int or number < 1:
        raise ValueError('Invalid attempt number')
    # Derive location from the restored state tree, never trust an old absolute path.
    return within(config['state_dir'], job['id'] + '/' + str(number))


def status(config):
    ledger_path = Path(config['state_dir']) / 'ledger.json'
    if not ledger_path.exists():
        return {'state': 'not-initialized', 'request_id': config['request_id'], 'spent_usd': None}
    ledger = read_ledger(config)
    return {'state': 'configured', 'request_id': config['request_id'], 'spent_usd': str(spent(ledger)),
            'cap_usd': config['max_total_usd'], 'jobs': [
                {'id': j['id'], 'attempts': len(j['attempts']), 'state': j['attempts'][-1]['state']}
                for j in ledger['jobs'].values()]}


# Attempts that cost nothing and never count toward max_attempts: the request was
# certainly not sent, or the provider answered with an error status.
FREE_FAILURE = 'failed'
# A sent request whose outcome stayed unknown, settled after a day as spent and failed.
SETTLED = 'lost'
SETTLE_AFTER_HOURS = 24


def counted(attempts):
    """Attempts that count toward max_attempts (free failures do not)."""
    return [a for a in attempts if a['state'] != FREE_FAILURE]


def last_outcome(attempts):
    """The latest attempt that produced or could have produced an image decision."""
    real = [a for a in attempts if a['state'] != FREE_FAILURE]
    return real[-1] if real else None


def free_failure(exc):
    """Failure kind when the provider certainly did not charge, else None."""
    if isinstance(exc, urllib.error.HTTPError):
        exc.close()
        return f'http-{exc.code}'
    reason = getattr(exc, 'reason', None)
    if isinstance(exc, urllib.error.URLError) and isinstance(reason, (socket.gaierror, ConnectionRefusedError)):
        return 'not-sent'
    if isinstance(exc, (socket.gaierror, ConnectionRefusedError)):
        return 'not-sent'
    return None


def spent(ledger):
    return sum((money(a['cost_usd']) for j in ledger['jobs'].values() for a in j['attempts'] if a.get('cost_usd') is not None), Decimal(0))


def api_key(config):
    # Explicit env file; never print it, return it, or use shell evaluation.
    values = dict(os.environ)
    if config.get('env_file'):
        for line in Path(config['env_file']).expanduser().read_text().splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                if k.strip() == 'OPENROUTER_API_KEY':
                    values[k.strip()] = v.strip().strip('\"\'')
    key = values.get('OPENROUTER_API_KEY')
    if not key:
        raise ValueError('Missing OPENROUTER_API_KEY')
    return key


def provider_check(config):
    """Read only key limits; never expose key labels, raw responses or error bodies."""
    req = urllib.request.Request('https://openrouter.ai/api/v1/key',
                                 headers={'Authorization': 'Bearer ' + api_key(config)})

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=20) as response:
            data = json.load(response)['data']
        # Whitelist types as well as fields: no provider-supplied text is echoed.
        result = {'authenticated': True}
        for field in ('limit', 'limit_remaining', 'usage'):
            value = data[field]
            result[field] = None if value is None else str(money(value))
        reset = data.get('limit_reset')
        result['limit_reset'] = reset if reset in (None, 'daily', 'weekly', 'monthly') else 'other'
        result['image_generation_tested'] = False
        return result
    except urllib.error.HTTPError as exc:
        exc.close()
        raise ValueError(f'Provider credential check failed: HTTP {exc.code}') from None
    except (OSError, ValueError, KeyError, TypeError, InvalidOperation):
        raise ValueError('Provider credential check failed: connection or response invalid') from None


def api_call(payload, config):
    key = api_key(config)
    req = urllib.request.Request(API, data=json.dumps(payload).encode(), headers={
        'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    # Avoid forwarding authorization through redirects. No retries.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    with urllib.request.build_opener(NoRedirect).open(req, timeout=300) as response:
        return json.load(response)


def finish_response(folder, result, attempt):
    # Persist the provider result before image processing so a crash is reconcilable.
    write(folder / 'response.json', result)
    cost = result.get('usage', {}).get('cost', result.get('cost'))
    if cost is not None:
        attempt['cost_usd'] = str(money(cost))
    data = result['data']
    if len(data) != 1 or data[0].get('media_type', 'image/png') not in ('image/png', 'image/jpeg', 'image/webp'):
        raise ValueError('Expected exactly one raster image')
    raw = base64.b64decode(data[0]['b64_json'], validate=True)
    if len(raw) > 32 * 1024 * 1024:
        raise ValueError('Image too large')
    with Image.open(io.BytesIO(raw)) as im:
        im.load()
        width, height = im.size
        im.save(folder / 'image.png')
    attempt.update({'sha256': sha(folder / 'image.png'), 'width': width, 'height': height,
                    'state': 'generated' if cost is not None else 'unknown', 'finished_at': now()})
    metadata = {k: v for k, v in result.items() if k != 'data'}
    write(folder / 'generation.json', metadata)


def job_fingerprint(job):
    return hashlib.sha256(json.dumps(job, sort_keys=True).encode()).hexdigest()


def logical_target(job):
    return job['learner'] + ':' + job['target'] + ':' + job['role']


def generation_job(ledger, job):
    """Resolve one logical target; variants share its durable attempt list and ID."""
    logical = logical_target(job)
    entry = ledger['jobs'].get(job['id'])
    if entry and entry['logical'] != logical:
        raise ValueError('Job ID already belongs to another logical target')
    matches = sorted((e for e in ledger['jobs'].values() if e['logical'] == logical),
                     key=lambda e: e['id'])
    if len(matches) > 1:
        raise ValueError('Multiple jobs for one logical target; reconcile ledger before generation')
    if matches:
        entry = matches[0]
        job = {**job, 'id': entry['id']}
    changed = bool(entry and entry['fingerprint'] != job_fingerprint(job))
    if changed:
        attempts = counted(entry['attempts'])
        last = attempts[-1] if attempts else None
        if entry.get('accepted') or not last or last['state'] not in ('rejected', SETTLED):
            raise ValueError('A képterv csak elutasított vagy lost utolsó próba után módosítható; '
                             'elfogadott vagy ítéletre váró képnél őrizd meg a korábbi tervet.')
    return job, changed


def current_frame(entry):
    """Attempts since the owner's last explicit exception (a `grants` record: a new frame of
    max_attempts); every attempt without one. The attempt bound counts only these."""
    grants = entry.get('grants') or []
    if not grants:
        return list(entry['attempts'])
    return [a for a in entry['attempts'] if a['number'] >= grants[-1]['first_attempt']]


def current_attempts(entry):
    start = entry['variants'][-1]['first_attempt'] if entry.get('variants') else 1
    return [a for a in entry['attempts'] if a['number'] >= start]


def run_generate(config, job_path, repair=None, transport=None):
    job, repo = load_job(config, job_path)
    if transport is None:
        api_key(config)  # Missing credentials are a preflight failure, not an unknown paid attempt.
    transport = transport or api_call
    with locked(config) as (state, ledger_path, ledger):
        job, changed = generation_job(ledger, job)
        fingerprint = job_fingerprint(job)
        logical = logical_target(job)
        entry = ledger['jobs'].get(job['id'])
        if entry and entry.get('accepted'):
            return {'state': 'accepted', 'reused': True, **entry['accepted']}
        # Any unknown charge blocks the whole request, including other jobs.
        for other in ledger['jobs'].values():
            if any(a['state'] == 'unknown' or a.get('cost_usd') is None for a in other['attempts']):
                raise ValueError('Reconcile pending provider call/cost before new spending')
        attempts = current_attempts(entry) if entry and not changed else []
        last = last_outcome(attempts)
        lost = bool(last and last['state'] == SETTLED)
        if lost:
            last = None
        if last and last['state'] == 'generated' and not repair:
            return {'state': 'needs-review', **last, 'folder': str(attempt_folder(config, job, last))}
        if last and (not repair or last['state'] not in ('generated', 'rejected')):
            raise ValueError('Repair requires a generated or rejected candidate and targeted instructions')
        if entry and len(counted(current_frame(entry))) >= int(config.get('max_attempts', 3)):
            raise ValueError('Attempt bound reached; select a usable candidate or request a specific exception')
        if repair and not last and not (changed or lost or entry and entry.get('variants')):
            raise ValueError('No initial attempt to repair')
        reserve = money(config['reservation_usd'])
        if not reserve or spent(ledger) + reserve > money(config['max_total_usd']):
            raise ValueError('Whole-request spending bound would be exceeded')
        learner_spent = sum((money(a['cost_usd']) for j in ledger['jobs'].values() if j['learner'] == job['learner'] for a in j['attempts']), Decimal(0))
        if learner_spent + reserve > money(config['learners'][job['learner']]['max_usd']):
            raise ValueError('Learner spending bound would be exceeded')
        if not entry:
            entry = {'id': job['id'], 'learner': job['learner'], 'logical': logical, 'fingerprint': fingerprint, 'attempts': []}
            ledger['jobs'][job['id']] = entry
        attempt_no = len(entry['attempts']) + 1
        if changed:
            variants = entry.setdefault('variants', [])
            variants.append({'id': job['id'] + '~' + str(len(variants) + 2),
                             'previous': variants[-1]['id'] if variants else job['id'],
                             'previous_fingerprint': entry['fingerprint'],
                             'fingerprint': fingerprint, 'first_attempt': attempt_no})
            entry['fingerprint'] = fingerprint
        folder = state / job['id'] / str(attempt_no)
        folder.mkdir(parents=True, exist_ok=True)
        prompt = compile_prompt(job)
        if repair:
            prompt += '\nCélzott javítás; az egyéb helyes részeket őrizd meg:\n' + Path(repair).read_text()
        (folder / 'prompt.txt').write_text(prompt)
        payload = {'model': MODEL, 'prompt': prompt, 'quality': 'high', 'aspect_ratio': job['plan']['aspect_ratio'], 'n': 1}
        write(folder / 'request.json', payload)
        attempt = {'number': attempt_no, 'state': 'unknown', 'started_at': now(), 'reserved_usd': str(reserve), 'cost_usd': None, 'folder': str(folder.relative_to(state)), 'fingerprint': fingerprint}
        entry['attempts'].append(attempt)
        write(ledger_path, ledger)  # Durable reservation BEFORE any network activity.
        try:
            result = transport(payload, config)
            finish_response(folder, result, attempt)
            write(ledger_path, ledger)
            return {'job': job['id'], **attempt, 'folder': str(folder), 'total_usd': str(spent(ledger))}
        except Exception as exc:
            # Never print raw provider errors or secrets.
            attempt['failure_type'] = type(exc).__name__
            kind = free_failure(exc)
            if kind:
                attempt.update({'state': FREE_FAILURE, 'cost_usd': '0', 'failure': kind, 'finished_at': now()})
                write(ledger_path, ledger)
                raise ValueError(f'Provider attempt failed without charge ({kind}); not counted, generation may continue') from None
            write(ledger_path, ledger)  # Preserve reserved/unknown.
            raise ValueError('Provider attempt unresolved; inspect saved response and reconcile, no automatic retry') from None


def reconcile(config, job_path):
    job, _ = load_job(config, job_path)
    with locked(config) as (_, ledger_path, ledger):
        job, _ = generation_job(ledger, job)
        attempt = ledger['jobs'][job['id']]['attempts'][-1]
        if attempt['state'] != 'unknown':
            return {'state': attempt['state'], 'no_change': True}
        folder = attempt_folder(config, job, attempt)
        if not (folder / 'response.json').exists():
            raise ValueError('No saved response: obtain provider billing/output evidence; do not reset or retry')
        finish_response(folder, read(folder / 'response.json'), attempt)
        write(ledger_path, ledger)
        return attempt


def settle_unknown(config, max_age_hours=SETTLE_AFTER_HOURS, at=None):
    """Settle unknown-outcome attempts older than max_age_hours (plan 4.6).

    A saved response is reconciled as usual. Without one, the reserved amount is booked
    as spent and the attempt as failed ('lost'); it still counts toward max_attempts.
    Returns the settled attempts so the caller can notify the owner.
    """
    at = at or datetime.now(timezone.utc)
    settled = []
    with locked(config) as (state, ledger_path, ledger):
        for entry in ledger['jobs'].values():
            for attempt in entry['attempts']:
                if attempt['state'] != 'unknown' and attempt.get('cost_usd') is not None:
                    continue
                age = at - datetime.fromisoformat(attempt['started_at'])
                if age.total_seconds() < max_age_hours * 3600:
                    continue
                folder = within(state, attempt['folder'])
                if (folder / 'response.json').exists():
                    try:
                        finish_response(folder, read(folder / 'response.json'), attempt)
                    except (ValueError, KeyError, OSError):
                        pass
                if attempt['state'] == 'unknown' or attempt.get('cost_usd') is None:
                    attempt.update({'state': SETTLED, 'cost_usd': attempt['reserved_usd'],
                                    'settled_at': at.isoformat(),
                                    'settled_reason': f'unknown outcome after {max_age_hours}h'})
                settled.append({'job': entry['id'], 'learner': entry['learner'],
                                'attempt': attempt['number'], 'state': attempt['state'],
                                'cost_usd': attempt['cost_usd']})
        if settled:
            write(ledger_path, ledger)
    return {'settled': settled, 'total_usd': str(spent(read_ledger(config)))}


def revise(config, previous_job_path, job_path, reason):
    """Reopen an accepted logical image without resetting costs or attempts."""
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('A concrete revision reason is required')
    previous = read(previous_job_path)
    job, repo = load_job(config, job_path)
    keys = ('id', 'request_id', 'learner', 'target', 'role')
    if any(previous.get(k) != job[k] for k in keys):
        raise ValueError('Revision must keep the original logical image identity')
    fingerprint = lambda value: hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
    with locked(config) as (state, ledger_path, ledger):
        entry = ledger['jobs'].get(job['id'])
        if not entry or entry['fingerprint'] != fingerprint(previous):
            raise ValueError('Previous job does not match the existing ledger')
        if not entry.get('accepted'):
            raise ValueError('Revision requires an accepted image; resume pending work instead')
        if any(a.get('cost_usd') is None or a['state'] == 'unknown'
               for j in ledger['jobs'].values() for a in j['attempts']):
            raise ValueError('Resolve unknown provider charges before revision')
        if len(counted(current_frame(entry))) >= int(config.get('max_attempts', 3)):
            raise ValueError('Attempt bound reached; a specific exception is required')
        reserve = money(config['reservation_usd'])
        learner_spent = sum((money(a['cost_usd']) for j in ledger['jobs'].values()
                             if j['learner'] == job['learner'] for a in j['attempts']), Decimal(0))
        if spent(ledger) + reserve > money(config['max_total_usd']) or learner_spent + reserve > money(config['learners'][job['learner']]['max_usd']):
            raise ValueError('Revision cannot exceed the existing spending bounds')
        accepted = entry['accepted']
        output = within(repo, accepted['path'])
        if output.exists() and sha(output) != accepted.get('published_sha256', accepted['sha256']):
            raise ValueError('Previously published image changed')
        original = next((a for a in entry['attempts'] if a.get('sha256') == accepted['sha256']), None)
        if original is None or sha(attempt_folder(config, job, original) / 'image.png') != accepted['sha256']:
            raise ValueError('Previously accepted original is missing or changed')
        revision = {'number': len(entry.get('revisions', [])) + 1,
                    'opened_at': now(), 'reason': reason.strip(),
                    'previous_job': previous, 'previous_fingerprint': entry['fingerprint'],
                    'previous_acceptance': accepted,
                    'previous_last_attempt_state': entry['attempts'][-1]['state'],
                    'next_fingerprint': fingerprint(job)}
        entry.setdefault('revisions', []).append(revision)
        del entry['accepted']
        entry['fingerprint'] = fingerprint(job)
        # The old review remains as history; this explicit event reopens repair.
        entry['attempts'][-1]['state'] = 'rejected'
        entry['attempts'][-1]['revision_reason'] = reason.strip()
        write(ledger_path, ledger)
        return {'state': 'revision-opened', 'revision': revision['number'],
                'attempts_used': len(entry['attempts']), 'total_usd': str(spent(ledger)),
                'previous_path': accepted['path']}


def banner_webp(file):
    """Encode a publication preview without resizing or changing source pixels in place."""
    output = io.BytesIO()
    with Image.open(file) as im:
        # Preserve transparency; compression is restricted to illustrative banners.
        im.convert('RGBA' if 'A' in im.getbands() else 'RGB').save(
            output, format='WEBP', quality=85, method=6)
    return output.getvalue()


def infographic_webp(file):
    """Lossless raster publication; verify dimensions and every decoded RGBA pixel."""
    output = io.BytesIO()
    with Image.open(file) as im:
        original = im.convert('RGBA')
        original.save(output, format='WEBP', lossless=True, method=6, exact=True)
        data = output.getvalue()
        with Image.open(io.BytesIO(data)) as decoded:
            if decoded.size != original.size or decoded.convert('RGBA').tobytes() != original.tobytes():
                raise ValueError('Lossless infographic preview changed decoded pixels')
    return data


def preview_banner(config, job_path):
    return preview_publication(config, job_path, infographic=False)


def preview_infographic(config, job_path):
    return preview_publication(config, job_path, infographic=True)


def preview_publication(config, job_path, infographic=False):
    job, _ = load_job(config, job_path)
    if infographic and job['role'] not in ('infographic', 'infographic-2'):
        raise ValueError('Lossless infographic preview requires an infographic job')
    if not infographic and job['role'] != 'banner':
        raise ValueError('WebP preview is for banners only; precise figures retain their format')
    with locked(config) as (state, ledger_path, ledger):
        job, _ = generation_job(ledger, job)
        entry = ledger['jobs'][job['id']]
        if entry['fingerprint'] != hashlib.sha256(json.dumps(job, sort_keys=True).encode()).hexdigest():
            raise ValueError('Job changed since generation')
        attempt = last_outcome(current_attempts(entry))
        if attempt is None or attempt.get('cost_usd') is None or not attempt.get('sha256'):
            raise ValueError('Resolve generation before preview')
        source = attempt_folder(config, job, attempt) / 'image.png'
        if sha(source) != attempt['sha256']:
            raise ValueError('Image changed since generation')
        dest = source.with_name('publication.webp')
        dest.write_bytes(infographic_webp(source) if infographic else banner_webp(source))
        return {'path': str(dest), 'source_sha256': sha(source), 'sha256': sha(dest),
                'format': 'webp', **({'lossless': True, 'pixel_identical': True} if infographic else {'quality': 85}),
                'bytes': dest.stat().st_size,
                'source_bytes': source.stat().st_size, 'review_required': True}


def review(config, job_path, review_path):
    job, repo = load_job(config, job_path)
    report = read(review_path)
    nonempty(report, ['verifier', 'checked_at', 'sha256', 'observed', 'decision', 'checks'])
    if report['decision'] not in ('accepted', 'rejected'):
        raise ValueError('Review must explicitly accept or reject')
    with locked(config) as (state, ledger_path, ledger):
        # Resolve aliases without allowing an old plan to review a new variant.
        matches = [e for e in ledger['jobs'].values() if e['logical'] == logical_target(job)]
        if len(matches) == 1:
            job = {**job, 'id': matches[0]['id']}
        entry = ledger['jobs'][job['id']]
        fingerprint = hashlib.sha256(json.dumps(job, sort_keys=True).encode()).hexdigest()
        if entry['fingerprint'] != fingerprint:
            raise ValueError('Job changed since generation; review original job')
        candidates = [a for a in current_attempts(entry) if a.get('sha256') == report['sha256']]
        if not candidates:
            raise ValueError('Review hash not found among this job attempts')
        attempt = candidates[-1]
        if attempt.get('cost_usd') is None or attempt['state'] == 'unknown':
            raise ValueError('Unresolved provider cost/status')
        file = attempt_folder(config, job, attempt) / 'image.png'
        if sha(file) != report['sha256']:
            raise ValueError('Image changed since review')
        if entry.get('accepted'):
            if entry['accepted']['sha256'] != report['sha256']:
                raise ValueError('Already accepted another version; do not silently replace')
            return {'state': 'accepted', **entry['accepted']}
        if report['decision'] == 'accepted':
            if not all(report['checks'].get(key) in ('pass', 'not-applicable') for key in CHECKS):
                raise ValueError('Required QA checks missing or failed')
            if any(report['checks'].get(key) == 'not-applicable' for key in CHECKS if key != 'arrows'):
                raise ValueError('Only arrow check may be inapplicable')
            if report.get('material_defects'):
                raise ValueError('Materially defective image cannot be published')
            # Optional publication encoding has its own hash-bound review.
            data = file.read_bytes()
            extension = '.png'
            publication = report.get('publication')
            if publication is not None:
                banner = job['role'] == 'banner' and publication.get('quality') == 85 and 'lossless' not in publication
                infographic = job['role'] in ('infographic', 'infographic-2') and publication.get('lossless') is True and 'quality' not in publication
                if publication.get('format') != 'webp' or not (banner or infographic):
                    raise ValueError('Use the fixed banner preview or lossless infographic preview')
                nonempty(publication, ['sha256', 'observed'])
                if publication.get('checked') is not True:
                    raise ValueError('Publication preview must be inspected explicitly')
                data = banner_webp(file) if banner else infographic_webp(file)
                if hashlib.sha256(data).hexdigest() != publication['sha256']:
                    raise ValueError('Publication preview hash mismatch; inspect the current encoding')
                extension = '.webp'
            published_hash = hashlib.sha256(data).hexdigest()
            # Versioned destination determined by role and ID, never arbitrary job output path.
            suffix = '-r' + str(len(entry['revisions'])) if entry.get('revisions') else ''
            relative = 'wiki/assets/' + ('banner/' if job['role'] == 'banner' else '') + job['id'] + suffix + extension
            output = within(repo, relative)
            if output.exists() and sha(output) != published_hash:
                raise ValueError('Destination exists with different bytes')
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(data)
            # sha256 remains the reviewed ORIGINAL for resumability/legacy receipts.
            entry['accepted'] = {'path': relative, 'sha256': report['sha256'],
                                 'published_sha256': published_hash, 'bytes': len(data),
                                 'attempt': attempt['number']}
        else:
            nonempty(report, ['material_defects'])
        attempt['state'] = report['decision']
        attempt['review'] = report
        evidence = within(repo, 'docs/evidence/media/' + job['id'])
        evidence.mkdir(parents=True, exist_ok=True)
        for revision in entry.get('revisions', []):
            write(evidence / f"revision-{revision['number']}.json", revision)
        write(evidence / 'job.json', job)
        (evidence / f"prompt-{attempt['number']}.txt").write_text((attempt_folder(config, job, attempt) / 'prompt.txt').read_text())
        write(evidence / f"review-{attempt['number']}.json", report)
        write(evidence / f"receipt-{attempt['number']}.json", {k: v for k, v in attempt.items() if k not in ('folder', 'review')})
        write(ledger_path, ledger)
        return {'state': report['decision'], **entry.get('accepted', {})}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', help='Explicit policy; default: learning-images.json in this checkout')
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('validate', 'prompt', 'generate', 'review', 'reconcile', 'preview-banner', 'preview-infographic'):
        p = sub.add_parser(command)
        p.add_argument('--job', required=True)
        if command == 'generate':
            p.add_argument('--repair', help='Targeted correction after rejected review; same ID/counters')
        if command == 'review':
            p.add_argument('--report', required=True)
    revision_parser = sub.add_parser('revise', help='Reopen an accepted image, preserving costs, attempts and prior evidence')
    revision_parser.add_argument('--previous-job', required=True)
    revision_parser.add_argument('--job', required=True)
    revision_parser.add_argument('--reason', required=True)
    sub.add_parser('status')
    sub.add_parser('settle', help='Settle unknown-outcome attempts older than 24 hours').add_argument(
        '--max-age-hours', type=float, default=SETTLE_AFTER_HOURS)
    sub.add_parser('check').add_argument('--provider', action='store_true',
                                       help='Read-only authenticated key/limit check; no image generation')
    sub.add_parser('init-state', help='Initialize a NEW request only; restore state for resumed work')
    args = parser.parse_args()
    try:
        config_path = Path(args.config).resolve() if args.config else Path(__file__).resolve().parent.parent / 'learning-images.json'
        if not config_path.exists():
            if args.command in ('status', 'check'):
                print(json.dumps({'state': 'not-configured', 'setup': 'pass --config (the sn command line builds one)'}))
                return 0
            raise ValueError('No image configuration: pass --config (the sn command line builds one)')
        config = load_config(config_path)
        if args.command == 'init-state':
            print(json.dumps(initialize_state(config)))
        elif args.command in ('status', 'check'):
            result = status(config)
            if args.command == 'check':
                try:
                    api_key(config)
                    result['credential_available'] = True
                except (OSError, ValueError):
                    result['credential_available'] = False
                result['spending_enabled'] = money(config['max_total_usd']) > 0
                result['model'] = MODEL
                result['repositories_exist'] = all(Path(v['repo']).is_dir() for v in config['learners'].values())
                if args.provider:
                    result['provider'] = provider_check(config)
            print(json.dumps(result, ensure_ascii=False))
        elif args.command in ('validate', 'prompt'):
            job, _ = load_job(config, args.job)
            print(compile_prompt(job) if args.command == 'prompt' else json.dumps({'valid': True, 'id': job['id']}))
        elif args.command == 'preview-banner':
            print(json.dumps(preview_banner(config, args.job), ensure_ascii=False))
        elif args.command == 'preview-infographic':
            print(json.dumps(preview_infographic(config, args.job), ensure_ascii=False))
        elif args.command == 'settle':
            print(json.dumps(settle_unknown(config, args.max_age_hours), ensure_ascii=False))
        elif args.command == 'reconcile':
            print(json.dumps(reconcile(config, args.job), ensure_ascii=False))
        elif args.command == 'revise':
            print(json.dumps(revise(config, args.previous_job, args.job, args.reason), ensure_ascii=False))
        elif args.command == 'generate':
            print(json.dumps(run_generate(config, args.job, args.repair), ensure_ascii=False))
        else:
            print(json.dumps(review(config, args.job, args.report), ensure_ascii=False))
        return 0
    except (ValueError, KeyError, OSError, InvalidOperation) as exc:
        print(json.dumps({'error': str(exc), 'type': type(exc).__name__}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
