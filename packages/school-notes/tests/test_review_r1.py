"""R1 regressions: real local Git/Poppler/bundle operations, fake transports only."""
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import types
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

import test_app as fixture
from test_app import Base, FakeAgents, FakeDrive, FakeRenderer, PNG, REPO, result
from school_notes import admin
from school_notes.agents import Agent, CHECKS
from school_notes.cli import initialize, finalize_external, main, wrapper
from school_notes.common import Blocked, EffectPending, RunLock, Window, WindowExhausted, atomic_json, digest, file_hash, private_dir, run
from school_notes.drive import Archive, DriveAPI, DriveError, FOLDER, check_classification
from school_notes.pipeline import Supervisor
from school_notes.publication import GitHub
from school_notes.report import pdf_bytes, semantic, write as report
from school_notes.state import State
from school_notes.verify import Git, merge_manifest, scan


class R1StateTests(Base):
    def test_SN01_baseline_description_cannot_create_job(self):
        self.state.revision('student','p',self.manifest('A'),baseline=True)
        self.state.revision('student','p',self.manifest('B'))
        self.assertEqual([],self.state.rows('SELECT * FROM jobs'))
        job=self.state.select_baseline('student','p')
        self.assertEqual('ingest',self.state.job(job)['kind'])
        self.assertEqual(2,self.state.job(job)['revision_seq'])

    def test_SN01_metadata_uses_last_closed_revision_not_superseded(self):
        self.state.revision('student','p',self.manifest('A'))
        first=self.state.rows('SELECT id FROM jobs')[0]['id']
        self.state.update_job(first,'complete')
        self.state.revision('student','p',self.manifest('B','b'*64))
        self.state.revision('student','p',self.manifest('C'))
        latest=self.state.job(self.state.rows('SELECT id FROM jobs ORDER BY id DESC')[0]['id'])
        self.assertEqual('metadata_update',latest['kind'])
        self.assertEqual(self.manifest('A'),latest['payload']['previous'])

    def test_SN02_background_and_role_mismatch(self):
        files=[{'id':'x','sha256':'a'}]
        background=[{'id':'x','sha256':'a','source_class':'teacher_background','uncertain':False}]
        with self.assertRaises(Blocked):
            check_classification(files,background,'teacher_background')
        background[0]['source_class']='teacher_learn'
        with self.assertRaises(Blocked):
            check_classification(files,background,'notebook')

    def test_SN03_unknown_receipt_is_retry_pending_and_cannot_fabricate_success(self):
        job=self.state.enqueue('public_release','student','x',{})
        effect=self.state.effect(job,'dispatch','x','a','effect')
        with self.assertRaises(EffectPending):
            self.state.perform_effect(effect,lambda e:None,lambda e:None)
        effect=self.state.rows('SELECT * FROM effects')[0]
        with self.assertRaises(EffectPending):
            self.state.perform_effect(effect,lambda e:self.fail('blind repeat'),lambda e:{'message':'not verified'})
        self.assertEqual('unknown',self.state.rows('SELECT * FROM effects')[0]['state'])

    def test_SN03_ack_wakes_waiting_jobs(self):
        job=self.state.enqueue('ingest','student','x',{})
        self.state.update_job(job,'ack_wait')
        self.state.wake_ack_waiters('student')
        self.assertEqual('queued',self.state.job(job)['state'])

    def test_SN20_manifest_preserves_pages_and_blocks_configuration(self):
        old={'title':'Notes','mode':'private-preview','base':'/','pages':[{'path':'wiki/a.md'},{'path':'wiki/b.md'}],
             'collections':[{'id':'notes','title':'Notes','pages':['wiki/a.md','wiki/b.md'],'pdf':True}]}
        new=copy.deepcopy(old)
        new['pages']=[new['pages'][1],new['pages'][0],{'path':'wiki/c.md'}]
        new['collections'][0]['pages']=['wiki/b.md','wiki/c.md','wiki/a.md']
        self.assertEqual(new,merge_manifest(old,new))
        for mutation in ('drop','base','license','branding','privateLinks'):
            bad=copy.deepcopy(new)
            if mutation=='drop':bad['pages'].pop(0)
            elif mutation=='base':bad['base']='/changed/'
            elif mutation=='license':bad['license']={'id':'CC-BY-4.0','attribution':'changed'}
            elif mutation=='branding':bad['branding']={'light':{'path':'wiki/logo.svg','sha256':'x'},'dark':{'path':'wiki/logo.svg','sha256':'x'}}
            else:bad['privateLinks']={'source':'https://github.com/private/source'}
            with self.assertRaises(Blocked,msg=mutation):merge_manifest(old,bad)

    def test_SN18_quoted_json_and_provider_secrets(self):
        for i,text in enumerate(('"refresh_token": "ABCDEFGHIJKLMN"','"client_secret": "ABCDEFGHIJKLMN"','ya29.ABCDEFGHIJKLMNOP','1//ABCDEFGHIJKLMNOP','github_pat_'+'a'*30,'eyJabcdef.abcdef.signature')):
            target=self.root/f'secret-{i}.json'
            target.write_text(text)
            with self.assertRaises(Blocked):scan([target],10000,100000,self.root)

    def test_SN22_unicode_longword_width_and_full_text(self):
        text='Árvíztűrő tükörfúrógép'
        long='W'*150
        target=self.root/'report.pdf'
        target.write_bytes(pdf_bytes([text,long,'https://example.test/'+long]))
        extracted=subprocess.check_output(['/usr/bin/pdftotext',str(target),'-'],text=True)
        self.assertIn(text,extracted)
        self.assertIn(long,extracted.replace('\n',''))
        bbox=subprocess.check_output(['/usr/bin/pdftotext','-bbox',str(target),'-'],text=True)
        root=ET.fromstring(bbox)
        words=list(root.iter('{http://www.w3.org/1999/xhtml}word'))
        self.assertTrue(words)
        self.assertTrue(all(float(w.attrib['xMax'])<=559.1 for w in words))
        self.assertTrue(all(float(w.attrib['xMin'])>=35.9 for w in words))

    def test_SN11_12_semantic_report_filters_and_ignores_observation_noise(self):
        status={'generated':'a','observations':[{'id':'one','learner':'student','kind':'drive','state':'complete','observed_sha':None,'ack_sha':None,'created':'today'}],
                'jobs':[{'id':1,'learner':'student','state':'blocked','kind':'ingest','phase':'classify','error':'ékezet','updated':'now'},
                        {'id':2,'learner':'other','state':'blocked','kind':'ingest','phase':'classify','error':'PRIVATE OTHER','updated':'now'}],
                'questions':[{'id':1,'job_id':2,'kind':'content','scope':'content','state':'open','prompt':'PRIVATE OTHER QUESTION'}],
                'effects':[{'stable_key':'x','job_id':2,'learner':'other','kind':'drive-upload','state':'unknown'}]}
        first=report(status,self.root/'reports','student')
        self.assertNotIn('PRIVATE OTHER',first.with_suffix('.json').read_text())
        status['observations'][0].update(id='two',created='tomorrow')
        status['jobs'][0]['updated']='later'
        self.assertEqual(first,report(status,self.root/'reports','student'))

    def test_SN14_successful_child_cannot_leave_group_descendant(self):
        pidfile=self.root/'child.pid'
        code="import subprocess;from pathlib import Path;p=subprocess.Popen(['sleep','30']);Path("+repr(str(pidfile))+").write_text(str(p.pid))"
        run([sys.executable,'-c',code],self.root)
        proc=Path('/proc')/pidfile.read_text()/'stat'
        self.assertTrue(not proc.exists() or proc.read_text().split(') ')[1].split()[0]=='Z')

    def test_SN23_resumable_chunks_checkpoint_and_resume_exact_id(self):
        target=self.root/'large.pdf'
        target.write_bytes(b'%PDF-'+b'x'*(9*1024**2))
        sha=file_hash(target)
        api=object.__new__(DriveAPI)
        api.window=None
        api.module=types.SimpleNamespace(allowed_url=lambda u:None,offset_of=lambda h,total:int(h.get('offset',0)))
        progress=[]
        calls=[]
        failed=False
        def transport(method,url,data=None,headers=None):
            nonlocal failed
            calls.append((method,url,len(data) if isinstance(data,bytes) else None,headers))
            if method=='POST':return 200,{'Location':'https://www.googleapis.com/upload/session'},{}
            if headers['Content-Range'].startswith('bytes */'):return 308,{'offset':8*1024**2},{}
            if not failed:
                failed=True
                return 308,{'offset':8*1024**2},{}
            if len(calls)==3:raise Blocked('transport interrupted')
            return 200,{}, {'id':'fixed-id'}
        api.request=transport
        with self.assertRaises(Blocked):
            api.upload('fixed-id',target,'application/pdf','parent','key',sha,checkpoint=lambda p:progress.append(copy.deepcopy(p)))
        self.assertEqual(8*1024**2,progress[-1]['offset'])
        saved=progress[-1]
        self.assertEqual('fixed-id',api.upload('fixed-id',target,'application/pdf','parent','key',sha,progress=saved)['id'])
        self.assertEqual(1,len([c for c in calls if c[0]=='POST']))
        self.assertTrue(all(c[2]<=8*1024**2 for c in calls if c[2] is not None))

    def test_SN04_draft_404_is_unknown_paginated_list_and_saved_id_reconcile(self):
        api=object.__new__(GitHub)
        requests=[]
        expected={'id':7,'tag_name':'tag','body':'School Notes bundle sha256=sha','draft':True}
        def request(method,path,**kwargs):
            requests.append(path)
            if path=='/releases/7':return expected
            if path.startswith('/releases?') and path.endswith('&page=1'):return [{'tag_name':'other'}]*100
            if path.startswith('/releases?'):return [expected]
            return None
        api.request=request
        effect={'external_id':None,'artifact_hash':'sha'}
        self.assertEqual('7',api.draft_reconcile(effect,'tag')['external_id'])
        self.assertIn('/releases?per_page=100&page=2',requests)
        requests.clear()
        self.assertEqual('7',api.draft_reconcile({**effect,'external_id':'7'},'tag')['external_id'])
        self.assertEqual(['/releases/7'],requests)
        api.request=lambda *a,**k:[]
        self.assertIsNone(api.draft_reconcile(effect,'tag'))

    def test_SN32_builder_no_bootstrap_false_proof_actual_role_and_isolation(self):
        config=json.loads((REPO/'packages/school-notes/config.example.json').read_text())['agents']
        config['python']=sys.executable
        agent=Agent(config,self.state,None,Window())
        source=private_dir(self.root/'inputs')/'image.png'
        source.write_bytes(PNG)
        job={'id':1,'revision_seq':None,'payload':{}}
        envelope={'job_id':1,'revision_seq':None,'inputs':[{'path':str(source),'sha256':file_hash(source),'kind':'source'}]}
        command=agent.build_command(job,'classify',envelope,self.root,self.root/'job','probe canary',1)
        self.assertIn('features.multi_agent=false',command['argv'])
        self.assertIn('features.hooks=false',command['argv'])
        self.assertEqual('1',command['environment']['UV_NO_SYNC'])
        self.assertTrue(Path(command['cwd']).is_relative_to(self.root/'job/private-classify'))
        self.assertEqual(file_hash(REPO/'packages/school-notes/agents/implementer.md'),command['role_sha256'])
        claude=agent.build_command(job,'public_review:aabbccddeeff0011',envelope,self.root,self.root/'job','probe',2)
        self.assertIn('--safe-mode',claude['argv'])
        self.assertIn('--system-prompt',claude['argv'])
        self.assertIn('model: claude-opus-5-5\n',claude['argv'][claude['argv'].index('--system-prompt')+1])
        self.assertFalse(any('CODEX_HOME' in a for a in command['argv']))


class R1PilotTests(Base):
    setUp=fixture.PilotTests.setUp
    def test_SN05_bad_package_does_not_block_good_package_or_baseline(self):
        self.drive.add('bad-package','ready','Broken')
        self.drive.add('bad-file','bad-package','opaque.png',b'wrong-signature')
        self.drive.add('empty-package','ready','Empty')
        self.drive.add('loose','ready','loose.png',PNG)
        with RunLock(self.config['lock_file']) as lock:
            supervisor=Supervisor(self.config,self.state,lock,lambda _:self.drive)
            supervisor.observe_drive('student',baseline=True)
            self.assertEqual('complete',self.state.meta('drive-baseline:student'))
            self.assertEqual(1,len(self.state.rows('SELECT * FROM revisions')))
            self.assertEqual(3,len(self.state.rows("SELECT * FROM jobs WHERE kind='capture_block'")))
            self.assertTrue(any(Path(json.loads(j['payload'])['staging']).joinpath('progress.json').exists() for j in self.state.rows("SELECT * FROM jobs WHERE kind='capture_block'") if json.loads(j['payload'])['staging']))

    def test_SN03_window_queues_phase_without_retry(self):
        with RunLock(self.config['lock_file']) as lock:
            supervisor=Supervisor(self.config,self.state,lock,lambda _:self.drive)
            supervisor.observe_drive('student')
            job=self.state.rows('SELECT id FROM jobs')[0]['id']
            supervisor.process=lambda _:(_ for _ in ()).throw(WindowExhausted('next run'))
            supervisor.run_once()
            retained=self.state.job(job)
            self.assertEqual('queued',retained['state'])
            self.assertNotIn('technical_retries',retained['payload'])

    def test_SN09_mutated_prepared_bytes_block_all_archive_writes(self):
        with RunLock(self.config['lock_file']) as lock:
            supervisor=Supervisor(self.config,self.state,lock,lambda _:self.drive)
            supervisor.observe_drive('student')
            job=self.state.job(self.state.rows('SELECT id FROM jobs')[0]['id'])
            supervisor.prepare(job)
            job=self.state.job(job['id'])
            f=job['payload']['manifest']['files'][0]
            classified=[{'id':f['id'],'sha256':f['prepared_sha256'],'source_class':'notebook','uncertain':False}]
            os.chmod(f['read_source'],0o600)
            Path(f['read_source']).write_bytes(PNG+b'modified')
            with self.assertRaises(Blocked):Archive(self.drive,self.state,'archive').package(job,classified)
            self.assertEqual([],self.drive.writes)

    def test_SN27_partial_photo_not_adopted_and_retry_preserves_it(self):
        with RunLock(self.config['lock_file']) as lock:
            supervisor=Supervisor(self.config,self.state,lock,lambda _:self.drive)
            supervisor.observe_drive('student')
            job=self.state.job(self.state.rows('SELECT id FROM jobs')[0]['id'])
            partial=private_dir(supervisor.job_dir(job)/'prepared-0')/'01.png'
            partial.write_bytes(b'partial')
            with self.assertRaises(Blocked):supervisor.prepare(job)
            admin.retry_render(supervisor,job['id'],'prepare')
            supervisor.prepare(self.state.job(job['id']))
            prepared=self.state.job(job['id'])['payload']['manifest']['files'][0]['prepared']
            self.assertIn('prepared-1',prepared)
            self.assertEqual(b'partial',partial.read_bytes())

    def test_SN30_worktree_estimate_includes_real_tree(self):
        (self.repo/'sources/large.bin').write_bytes(b'x'*20000)
        self.assertGreaterEqual(Git(self.repo).estimate(),20000)

    def test_SN31_wrong_initial_head_does_not_create_database(self):
        self.config['state_db']=str(self.root/'new.sqlite')
        self.config['learners']['student']['observed_sha']='a'*40
        with RunLock(self.config['lock_file']) as lock, self.assertRaises(Blocked):
            initialize(self.config,lock)
        self.assertFalse(Path(self.config['state_db']).exists())

    def test_SN08_ranges_always_begin_at_ack_and_old_finalize_blocks(self):
        ack=self.git('rev-parse','HEAD')
        self.git('checkout','-b','human')
        (self.repo/'wiki/math/index.md').write_text('# Second\n')
        self.git('add','wiki');self.git('commit','-m','second');self.git('push','origin','HEAD:main')
        self.git('checkout','main')
        with RunLock(self.config['lock_file']) as lock:
            supervisor=Supervisor(self.config,self.state,lock,lambda _:self.drive)
            supervisor.observe_git('student')
            first=self.state.rows("SELECT id FROM jobs WHERE kind='external_change_review'")[0]['id']
            (self.repo/'wiki/math/index.md').write_text('# Third\n')
            self.git('add','wiki');self.git('commit','-m','third');self.git('push','origin','HEAD:main')
            supervisor.observe_git('student')
            jobs=self.state.rows("SELECT id FROM jobs WHERE kind='external_change_review' ORDER BY id")
            self.assertEqual(ack,self.state.job(jobs[-1]['id'])['payload']['base'])
            self.assertEqual('superseded',self.state.job(first)['state'])
            # Even an apparently accepted review may not skip the live ack.
            fake=self.root/'review.json';atomic_json(fake,{})
            with self.state.db:
                self.state.db.execute("INSERT INTO reviews(job_id,path,sha256,inputs_hash,scope,state) VALUES (?,?,?,?,?,'accepted')",(first,str(fake),file_hash(fake),'x','external'))
                self.state.db.execute('UPDATE observations SET ack_sha=?',(self.git('rev-parse','HEAD'),))
            # N14-05 rejects the retained terminal job before any Git/ack work.
            before=self.state.job(first)
            with self.assertRaisesRegex(Blocked,'state'):
                finalize_external(supervisor,first)
            self.assertEqual(before,self.state.job(first))
            # Keep the original acknowledged-base assertion on an eligible
            # review_wait job, so the earlier state gate cannot mask it.
            current=jobs[-1]['id']
            with self.state.db:
                self.state.db.execute("INSERT INTO reviews(job_id,path,sha256,inputs_hash,scope,state) VALUES (?,?,?,?,?,'accepted')",(current,str(fake),file_hash(fake),'x','external'))
            self.state.update_job(current,'review_wait','external_review')
            with self.assertRaisesRegex(Blocked,'acknowledged'):
                finalize_external(supervisor,current)

    def test_SN06_chunk_union_resumes_reuses_only_accepted_visual_hashes(self):
        self.config['review_chunk_items']=2
        with RunLock(self.config['lock_file']) as lock:
            supervisor=Supervisor(self.config,self.state,lock,lambda _:self.drive)
            supervisor.agents=FakeAgents(self.state,lock)
            job_id=self.state.enqueue('external_change_review','student','review-chunks',{})
            job=self.state.job(job_id)
            inputs=[]
            for i in range(5):
                path=self.root/f'page-{i}.png';path.write_bytes(PNG+bytes([i]))
                inputs.append({'path':str(path),'sha256':file_hash(path),'kind':'pdf-page','page_key':f'notes.pdf:{i}'})
            paths=supervisor.bounded_review(job,'review',inputs,'content,visual,all_pdf_pages',reuse_visual=True)
            self.assertEqual(3,len(paths));self.assertEqual(3,len(supervisor.agents.calls))
            supervisor.bounded_review(job,'review',inputs,'content,visual,all_pdf_pages',reuse_visual=True)
            self.assertEqual(3,len(supervisor.agents.calls))
            inputs[0]['sha256']=file_hash(inputs[0]['path'])
            Path(inputs[0]['path']).write_bytes(PNG+b'new')
            inputs[0]['sha256']=file_hash(inputs[0]['path'])
            supervisor.bounded_review(job,'review',inputs,'content,visual,all_pdf_pages',reuse_visual=True)
            self.assertEqual(4,len(supervisor.agents.calls))
            self.assertEqual(1,len(json.loads(self.state.rows('SELECT * FROM reviews ORDER BY id DESC LIMIT 1')[0]['closure'])['inputs']))

    def test_SN26_scoped_attempt_and_quota_recovery_rejection(self):
        with RunLock(self.config['lock_file']) as lock:
            supervisor=Supervisor(self.config,self.state,lock,lambda _:self.drive)
            supervisor.observe_drive('student')
            job=self.state.job(self.state.rows('SELECT id FROM jobs')[0]['id'])
            proposal=admin.propose_attempts(supervisor,job['id'],'public_review:aabbccddeeff0011',4,3)
            with self.assertRaises(Blocked):admin.approve_attempts(supervisor,job['id'],'b'*64)
            admin.approve_attempts(supervisor,job['id'],proposal['proposal_sha256'])
            payload=self.state.job(job['id'])['payload'];payload['quota_block']=True
            self.state.update_job(job['id'],'retry_wait',payload=payload)
            with self.assertRaises(Blocked):admin.clear_quota(supervisor,job['id'],{'job_id':job['id'],'revision_seq':job['revision_seq'],'reason':'reset','reset_epoch':time.time()+3600})
            admin.clear_quota(supervisor,job['id'],{'job_id':job['id'],'revision_seq':job['revision_seq'],'reason':'verified elapsed reset','reset_epoch':time.time()-1})
            self.assertFalse(self.state.job(job['id'])['payload']['quota_block'])
            admin.reject_package(supervisor,job['id'],'local reference, not school ingest')
            self.assertEqual('rejected',self.state.job(job['id'])['state'])

class PublicRenderer(FakeRenderer):
    """Controlled rendered fixture; real privacy scanner, PDFs and bundler."""
    def build(self,repo,manifest,directory):
        directory=private_dir(directory)
        receipt=directory/'complete.json'
        if receipt.exists():
            saved=json.loads(receipt.read_text())
            return directory/'build',saved['images']
        build=private_dir(directory/'build')
        private_dir(build/'site/pdf')
        (build/'site/index.html').write_text('<!doctype html><html><body><h1>School Notes</h1><p>Public reviewed notes</p></body></html>')
        (build/'site/pdf/math.pdf').write_bytes(pdf_bytes(['Public matematika']))
        (build/'payload.json').write_text(json.dumps({'mode':manifest['mode'],'base':manifest['base'],'pages':manifest['pages'],'collections':[{'pdf':True}]}))
        # A controlled browser receipt is explicitly not real Chromium proof.
        (build/'browser-report.json').write_text(json.dumps({'errors':[],'pages':[{}]*len(manifest['pages'])*6}))
        run([sys.executable,str(REPO/'packages/study-site/check-public.py'),str(build)],directory)
        page=directory/'page-1.png';page.write_bytes(PNG)
        images=[{'path':str(page),'sha256':file_hash(page),'kind':'pdf-page','page_key':'math.pdf:1'}]
        atomic_json(receipt,{'images':images})
        return build,images


class FakeGitHub:
    def __init__(self,job_root):
        self.job_root=job_root
        self.requests=[]
        self.release=None
        self.assets={}
        self.complete=False
        self.crash_draft=False
        self.counter=100

    def request(self,method,path,data=None,*,raw=False,upload=False):
        self.requests.append((method,path))
        if method=='POST' and path=='/releases':
            self.release={**data,'id':7}
            if self.crash_draft:
                self.crash_draft=False
                raise OSError('crash after draft POST, before receipt')
            return self.release
        if path.startswith('/releases?'):return [self.release] if self.release else []
        if path=='/releases/7':
            if method=='PATCH':self.release.update(data)
            return self.release
        if '/assets?' in path and method=='POST':
            import urllib.parse
            name=urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)['name'][0]
            self.counter+=1
            self.assets[self.counter]={'id':self.counter,'name':name,'content':data}
            return {'id':self.counter}
        if path.startswith('/releases/7/assets?'):return [{k:v for k,v in item.items() if k!='content'} for item in self.assets.values()]
        if path.startswith('/releases/assets/'):
            return self.assets[int(path.rsplit('/',1)[1])]['content']
        if '/actions/workflows/' in path and method=='GET':
            return {'workflow_runs':[{'id':1,'display_title':'Publish '+self.release['tag_name'],'status':'completed' if self.complete else 'in_progress','conclusion':'success' if self.complete else None}]}
        if '/dispatches' in path:return {}
        raise AssertionError((method,path))

    pages=GitHub.pages
    draft_reconcile=GitHub.draft_reconcile
    asset_reconcile=GitHub.asset_reconcile
    dispatch_reconcile=GitHub.dispatch_reconcile
    settings={'workflow':'publish.yml','run_title':'Publish {tag}'}

    def live_get(self,url):
        verified=next(p for p in self.job_root.glob('*/bundle-*-verified-*') if p.is_dir())
        path='release.json' if url.endswith('release.json') else 'pdf/math.pdf'
        return (verified/path).read_bytes()


class PublicR1Tests(Base):
    setUp=fixture.PilotTests.setUp
    def public_setup(self):
        self.config['renderer']={'package':str(REPO/'packages/study-site'),'node':'unused','browser':'unused'}
        self.config['learners']['student']['public']={'repository':'owner/public-notes','site':'https://example.test','run_title':'Publish {tag}','release_input':'release','ref':'main'}
        lock=RunLock(self.config['lock_file']);lock.__enter__();self.addCleanup(lock.__exit__)
        supervisor=Supervisor(self.config,self.state,lock,lambda _:self.drive)
        supervisor.agents=FakeAgents(self.state,lock)
        with patch('school_notes.pipeline.Renderer',FakeRenderer):
            supervisor.run_once()
        private=self.state.rows("SELECT id FROM jobs WHERE kind='ingest'")[0]['id']
        self.assertEqual('complete',self.state.job(private)['state'])
        manifest=json.loads((self.repo/'publication/pilot.json').read_text())
        manifest.update(mode='public',publicationApproved=True)
        request=admin.request_public(supervisor,private,manifest)
        api=FakeGitHub(Path(self.config['jobs_dir']))
        return supervisor,private,request['job_id'],api

    def run_public(self,supervisor,api):
        from school_notes import publication
        actual_run=publication.run
        def offline_run(argv,*args,**kwargs):
            if any('check-browser.mjs' in a for a in argv):return 'controlled browser fixture'
            return actual_run(argv,*args,**kwargs)
        with patch('school_notes.publication.Renderer',PublicRenderer),patch('school_notes.publication.GitHub',return_value=api),patch('school_notes.publication.run',offline_run):
            supervisor.run_once()

    def test_SN07_21_25_public_preview_bound_before_approval_and_full_recovery(self):
        supervisor,private,public,api=self.public_setup()
        self.assertNotEqual(private,public)
        self.run_public(supervisor,api)
        job=self.state.job(public)
        self.assertEqual('approval_wait',job['state'],job['error'])
        self.assertTrue(Path(job['payload']['public_preview']).is_dir())
        self.assertTrue(job['payload']['public_proposal']['bundle_sha256'])
        self.assertEqual([],api.requests)
        sha=digest(job['payload']['public_proposal'])
        self.state.approve(public,sha)
        api.crash_draft=True
        self.run_public(supervisor,api)
        self.assertEqual('blocked',self.state.job(public)['state'])
        self.state.update_job(public,'queued')
        self.run_public(supervisor,api)
        self.assertEqual('retry_wait',self.state.job(public)['state'])
        self.assertEqual(1,len([r for r in api.requests if r==('POST','/releases')]))
        self.assertEqual(1,len([r for r in api.requests if r[0]=='POST' and '/dispatches' in r[1]]))
        api.complete=True
        self.state.update_job(public,'queued')
        self.run_public(supervisor,api)
        complete=self.state.job(public)
        self.assertEqual('complete',complete['state'],complete['error'])
        self.assertEqual('verified',complete['payload']['public_state'])
        self.assertTrue(all(e['state']=='verified' for e in self.state.rows('SELECT * FROM effects WHERE job_id=?',(public,))))
        self.assertEqual(1,len([r for r in api.requests if r==('POST','/releases')]))
        self.assertEqual(1,len([r for r in api.requests if r[0]=='POST' and '/dispatches' in r[1]]))
        self.assertTrue(any(c.startswith('public_review:') for c in supervisor.agents.calls))
        # A later reviewed private HEAD produces a separate current-head job,
        # never reopens the historical ingest/public worktree.
        self.drive.items['package']['description']='Catch-up from another learner'
        self.drive.items['package']['version']='2'
        with patch('school_notes.pipeline.Renderer',FakeRenderer):supervisor.run_once()
        newer=self.state.rows("SELECT id FROM jobs WHERE kind='metadata_update'")[0]['id']
        current=admin.request_public(supervisor,newer,self.state.job(public)['payload']['public_manifest'])
        self.assertNotEqual(public,current['job_id'])
        self.assertEqual(self.git('rev-parse','HEAD'),self.state.job(current['job_id'])['payload']['base'])

    def test_SN07_bundle_mutation_invalidates_approval_before_writes(self):
        supervisor,private,public,api=self.public_setup()
        self.run_public(supervisor,api)
        job=self.state.job(public)
        self.state.approve(public,digest(job['payload']['public_proposal']))
        bundle=next(p for p in supervisor.job_dir(job).glob('bundle-*') if (p/'site.tar.gz').exists())/'site.tar.gz'
        bundle.write_bytes(bundle.read_bytes()+b'mutation')
        self.run_public(supervisor,api)
        self.assertEqual('blocked',self.state.job(public)['state'])
        self.assertEqual([],api.requests)

    def test_SN12_actual_repeat_run_zero_duplicate_status_upload(self):
        self.config.update(drive_tool='unused')
        self.config['learners']['student'].update(status_id='status',drive_config_dir=str(self.root),drive_evidence='unused')
        with patch('school_notes.cli.load',return_value=self.config),patch('school_notes.cli.DriveAPI',return_value=self.drive),patch('school_notes.pipeline.Renderer',FakeRenderer),patch('school_notes.pipeline.Agent',side_effect=lambda c,s,l,w,**kw:FakeAgents(s,l)),patch('sys.stdout',new=io.StringIO()):
            self.assertEqual(0,main(['--config','unused','run-once']))
            count=len(self.drive.writes)
            self.assertEqual(0,main(['--config','unused','run-once']))
            self.assertEqual(count,len(self.drive.writes))

class FinalR1Tests(Base):
    def test_SN10_19_32_permission_tables_zero_one_many_and_role_body(self):
        import tomllib
        config=json.loads((REPO/'packages/school-notes/config.example.json').read_text())['agents']
        config['python']=sys.executable
        agent=Agent(config,self.state,None,Window())
        job={'id':1,'revision_seq':None,'payload':{}}
        for count in (0,1,3):
            inputs=[]
            for i in range(count):
                source=private_dir(self.root/f'input-{i}')/'source.png';source.write_bytes(PNG)
                inputs.append({'path':str(source),'sha256':file_hash(source),'kind':'source'})
            envelope={'job_id':1,'revision_seq':None,'inputs':inputs}
            contract=agent.build_command(job,'candidate',envelope,self.root/'worktree',self.root/f'job-{count}','test',1)
            table=next(arg.split('=',1)[1] for arg in contract['argv'] if arg.startswith('permissions.school-notes='))
            filesystem=tomllib.loads('permission='+table)['permission']['filesystem']
            self.assertNotIn(str(self.root/'job-0'),filesystem)
            self.assertNotIn('CODEX_HOME',contract['environment'])
            self.assertEqual(str(Path(sys.executable).parent.parent),contract['environment']['UV_PROJECT_ENVIRONMENT'])
            for item in inputs:self.assertEqual('read',filesystem[str(Path(item['path']).parent)])

    def test_SN13_stream_large_stdout_separate_stderr_SN19_model_usage_required(self):
        uv=self.root/'uv.lock';uv.write_text('offline test fixture')
        response_file=self.root/'response.json'
        script=self.root/'provider.py'
        script.write_text("import json,sys\nfrom pathlib import Path\nr=json.loads(Path(sys.argv[1]).read_text())\nprint('harmless warning',file=sys.stderr)\nif sys.argv[2]=='codex':\n for i in range(10000): print(json.dumps({'type':'item.completed','text':'x'*1000}))\n Path(sys.argv[3]).write_text(json.dumps(r))\n print(json.dumps({'type':'turn.completed'}))\nelse:\n print(json.dumps({'type':'result','subtype':'success','is_error':False,'structured_output':r}))\n")
        config={'python':sys.executable,'uv_lock':str(uv)}
        for role,model in (('codex','gpt-6.1-sol'),('claude','claude-opus-5-5')):
            argv=[sys.executable,str(script),str(response_file),role,'{result}']
            proof=self.root/f'{role}-proof.json'
            atomic_json(proof,{**{k:True for k in CHECKS},'model':model,'effort':'high','argv_hash':digest(argv),'python':sys.executable,'uv_lock_sha256':file_hash(uv),
                               'role_sha256':Agent({role:{'model':model,'effort':'high'}},self.state,None,Window()).role_settings(role)['role_sha256']})
            config[role]={'model':model,'effort':'high','argv':argv,'evidence':str(proof),'timeout':10}
        job_id=self.state.enqueue('ingest','student','streams',{})
        job=self.state.job(job_id)
        envelope={'job_id':job_id,'revision_seq':None,'inputs':[]}
        atomic_json(response_file,result(envelope))
        with RunLock(self.root/'run.lock') as lock:
            agent=Agent(config,self.state,lock,Window())
            worker=private_dir(self.root/'stream-worker')
            self.assertEqual('complete',agent.call(job,'candidate',envelope,worker,self.root/'job','test')[0]['status'])
            metadata=json.loads(next((self.root/'job').glob('attempt-*/transport.json')).read_text())
            log=Path(metadata['stdout']['path'])
            self.assertGreater(log.stat().st_size,8*1024**2)
            self.assertNotIn('harmless warning',log.read_text())
            self.assertIn('harmless warning',log.with_name('events.log.stderr').read_text())
            with self.assertRaisesRegex(Blocked,'runtime model'):
                agent.call(job,'review',envelope,self.root,self.root/'job','test')


class AdditionalPilotR1Tests(Base):
    setUp=fixture.PilotTests.setUp

    def test_SN15_interactive_tty_works_and_child_cleanup_before_receipt(self):
        import pty
        # pty.fork creates a real controlling terminal; the trusted command
        # verifies /dev/tty after wrapper puts its group into the foreground.
        script=self.root/'tty-wrapper.py'
        marker=self.root/'tty-ok'
        config=self.root/'wrapper-config.json';atomic_json(config,self.config)
        script.write_text("import json,sys\nfrom pathlib import Path\nfrom school_notes.cli import wrapper\nfrom school_notes.state import State\nfrom school_notes.common import RunLock\nc=json.loads(Path(sys.argv[1]).read_text())\ns=State(c['state_db'])\nwrapper(c,'student',[sys.executable,'-c',\"import os;from pathlib import Path;fd=os.open('/dev/tty',os.O_RDWR);assert os.tcgetpgrp(fd)==os.getpgrp();Path(\"+repr(sys.argv[2])+\").write_text('tty ok')\"])\ns.close()\n")
        pid,fd=pty.fork()
        if pid==0:
            os.execve(sys.executable,[sys.executable,str(script),str(config),str(marker)],{**os.environ,'PYTHONPATH':str(REPO/'packages/school-notes')})
        output=bytearray()
        try:
            while True:
                try:chunk=os.read(fd,4096)
                except OSError:break
                if not chunk:break
                output.extend(chunk)
        finally:os.close(fd)
        _,status=os.waitpid(pid,0)
        self.assertEqual(0,os.waitstatus_to_exitcode(status),output.decode(errors='replace'))
        self.assertEqual('tty ok',marker.read_text())
        receipt=next(Path(self.config['jobs_dir']).glob('interactive-*/receipt.json'))
        self.assertEqual('recorded',json.loads(receipt.read_text())['state'])

    def test_SN17_fix_round_cumulative_changes_and_SN24_source_paths(self):
        class FixOnce(FakeAgents):
            fixed=False
            def call(self,job,phase,*args,**kwargs):
                response,path=super().call(job,phase,*args,**kwargs)
                if phase.startswith('source_review:') and not self.fixed:
                    self.fixed=True
                    response['status']='changes_requested'
                    response['uncertainties']=['explicit first fix']
                return response,path
        with RunLock(self.config['lock_file']) as lock,patch('school_notes.pipeline.Renderer',FakeRenderer):
            supervisor=Supervisor(self.config,self.state,lock,lambda _:self.drive)
            supervisor.agents=FixOnce(self.state,lock)
            supervisor.run_once()
            job=self.state.job(self.state.rows("SELECT id FROM jobs WHERE kind='ingest'")[0]['id'])
            self.assertEqual('complete',job['state'],job['error'])
            self.assertEqual(1,job['payload']['fix_round'])
            self.assertEqual(2,len(supervisor.agents.contexts))
            self.assertIn('cumulative_existing_changes',supervisor.agents.contexts[-1])
            source=Path(job['payload']['git_sources'][0]['path']).relative_to(job['payload']['worktree'])
            self.assertRegex(source.parts[1],r'^\d{4}-\d\d-\d\d-math-package-\d+$')
            family=[item for item in self.drive.items.values() if item.get('parents')==['output']]
            self.assertTrue(family)
            self.assertRegex(family[0]['name'],r'^math-[a-f0-9]{16}\.pdf$')

    def test_SN16_unknown_push_with_newer_revision_reconciles_before_source_gate(self):
        with RunLock(self.config['lock_file']) as lock,patch('school_notes.pipeline.Renderer',FakeRenderer):
            supervisor=Supervisor(self.config,self.state,lock,lambda _:self.drive)
            supervisor.agents=FakeAgents(self.state,lock)
            actual=Git.git
            failed=False
            def crash(git,*args,**kwargs):
                nonlocal failed
                output=actual(git,*args,**kwargs)
                if args[0]=='push' and not failed:
                    failed=True
                    raise OSError('crash after push')
                return output
            with patch.object(Git,'git',crash):supervisor.run_once()
            job=self.state.job(self.state.rows("SELECT id FROM jobs WHERE kind='ingest'")[0]['id'])
            self.assertEqual('push',job['phase'])
            self.drive.items['package'].update(description='Catch-up from another learner',version='2')
            self.state.update_job(job['id'],'queued')
            supervisor.run_once()
            self.assertEqual('complete',self.state.job(job['id'])['state'],self.state.job(job['id'])['error'])
            self.assertEqual([],self.state.rows("SELECT * FROM jobs WHERE kind='external_change_review'"))
            effect=self.state.rows("SELECT * FROM effects WHERE stable_key LIKE 'private-push:%' ORDER BY updated")[0]
            self.assertEqual('verified',effect['state'])

    def test_SN26_new_subject_exact_config_applied_supervisor_then_reviewed(self):
        (self.repo/'tools/subjects.json').write_text(json.dumps({'labels':{'header':'Header'},'subjects':{}}))
        self.git('add','tools/subjects.json');self.git('commit','-m','Fixture learner labels');self.git('push','origin','HEAD:main')
        head=self.git('rev-parse','HEAD')
        with self.state.db:self.state.db.execute('UPDATE observations SET observed_sha=?,ack_sha=?',(head,head))
        class NewSubject(FakeAgents):
            def call(self,job,phase,envelope,cwd,directory,instructions):
                if phase!='candidate':return super().call(job,phase,envelope,cwd,directory,instructions)
                self.calls.append(phase)
                root=Path(cwd)
                (root/'wiki/science').mkdir(exist_ok=True)
                (root/'wiki/science/lesson.md').write_text('# Science\nReviewed learning notes\n')
                (root/'wiki/math/source.md').write_text('# Source\ncontent_sha256: '+envelope['inputs'][0]['sha256']+'\n')
                (root/'wiki/log.md').write_text('# Log\nnew subject\n')
                response=result(envelope)
                changes=Git(root,self.lock).changes(job['payload']['base'],job['payload'].get('supervisor_config_paths',{}),job['payload'].get('git_sources',[]))
                response['file_changes']=[{'path':n,'sha256':sha} for n,sha in changes.items() if not n.startswith(('sources/','tools/'))]
                response['manifest_proposal']=json.loads((root/'publication/pilot.json').read_text())
                response['manifest_proposal']['pages'].append({'path':'wiki/science/lesson.md'})
                path=private_dir(Path(directory)/f'new-subject-{len(self.calls)}')/'result.json';atomic_json(path,response)
                return response,path
        with RunLock(self.config['lock_file']) as lock,patch('school_notes.pipeline.Renderer',FakeRenderer):
            supervisor=Supervisor(self.config,self.state,lock,lambda _:self.drive)
            supervisor.agents=NewSubject(self.state,lock)
            supervisor.run_once()
            job=self.state.job(self.state.rows("SELECT id FROM jobs WHERE kind='ingest'")[0]['id'])
            self.assertEqual('approval_wait',job['state'],job['error'])
            proposal={'tools/subjects.json':{'labels':{'header':'Header'},'subjects':{'science':{'name':'Science','emoji':'⚗','light':'#ffffff','dark':'#000000','icon':'flask'}}}}
            frozen=admin.propose_subject(supervisor,job['id'],proposal)
            with self.assertRaises(Blocked):admin.approve_subject(supervisor,job['id'],'b'*64)
            admin.approve_subject(supervisor,job['id'],frozen['proposal_sha256'])
            supervisor.run_once()
            completed=self.state.job(job['id'])
            self.assertEqual('complete',completed['state'],completed['error'])
            self.assertEqual(proposal['tools/subjects.json'],json.loads((self.repo/'tools/subjects.json').read_text()))
            self.assertEqual('direct-vm-admin',self.state.rows("SELECT origin FROM questions WHERE scope='new_subject'")[0]['origin'])

    def test_SN06_external_follows_affected_summary_and_rehydrates_ignored_sources(self):
        source=self.repo/'sources/ignored-source.png';source.write_bytes(PNG+b'actual affected source')
        unrelated=self.repo/'sources/ignored-unrelated.png';unrelated.write_bytes(PNG+b'unrelated bytes')
        exclude=self.repo/'.git/info/exclude';exclude.write_text(exclude.read_text()+'\nignored-*\n')
        sha=file_hash(source)
        (self.repo/'wiki/math/summary.md').write_text('---\ncontent_sha256:\n  01.png: '+sha+'\n---\n# Source summary\n')
        (self.repo/'wiki/math/lesson.md').write_text('---\nsources:\n  - { resource: summary.md }\n---\n# Affected lesson\n')
        (self.repo/'wiki/math/unrelated-source.md').write_text('# Unrelated\ncontent_sha256: '+file_hash(unrelated)+'\n')
        self.git('add','wiki');self.git('commit','-m','Baseline source-summary fixtures');self.git('push','origin','HEAD:main')
        base=self.git('rev-parse','HEAD')
        with self.state.db:self.state.db.execute('UPDATE observations SET observed_sha=?,ack_sha=?',(base,base))
        (self.repo/'wiki/math/lesson.md').write_text((self.repo/'wiki/math/lesson.md').read_text()+'Changed explanation\n')
        self.git('add','wiki');self.git('commit','-m','External exact content');self.git('push','origin','HEAD:main')
        with RunLock(self.config['lock_file']) as lock,patch('school_notes.pipeline.Renderer',FakeRenderer):
            supervisor=Supervisor(self.config,self.state,lock,lambda _:self.drive)
            supervisor.agents=FakeAgents(self.state,lock)
            supervisor.observe_git('student')
            job=self.state.job(self.state.rows("SELECT id FROM jobs WHERE kind='external_change_review'")[0]['id'])
            self.state.update_job(job['id'],'running')
            supervisor.external_review(job)
            current=self.state.job(job['id'])
            self.assertEqual('review_wait',current['state'],current['error'])
            evidence=[i for i in current['payload']['external_review_envelope']['inputs'] if i['kind']=='external-source']
            self.assertEqual([sha],[i['sha256'] for i in evidence])
            self.assertTrue(Path(evidence[0]['path']).is_relative_to(supervisor.job_dir(job)))
            self.assertFalse((Path(current['payload'].get('external_build')).parent/'external-worktree/sources/ignored-source.png').exists())

    def test_SN05_repeated_unsupported_capture_reuses_preserved_bytes(self):
        self.drive.add('unsupported','ready','Unsupported')
        self.drive.add('opaque','unsupported','opaque.png',b'unsupported preserved bytes')
        with RunLock(self.config['lock_file']) as lock:
            supervisor=Supervisor(self.config,self.state,lock,lambda _:self.drive)
            supervisor.observe_drive('student')
            count=self.drive.downloads.count('opaque')
            supervisor.observe_drive('student')
            self.assertEqual(count,self.drive.downloads.count('opaque'))
            self.assertEqual(1,len(self.state.rows("SELECT * FROM revisions r JOIN packages p ON p.id=r.package_id WHERE p.source_id='package'")))
            self.assertEqual([],self.state.rows("SELECT * FROM revisions r JOIN packages p ON p.id=r.package_id WHERE p.source_id='unsupported'"))

class RecoveryContractR1Tests(Base):
    def test_SN23_expired_session_retains_id_and_unknown_cannot_restart(self):
        target=self.root/'file.pdf';target.write_bytes(b'%PDF-test')
        sha=file_hash(target)
        api=object.__new__(DriveAPI);api.window=None
        api.module=types.SimpleNamespace(allowed_url=lambda u:None)
        calls=[]
        def transport(method,url,data=None,headers=None):
            calls.append((method,url,data))
            if url.endswith('/expired'):raise DriveError(404)
            if method=='POST':return 200,{'Location':'https://www.googleapis.com/upload/new'},{}
            return 200,{}, {'id':'fixed'}
        api.request=transport
        api.reconcile=lambda e:{'absent':True}
        progress={'session':'https://www.googleapis.com/upload/expired','offset':0,'file_id':'fixed','sha256':sha,'bytes':target.stat().st_size}
        checkpoints=[]
        self.assertEqual('fixed',api.upload('fixed',target,'application/pdf','parent','key',sha,progress=progress,checkpoint=checkpoints.append)['id'])
        post=[c for c in calls if c[0]=='POST']
        self.assertEqual('fixed',post[0][2]['id'])
        self.assertEqual('fixed',checkpoints[0]['file_id'])
        calls.clear();api.reconcile=lambda e:None
        with self.assertRaises(EffectPending):api.upload('fixed',target,'application/pdf','parent','key',sha,progress=progress)
        self.assertEqual([], [c for c in calls if c[0]=='POST'])

    def test_SN26_stale_reconciliation_preserves_answers_without_authorization(self):
        self.state.revision('student','p',self.manifest('A'))
        old=self.state.rows('SELECT id FROM jobs')[0]['id']
        question=self.state.question(old,'content','author','who authored source')
        self.state.answer(question,'classmate catch-up','admin-content')
        self.state.revision('student','p',self.manifest('B'))
        supervisor=Supervisor({'agents':{},'learners':{}},self.state,None,None)
        reconciled=admin.reconcile_job(supervisor,old)
        current=self.state.job(reconciled['job_id'])
        self.assertEqual('reconciled',self.state.job(old)['state'])
        self.assertEqual('queued',current['state'])
        self.assertEqual('classmate catch-up',current['payload']['reconciled_from']['answers'][0]['answer'])
        self.assertNotIn('public_proposal',current['payload'])

class StaleCommitRecoveryR1Tests(Base):
    setUp=fixture.PilotTests.setUp

    def test_SN26_unknown_local_commit_reconciles_readonly_when_source_is_stale(self):
        baseline=self.git('rev-parse','HEAD')
        with RunLock(self.config['lock_file']) as lock,patch('school_notes.pipeline.Renderer',FakeRenderer):
            supervisor=Supervisor(self.config,self.state,lock,lambda _:self.drive)
            supervisor.agents=FakeAgents(self.state,lock)
            actual=self.state.effect_state
            failed=False
            def crash(key,state,receipt=None,external_id=None):
                nonlocal failed
                if key.startswith('private-commit:') and state=='verified' and not failed:
                    failed=True
                    raise OSError('crash after commit before receipt')
                return actual(key,state,receipt,external_id)
            with patch.object(self.state,'effect_state',crash):supervisor.run_once()
            job=self.state.job(self.state.rows("SELECT id FROM jobs WHERE kind='ingest'")[0]['id'])
            self.assertEqual('commit',job['phase'])
            self.drive.items['package'].update(description='New metadata after interrupted commit',version='2')
            supervisor.observe_drive('student')
            self.assertFalse(self.state.current(self.state.job(job['id'])))
            result=admin.resume_effects(supervisor,job['id'])
            self.assertEqual('blocked',result['state'])
            self.assertEqual('push',self.state.job(job['id'])['phase'])
            self.assertEqual('verified',self.state.rows("SELECT state FROM effects WHERE kind='git-commit'")[0]['state'])
            self.assertEqual(baseline,self.git('rev-parse','refs/remotes/origin/main'))
            current=admin.reconcile_job(supervisor,job['id'])
            self.assertNotEqual(job['id'],current['job_id'])
            self.assertEqual('reconciled',self.state.job(job['id'])['state'])

    def test_SN15_real_terminal_ctrl_c_stops_child_before_receipt(self):
        import pty
        import select
        import signal
        script=self.root/'ctrl-c-wrapper.py'
        config=self.root/'config.json';atomic_json(config,self.config)
        script.write_text("import json,sys\nfrom pathlib import Path\nfrom school_notes.cli import wrapper\nfrom school_notes.state import State\nfrom school_notes.common import RunLock\nc=json.loads(Path(sys.argv[1]).read_text());s=State(c['state_db'])\nwrapper(c,'student',[sys.executable,'-c',\"import time;print('CHILD_READY',flush=True);time.sleep(20)\"])\ns.close()\n")
        pid,fd=pty.fork()
        if pid==0:
            os.execve(sys.executable,[sys.executable,str(script),str(config)],{**os.environ,'PYTHONPATH':str(REPO/'packages/school-notes')})
        output=bytearray()
        deadline=time.monotonic()+10
        sent=False
        try:
            while time.monotonic()<deadline:
                if not select.select([fd],[],[],0.2)[0]:continue
                try:chunk=os.read(fd,4096)
                except OSError:break
                if not chunk:break
                output.extend(chunk)
                if not sent and b'CHILD_READY' in output:
                    os.write(fd,b'\x03')
                    sent=True
            else:
                os.kill(pid,signal.SIGTERM)
                self.fail('Ctrl-C wrapper did not finish within local test deadline')
        finally:os.close(fd)
        _,status=os.waitpid(pid,0)
        self.assertTrue(sent)
        self.assertEqual(0,os.waitstatus_to_exitcode(status),output.decode(errors='replace'))
        receipt=json.loads(next(Path(self.config['jobs_dir']).glob('interactive-*/receipt.json')).read_text())
        self.assertEqual(-signal.SIGINT,receipt['exit_code'])
        self.assertEqual('recorded',receipt['state'])
        with RunLock(self.config['lock_file']):pass
