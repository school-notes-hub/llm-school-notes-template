"""Behavior checks for spending, versioning and review boundaries; no API calls."""
import base64
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
import learning_image as m


class ExecutorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo'
        (self.repo / 'wiki/history').mkdir(parents=True)
        self.target = self.repo / 'wiki/history/topic.md'
        self.target.write_text('Verified lesson')
        self.config = {'request_id': 'trial', 'state_dir': str(self.root/'state'), 'max_total_usd': '1', 'reservation_usd': '.2', 'max_attempts': 3, 'learners': {'child': {'repo': str(self.repo), 'targets': ['wiki/history/topic.md'], 'max_usd': '1'}}}
        self.job = {'id': 'topic-banner', 'request_id': 'trial', 'learner': 'child', 'target': 'wiki/history/topic.md', 'role': 'banner', 'sources': [{'path':'wiki/history/topic.md','sha256':m.sha(self.target)}], 'plan': {'goal':'Understand', 'scope':'Scoped lesson', 'decision_reason':'Orientation', 'context':'Ancient place', 'composition':'Wide scene', 'visible_text':['Title'], 'claims':[{'text':'Verified fact','source':'lesson'}], 'style':'Clear', 'aspect_ratio':'21:9','constraints':'No inventions'}}
        self.path = self.root / 'job.json'
        self.save()
        self.calls = 0
        m.initialize_state(self.config)

    def tearDown(self):
        self.temp.cleanup()

    def save(self):
        m.write(self.path, self.job)

    def test_provider_check_only_reads_limits_and_hides_identifiers(self):
        body = {'data': {'limit': 10, 'limit_remaining': 8.5, 'usage': 1.5,
                         'limit_reset': None, 'label': 'PRIVATE_KEY_LABEL',
                         'creator_user_id': 'PRIVATE_USER'}}
        before = (Path(self.config['state_dir'])/'ledger.json').read_bytes()
        with patch.object(m, 'api_key', return_value='test-key'), patch.object(m.urllib.request, 'build_opener') as build:
            build.return_value.open.return_value = io.BytesIO(json.dumps(body).encode())
            result = m.provider_check(self.config)
            request = build.return_value.open.call_args.args[0]
            self.assertEqual(request.get_method(), 'GET')
            self.assertEqual(request.full_url, 'https://openrouter.ai/api/v1/key')
            self.assertIsNone(request.data)
        self.assertEqual(result['limit_remaining'], '8.5')
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertFalse(result['image_generation_tested'])
        self.assertEqual(before, (Path(self.config['state_dir'])/'ledger.json').read_bytes())

    def test_provider_check_redacts_failure_and_forbids_redirects(self):
        error = m.urllib.error.HTTPError('https://openrouter.ai/api/v1/key', 401,
                                         'PRIVATE_ERROR', {}, io.BytesIO(b'PRIVATE_BODY'))
        with patch.object(m, 'api_key', return_value='test-key'), patch.object(m.urllib.request, 'build_opener') as build:
            build.return_value.open.side_effect = error
            with self.assertRaisesRegex(ValueError, '^Provider credential check failed: HTTP 401$'):
                m.provider_check(self.config)
            self.assertTrue(error.closed)
            handler = build.call_args.args[0]()
            self.assertIsNone(handler.redirect_request(None, None, 302, '', {}, 'https://other.invalid/'))

    def test_provider_check_rejects_unexpected_limit_text(self):
        body = {'data': {'limit': 'PRIVATE_UNEXPECTED_TEXT'}}
        with patch.object(m, 'api_key', return_value='test-key'), patch.object(m.urllib.request, 'build_opener') as build:
            build.return_value.open.return_value = io.BytesIO(json.dumps(body).encode())
            with self.assertRaisesRegex(ValueError, '^Provider credential check failed: connection or response invalid$'):
                m.provider_check(self.config)

    def fake(self, payload, config):
        self.calls += 1
        out=io.BytesIO();Image.new('RGB',(420,180),(255-self.calls,255,255)).save(out,format='PNG')
        return {'usage':{'cost':.1},'data':[{'b64_json':base64.b64encode(out.getvalue()).decode(),'media_type':'image/png'}]}

    def generate(self, repair=None):
        return m.run_generate(self.config,self.path,repair,self.fake)

    def test_targeted_candidate_repair_needs_no_legacy_accept_and_keeps_limits(self):
        first = self.generate()
        self.assertEqual(self.generate()['number'], first['number'])
        self.assertEqual(self.calls, 1)
        repair = self.root / 'repair.txt'
        repair.write_text('Correct the title')
        for number in (2, 3):
            self.assertEqual(self.generate(repair)['number'], number)
        with self.assertRaisesRegex(ValueError, 'Attempt bound'):
            self.generate(repair)
        self.assertEqual(self.calls, 3)
        self.assertFalse(any((self.repo / 'wiki').rglob('*.webp')))

    def test_owner_grant_opens_one_new_frame_and_keeps_the_old_attempts(self):
        """Fix-51: only an explicit owner exception (a `grants` record) allows further paid
        attempts; the old attempts and costs stay, and the new frame is bounded again."""
        repair = self.root / 'repair.txt'
        repair.write_text('Correct the title')
        self.generate()
        for _ in (2, 3):
            self.generate(repair)
        with self.assertRaisesRegex(ValueError, 'Attempt bound'):
            self.generate(repair)
        ledger_path = Path(self.config['state_dir']) / 'ledger.json'
        ledger = m.read(ledger_path)
        ledger['jobs'][self.job['id']]['grants'] = [{'request': 'reopen-x', 'first_attempt': 4, 'attempts': 3}]
        m.write(ledger_path, ledger)
        for number in (4, 5, 6):
            self.assertEqual(self.generate(repair)['number'], number)
        with self.assertRaisesRegex(ValueError, 'Attempt bound'):
            self.generate(repair)
        entry = m.read(ledger_path)['jobs'][self.job['id']]
        self.assertEqual([a['number'] for a in entry['attempts']], [1, 2, 3, 4, 5, 6])
        self.assertEqual(self.calls, 6)

    def report(self, result, decision='accepted'):
        p=self.root/'review.json'
        m.write(p, {'sha256':result['sha256'],'verifier':'test','checked_at':m.now(),'observed':'Synthetic near-white test image, not teaching content','decision':decision,'checks':dict.fromkeys(m.CHECKS,'pass'),'material_defects':['test rejection'] if decision=='rejected' else []})
        return p

    def test_accepted_revision_preserves_cost_attempts_and_old_output(self):
        result = self.generate()
        accepted = m.review(self.config, self.path, self.report(result))
        previous = self.root / 'previous.json'
        m.write(previous, self.job)
        self.target.write_text('Corrected lesson')
        self.job['sources'][0]['sha256'] = m.sha(self.target)
        self.job['plan']['visible_text'] = ['Corrected title']
        self.save()
        event = m.revise(self.config, previous, self.path, 'Observed typo')
        self.assertEqual(event['attempts_used'], 1)
        self.assertEqual(event['total_usd'], '0.1')
        self.assertTrue((self.repo / accepted['path']).exists())
        repair = self.root / 'repair.txt'
        repair.write_text('Correct the title')
        result2 = self.generate(repair)
        self.assertEqual(result2['number'], 2)
        accepted2 = m.review(self.config, self.path, self.report(result2))
        self.assertIn('-r1.png', accepted2['path'])
        self.assertTrue((self.repo / accepted['path']).exists())
        self.assertEqual(m.read_ledger(self.config)['jobs'][self.job['id']]['revisions'][0]['previous_job']['plan']['visible_text'], ['Title'])

    def test_revision_keeps_verified_original_when_old_publication_was_compressed(self):
        result = self.generate()
        accepted = m.review(self.config, self.path, self.report(result))
        (self.repo / accepted['path']).unlink()
        previous = self.root / 'previous.json'
        m.write(previous, self.job)
        event = m.revise(self.config, previous, self.path, 'Later review after lossless compression')
        self.assertEqual(event['attempts_used'], 1)
        self.assertEqual(event['total_usd'], '0.1')

    def test_revision_cannot_reset_attempts_or_budget_or_identity(self):
        result = self.generate()
        m.review(self.config, self.path, self.report(result))
        previous = self.root / 'previous.json'
        m.write(previous, self.job)
        self.config['max_attempts'] = 1
        with self.assertRaisesRegex(ValueError, 'Attempt bound'):
            m.revise(self.config, previous, self.path, 'Typo')
        self.config['max_attempts'] = 3
        self.config['max_total_usd'] = '.1'
        with self.assertRaisesRegex(ValueError, 'spending bounds'):
            m.revise(self.config, previous, self.path, 'Typo')
        self.config['max_total_usd'] = '1'
        self.job['id'] = 'renamed-job'
        self.save()
        with self.assertRaisesRegex(ValueError, 'identity'):
            m.revise(self.config, previous, self.path, 'Typo')
        self.assertEqual(len(m.read_ledger(self.config)['jobs']['topic-banner']['attempts']), 1)
        self.assertIn('accepted', m.read_ledger(self.config)['jobs']['topic-banner'])

    def test_banner_preview_requires_its_own_hash_review(self):
        result = self.generate()
        preview = m.preview_banner(self.config, self.path)
        self.assertEqual(self.calls, 1)
        self.assertFalse((self.repo/'wiki/assets/banner/topic-banner.webp').exists())
        report = self.report(result)
        data = m.read(report)
        data['publication'] = {'format':'webp', 'quality':85, 'sha256':'incorrect',
                               'checked':True, 'observed':'Synthetic compressed banner inspected'}
        m.write(report, data)
        with self.assertRaisesRegex(ValueError, 'preview hash mismatch'):
            m.review(self.config, self.path, report)
        data['publication']['sha256'] = preview['sha256']
        m.write(report, data)
        accepted = m.review(self.config, self.path, report)
        self.assertEqual(m.sha(self.repo/accepted['path']), preview['sha256'])
        self.assertEqual(accepted['sha256'], result['sha256'])
        self.assertEqual(accepted['published_sha256'], preview['sha256'])
        with Image.open(self.repo/accepted['path']) as image:
            self.assertEqual(image.size, (420, 180))
        self.assertTrue(self.generate()['reused'])
        self.assertEqual(self.calls, 1)

    def test_precise_nonbanner_not_implicitly_compressed(self):
        self.job['role'] = 'infographic'
        self.save()
        result = self.generate()
        with self.assertRaisesRegex(ValueError, 'banners only'):
            m.preview_banner(self.config, self.path)
        accepted = m.review(self.config, self.path, self.report(result))
        self.assertTrue(accepted['path'].endswith('.png'))
        self.assertEqual(m.sha(self.repo/accepted['path']), result['sha256'])

    def test_lossless_infographic_publication_requires_exact_review(self):
        self.job['role'] = 'infographic-2'
        self.save()
        result = self.generate()
        preview = m.preview_infographic(self.config, self.path)
        self.assertTrue(preview['pixel_identical'])
        report = self.report(result)
        data = m.read(report)
        data['publication'] = {'format':'webp', 'quality':85, 'sha256':preview['sha256'],
                               'checked':True, 'observed':'Synthetic preview'}
        m.write(report, data)
        with self.assertRaisesRegex(ValueError, 'lossless infographic'):
            m.review(self.config, self.path, report)
        data['publication'].pop('quality')
        data['publication']['lossless'] = True
        data['publication']['sha256'] = 'wrong'
        m.write(report, data)
        with self.assertRaisesRegex(ValueError, 'preview hash mismatch'):
            m.review(self.config, self.path, report)
        data['publication']['sha256'] = preview['sha256']
        m.write(report, data)
        accepted = m.review(self.config, self.path, report)
        self.assertTrue(accepted['path'].endswith('.webp'))
        self.assertEqual(m.sha(self.repo/accepted['path']), preview['sha256'])
        self.assertEqual(self.calls, 1)

    def test_lossless_encoder_preserves_sharp_pixels_and_transparency(self):
        original = Image.new('RGBA', (41, 29))
        original.putdata([((x*31)%256, (y*47)%256, (x*y)%256, (x+y)%256)
                          for y in range(29) for x in range(41)])
        file = self.root/'sharp.png'; original.save(file)
        with Image.open(io.BytesIO(m.infographic_webp(file))) as decoded:
            self.assertEqual(decoded.size, original.size)
            self.assertEqual(decoded.convert('RGBA').tobytes(), original.tobytes())

    def test_missing_credential_fails_before_reservation_or_network(self):
        empty=self.root/'empty.env';empty.write_text('OPENROUTER_API_KEY=\n')
        self.config['env_file']=str(empty)
        before=(self.root/'state/ledger.json').read_bytes()
        with patch.dict(m.os.environ,{},clear=True), patch.object(m.urllib.request,'build_opener') as network:
            with self.assertRaisesRegex(ValueError,'Missing OPENROUTER_API_KEY'):
                m.run_generate(self.config,self.path)
            network.assert_not_called()
        self.assertEqual((self.root/'state/ledger.json').read_bytes(),before)

    def test_duplicate_does_not_spend_and_requires_review(self):
        r=self.generate();self.assertEqual(self.generate()['state'],'generated');self.assertEqual(self.calls,1)
        self.assertFalse((self.repo/'wiki/assets/banner/topic-banner.png').exists())
        m.review(self.config,self.path,self.report(r))
        self.assertTrue(self.generate()['reused']);self.assertEqual(self.calls,1)

    def test_stale_source_and_cross_learner_rejected(self):
        self.target.write_text('Changed')
        with self.assertRaises(ValueError):self.generate()
        self.job['sources'][0]['sha256']=m.sha(self.target);self.job['learner']='other';self.save()
        with self.assertRaises(KeyError):self.generate()
        self.assertEqual(self.calls,0)

    def test_path_escape_and_symlink_rejected(self):
        with self.assertRaises(ValueError):m.within(self.repo,'../outside')
        (self.repo/'escape').symlink_to(self.root)
        with self.assertRaises(ValueError):m.within(self.repo,'escape/file')

    def test_budget_blocks_before_request(self):
        self.config['max_total_usd']='.19'
        with self.assertRaises(ValueError):self.generate()
        self.assertEqual(self.calls,0)

    def test_timeout_preserves_unknown_and_blocks_other_jobs(self):
        def fail(payload,config):raise TimeoutError()
        with self.assertRaises(ValueError):m.run_generate(self.config,self.path,transport=fail)
        self.job['id']='topic-infographic';self.job['role']='infographic';self.save()
        with self.assertRaisesRegex(ValueError,'Reconcile'):self.generate()
        self.assertEqual(self.calls,0)

    def test_free_failures_cost_nothing_and_do_not_count(self):
        import socket
        def http(code):
            def call(payload, config):
                raise m.urllib.error.HTTPError(m.API, code, 'PRIVATE', {}, io.BytesIO(b'PRIVATE_BODY'))
            return call
        def refused(payload, config):
            raise m.urllib.error.URLError(ConnectionRefusedError())
        def dns(payload, config):
            raise m.urllib.error.URLError(socket.gaierror('no name'))
        for transport, kind in ((http(429), 'http-429'), (http(503), 'http-503'), (http(400), 'http-400'),
                                (refused, 'not-sent'), (dns, 'not-sent')):
            with self.assertRaisesRegex(ValueError, 'without charge'):
                m.run_generate(self.config, self.path, transport=transport)
            last = m.read(self.root/'state/ledger.json')['jobs'][self.job['id']]['attempts'][-1]
            self.assertEqual((last['state'], last['cost_usd'], last['failure']), ('failed', '0', kind))
        # Five free failures neither block other jobs nor use up the three attempts.
        repair = self.root/'repair.txt'; repair.write_text('Fix')
        for n in range(3):
            r = self.generate(repair if n else None)
            m.review(self.config, self.path, self.report(r, 'rejected'))
        self.assertEqual(self.calls, 3)
        with self.assertRaisesRegex(ValueError, 'Attempt bound'):
            self.generate(repair)
        self.assertEqual(m.spent(m.read(self.root/'state/ledger.json')), m.Decimal('0.3'))

    def test_free_failure_after_rejection_still_needs_repair(self):
        r = self.generate()
        m.review(self.config, self.path, self.report(r, 'rejected'))
        repair = self.root/'repair.txt'; repair.write_text('Fix')
        def refused(payload, config):
            raise m.urllib.error.URLError(ConnectionRefusedError())
        with self.assertRaisesRegex(ValueError, 'without charge'):
            m.run_generate(self.config, self.path, str(repair), refused)
        with self.assertRaisesRegex(ValueError, 'Repair requires'):
            self.generate()
        self.assertEqual(self.generate(repair)['state'], 'generated')

    def test_unknown_outcome_settled_after_a_day(self):
        def timeout(payload, config): raise TimeoutError()
        with self.assertRaises(ValueError): m.run_generate(self.config, self.path, transport=timeout)
        self.assertEqual(m.settle_unknown(self.config)['settled'], [])  # too young
        later = datetime.now(timezone.utc) + timedelta(hours=25)
        result = m.settle_unknown(self.config, at=later)
        self.assertEqual(result['settled'][0]['state'], 'lost')
        self.assertEqual(result['settled'][0]['cost_usd'], '0.2')
        self.assertEqual(result['total_usd'], '0.2')
        # Generation continues; the lost attempt counts toward the bound.
        r = self.generate()
        self.assertEqual(r['state'], 'generated')
        self.assertEqual(r['number'], 2)
        self.assertEqual(m.settle_unknown(self.config, at=later)['settled'], [])

    def test_settle_reconciles_a_saved_response(self):
        r = self.generate()
        ledger_path = self.root/'state/ledger.json'
        ledger = m.read(ledger_path); ledger['jobs'][self.job['id']]['attempts'][0]['state'] = 'unknown'; m.write(ledger_path, ledger)
        later = datetime.now(timezone.utc) + timedelta(hours=25)
        self.assertEqual(m.settle_unknown(self.config, at=later)['settled'][0]['state'], 'generated')

    def test_rename_cannot_reset_attempts(self):
        self.generate();self.job['id']='renamed';self.save()
        self.assertEqual(self.generate()['number'], 1)
        self.assertEqual(self.calls,1)

    def test_changed_rejected_plan_and_alias_share_three_attempts(self):
        result = self.generate()
        old = dict(self.job)
        for number in (2, 3):
            m.review(self.config, self.path, self.report(result, 'rejected'))
            self.job['id'] = 'alias-' + str(number)
            self.job['plan']['composition'] = 'Corrected scene ' + str(number)
            self.save()
            result = self.generate()
            self.assertEqual(result['number'], number)
            self.assertEqual(result['job'], old['id'])
            self.assertTrue(m.preview_banner(self.config, self.path)['review_required'])
        m.review(self.config, self.path, self.report(result, 'rejected'))
        self.job['id'] = 'alias-four'
        self.job['plan']['composition'] = 'Another correction'
        self.save()
        with self.assertRaisesRegex(ValueError, 'Attempt bound'):
            self.generate()
        ledger = m.read_ledger(self.config)
        self.assertEqual(list(ledger['jobs']), [old['id']])
        self.assertEqual(len(ledger['jobs'][old['id']]['variants']), 2)
        self.assertEqual(m.spent(ledger), m.money('.3'))
        self.assertEqual(self.calls, 3)

    def test_changed_plan_while_unreviewed_or_accepted_is_refused(self):
        result = self.generate()
        for accepted in (False, True):
            if accepted:
                m.review(self.config, self.path, self.report(result))
            self.job['plan']['composition'] = 'New scene'
            self.save()
            with self.assertRaisesRegex(ValueError, 'ítéletre váró'):
                self.generate()
            self.job['plan']['composition'] = 'Wide scene'
            self.save()
        self.assertEqual(self.calls, 1)

    def test_variant_free_failure_resumes_without_reopening_old_review(self):
        result = self.generate()
        m.review(self.config, self.path, self.report(result, 'rejected'))
        self.job['plan']['composition'] = 'Corrected scene'
        self.save()
        def disconnected(*args):
            raise ConnectionRefusedError()
        with self.assertRaisesRegex(ValueError, 'without charge'):
            m.run_generate(self.config, self.path, transport=disconnected)
        result2 = self.generate()
        self.assertEqual(result2['number'], 3)
        with self.assertRaisesRegex(ValueError, 'hash not found'):
            m.review(self.config, self.path, self.report(result))
        entry = m.read_ledger(self.config)['jobs'][self.job['id']]
        self.assertEqual(len(entry['variants']), 1)
        self.assertEqual(len(m.counted(entry['attempts'])), 2)

    def test_variant_reservation_survives_process_crash(self):
        result = self.generate()
        m.review(self.config, self.path, self.report(result, 'rejected'))
        self.job['plan']['composition'] = 'Corrected scene'
        self.save()
        def interrupted(*args):
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            m.run_generate(self.config, self.path, transport=interrupted)
        entry = m.read_ledger(self.config)['jobs'][self.job['id']]
        self.assertEqual(entry['attempts'][-1]['state'], 'unknown')
        self.assertEqual(entry['variants'][-1]['first_attempt'], 2)
        with self.assertRaisesRegex(ValueError, 'Reconcile'):
            self.generate()
        later = datetime.now(timezone.utc) + timedelta(hours=25)
        m.settle_unknown(self.config, at=later)
        result = self.generate()
        self.assertEqual(result['number'], 3)
        entry = m.read_ledger(self.config)['jobs'][self.job['id']]
        self.assertEqual(len(entry['variants']), 1)
        self.assertEqual(len(m.counted(entry['attempts'])), 3)

    def test_three_attempt_limit_and_old_best_candidate(self):
        repair=self.root/'repair.txt';repair.write_text('Fix identified issue')
        first=None
        for n in range(3):
            r=self.generate(repair if n else None);first=first or r
            m.review(self.config,self.path,self.report(r,'rejected'))
        with self.assertRaisesRegex(ValueError,'Attempt bound'):self.generate(repair)
        self.assertEqual(self.calls,3)
        m.review(self.config,self.path,self.report(first))
        accepted=m.read(self.root/'state/ledger.json')['jobs'][self.job['id']]['accepted']
        self.assertEqual(accepted['attempt'],1)
        self.assertEqual(accepted['sha256'],first['sha256'])
        self.assertNotEqual(first['sha256'],r['sha256'])
        self.assertTrue(self.generate()['reused'])

    def test_review_hash_and_missing_checks_rejected(self):
        r=self.generate();p=self.report(r);v=m.read(p);v['sha256']='wrong';m.write(p,v)
        with self.assertRaises(ValueError):m.review(self.config,self.path,p)
        v['sha256']=r['sha256'];v['checks'].pop('context');m.write(p,v)
        with self.assertRaises(ValueError):m.review(self.config,self.path,p)

    def test_changed_plan_cannot_accept_old_image(self):
        r=self.generate();p=self.report(r)
        self.job['plan']['visible_text']=['Different claim'];self.save()
        with self.assertRaisesRegex(ValueError,'Job changed'):m.review(self.config,self.path,p)

    def test_reconcile_saved_response_without_network(self):
        r=self.generate()
        ledger_path=self.root/'state/ledger.json'
        ledger=m.read(ledger_path);ledger['jobs'][self.job['id']]['attempts'][0]['state']='unknown';m.write(ledger_path,ledger)
        fixed=m.reconcile(self.config,self.path)
        self.assertEqual(fixed['state'],'generated');self.assertEqual(self.calls,1)
        self.assertEqual(fixed['sha256'],r['sha256'])

    def test_concurrent_lock(self):
        with m.locked(self.config):
            with self.assertRaises(BlockingIOError):self.generate()
        self.assertEqual(self.calls,0)

    def test_no_private_paths_sent_to_provider(self):
        text=m.compile_prompt(self.job)
        self.assertNotIn(str(self.repo),text)
        self.assertNotIn('wiki/history',text)
        self.assertNotIn('child',text)

    def test_missing_state_blocks_generation_and_readonly_status(self):
        other = self.root/'missing-state'
        self.config['state_dir'] = str(other)
        self.assertEqual(m.status(self.config)['state'], 'not-initialized')
        self.assertFalse(other.exists())
        with self.assertRaisesRegex(ValueError, 'State missing'):
            self.generate()
        self.assertEqual(self.calls, 0)
        self.assertFalse(other.exists())

    def test_initialize_preserves_existing_request_and_refuses_partial_restore(self):
        self.generate()
        original = (self.root/'state/ledger.json').read_bytes()
        self.assertEqual(m.initialize_state(self.config)['state'], 'already-initialized')
        self.assertEqual((self.root/'state/ledger.json').read_bytes(), original)
        (self.root/'state/ledger.json').unlink()
        with self.assertRaisesRegex(ValueError, 'artifacts exist'):
            m.initialize_state(self.config)

    def test_relative_config_does_not_use_home(self):
        cfg = self.root/'learning-images.json'
        value = dict(self.config, state_dir='state', env_file='.env',
                     learners={'child': {'repo': 'repo', 'targets': [self.job['target']], 'max_usd': '1'}})
        m.write(cfg, value)
        loaded = m.load_config(cfg)
        self.assertEqual(loaded['state_dir'], str(self.root/'state'))
        self.assertEqual(loaded['env_file'], str(self.root/'.env'))
        self.assertEqual(loaded['learners']['child']['repo'], str(self.repo))

    def test_relocated_state_preserves_cost_review_and_reuse(self):
        import shutil
        r = self.generate()
        ledger_path = self.root/'state/ledger.json'
        ledger = m.read(ledger_path)
        # A legacy absolute folder is ignored; use the canonical restored tree.
        ledger['jobs'][self.job['id']]['attempts'][0]['folder'] = '/missing/old/machine/path'
        m.write(ledger_path, ledger)
        moved = self.root/'relocated'
        shutil.move(self.root/'state', moved)
        self.config['state_dir'] = str(moved)
        pending = self.generate()
        self.assertEqual(self.calls, 1)
        self.assertEqual(Path(pending['folder']), moved/self.job['id']/'1')
        m.review(self.config, self.path, self.report(r))
        self.assertTrue(self.generate()['reused'])
        self.assertEqual(m.status(self.config)['spent_usd'], '0.1')
        self.assertEqual(self.calls, 1)

    def test_relocated_unknown_still_blocks(self):
        import shutil
        def fail(payload, config): raise TimeoutError()
        with self.assertRaises(ValueError):
            m.run_generate(self.config, self.path, transport=fail)
        moved = self.root/'relocated'
        shutil.move(self.root/'state', moved)
        self.config['state_dir'] = str(moved)
        with self.assertRaisesRegex(ValueError, 'Reconcile'):
            self.generate()

    def test_explicit_language_and_no_implicit_model_setting(self):
        self.job['plan']['language'] = 'English'
        self.assertIn('English nyelven', m.compile_prompt(self.job))
        self.assertNotIn('magyar nyelven', m.compile_prompt(self.job))


if __name__=='__main__':unittest.main()
