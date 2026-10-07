"""`sn publish <t> [--reviewed] [--build-only DIR]` (plan 3.2, 5): release the working copy's
HEAD to the public site.

In order, stopping at the first failure:

1. preconditions: on `main`, a clean worktree (nothing modified, nothing untracked) and
   `sn done` 0;
2. `git push origin main` (HTTPS, `gh`'s token; never forced);
3. the gh-pages clone `~/.local/share/school-notes/site/<t>` fetched (one per learner);
4. the site built from HEAD (`git archive`, never the worktree) into a temporary folder; the
   build runs the browser check and the public gate (`check-public.py`) – a finding stops
   here, **before** anything goes to gh-pages;
5. the gh-pages push (only the changed files; a parent commit, never forced);
6. the live check (the site's `publish.json` names HEAD; a timeout is only a warning);
7. with `--reviewed`: `claude-reviewed` moves forward to HEAD (fast-forward only);
8. the temporary build is removed; one line goes into the JSONL log.

`--build-only DIR` checks the preconditions and builds HEAD into DIR (kept), without any push:
for comparing a build with the live site."""

import tempfile
from pathlib import Path

from .. import VERSION
from ..git import repos
from ..site import build as site_build
from ..site import publish as site_publish
from . import done
from .common import RELEASE, https_url, require_github, today


def preconditions(local, git, out) -> str | None:
    """The reason publishing may not start, or None."""
    branch = git.out("symbolic-ref", "--quiet", "--short", "HEAD", check=False).strip()
    if branch != "main":
        return f"a munkapéldány nem a main ágon áll ({branch or 'leválasztott HEAD'})"
    dirty = git.out("status", "--porcelain", "--untracked-files=all").splitlines()
    if dirty:
        return "a munkafa nem tiszta: " + "; ".join(sorted(dirty)[:10])
    if done.report(local.repo, out) != 0:
        return "az sn done nem 0"
    return None


def renderer(local) -> site_build.Renderer:
    """The release's study-site renderer; the PDF cache is kept per learner."""
    t = local.cfg.timeouts
    return site_build.Renderer(
        study_site=RELEASE / "packages" / "study-site", browser=local.cfg.browser,
        pdf_cache=local.cfg.state_dir / "pdf-cache" / local.name, build_s=t.build_s,
        browser_check_s=t.browser_check_s, check_public_s=t.check_public_s)


def effective_remote(git, what: str) -> None:
    """Both the fetch and the push address of `origin` (after any `insteadOf`/`pushurl`) must
    be https://github.com/…; only then may git get the token."""
    for args in (("remote", "get-url", "origin"), ("remote", "get-url", "--push", "origin")):
        require_github(git.out(*args).strip(), what)


def site_git(local):
    """The learner's single gh-pages clone (created on first use, HTTPS remote)."""
    path = local.site_clone()
    url = require_github(https_url(local.student.site_repo), "the site repo")
    if not (path / ".git").exists():
        path.mkdir(parents=True, exist_ok=True)
        local.git(path).run("init", "--quiet", str(path), cwd=path)
    git = local.git(path, network=True)
    current = git.out("config", "--get", "remote.origin.url", check=False).strip()
    if current != url:
        git.run("remote", "remove", "origin", check=False)
        git.run("remote", "add", "origin", url)
    effective_remote(git, "the site clone's origin")
    return git


def run(local, reviewed: bool = False, build_only: Path | None = None, out=print) -> int:
    git = local.git()
    reason = preconditions(local, git, out)
    head = git.out("rev-parse", "--verify", "HEAD").strip()
    if reason:
        out(f"nem adom ki: {reason}")
        local.record("publish", "refused", target=head, reason=reason)
        return 1
    if build_only is not None:
        record = site_build.build(git, head, Path(build_only), renderer(local), changed=None, log=local.quiet)
        out(f"build: {record.output / 'site'} ({record.pages} lap, {record.duration_s} s)")
        local.record("publish", "built", target=head, pages=record.pages)
        return 0
    effective_remote(git, "the working copy's origin")
    require_github(https_url(local.student.site_repo), "the site repo")
    net = local.git(network=True)
    net.run("push", "--porcelain", "origin", "HEAD:refs/heads/main", timeout=local.cfg.timeouts.push_s)
    if repos.ls_remote(net, "refs/heads/main", local.cfg.timeouts.ls_remote_s) != head:
        out("a main push nem látszik a GitHubon")
        local.record("publish", "error", target=head, reason="main push not visible")
        return 1
    site = site_git(local)
    site_publish.fetch_gh_pages(site, local.quiet, fetch_s=local.cfg.timeouts.fetch_s,
                                ls_remote_s=local.cfg.timeouts.ls_remote_s)
    needed, why = site_publish.publish_needed(git, site, head, VERSION)
    commit, live = None, None
    if needed:
        changed = site_publish.changed_since_publish(git, site, head)
        with tempfile.TemporaryDirectory(prefix=f"sn-publish-{local.name}-") as tmp:
            try:
                record = site_build.build(git, head, Path(tmp), renderer(local), changed=changed, log=local.quiet)
            except site_build.BuildContentError as exc:
                for problem in exc.problems[:30]:
                    out(f"  {problem['file']}: {problem['message']}")
                out("nem adom ki: a build vagy a nyilvános kapu hibát talált (a gh-pages változatlan)")
                local.record("publish", "held", target=head, problems=len(exc.problems))
                return 1
            published = site_publish.publish(
                site, record.output / "site", student=local.name, source_commit=head,
                run_id=f"helyi-{today()}", tool_version=VERSION, log=local.quiet,
                fetch_s=local.cfg.timeouts.fetch_s, push_s=local.cfg.timeouts.push_s,
                ls_remote_s=local.cfg.timeouts.ls_remote_s)
            commit = published.commit
            url = site_publish.live_url(record.output)
            live = site_publish.wait_until_live(url, head, local.quiet) if url else None
        out(f"gh-pages: {commit or 'nem változott'}; élő: {'igen' if live else 'még nem' if url else '–'}")
    else:
        out(f"gh-pages: nincs teendő ({why})")
    if reviewed:
        net.run("push", "--porcelain", "origin", "HEAD:refs/heads/claude-reviewed",
                timeout=local.cfg.timeouts.push_s)
        out(f"claude-reviewed → {head[:12]}")
    local.record("publish", "ok", target=head, site_commit=commit, live=live, reviewed=reviewed,
                 reason=why)
    return 0
