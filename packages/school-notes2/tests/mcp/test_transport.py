from pathlib import Path

import pytest

from school_notes2.mcp import transport


class Listener:
    """Exercise startup without requiring the sandbox to allow sockets."""

    def __init__(self, public, fail=None):
        self.public, self.fail = public, fail
        self.events = []
        self.closed = False

    def bind(self, path):
        self.path = Path(path)
        assert self.path != self.public and not self.public.exists()
        self.path.touch(mode=0o666)
        self.events.append("bind")

    def listen(self, backlog):
        assert not self.public.exists()
        assert self.path.stat().st_mode & 0o777 == 0o600
        if self.fail == "listen":
            raise OSError("listen failed")
        self.events.append("listen")

    def setblocking(self, blocking):
        assert not blocking and not self.public.exists()
        self.events.append("nonblocking")

    def close(self):
        self.closed = True


def test_socket_publication_is_atomic_and_ready(tmp_path, monkeypatch):
    public = tmp_path / "mcp.sock"
    listener = Listener(public)
    replace = transport.os.replace
    def publish(src, dst):
        assert dst == public and not public.exists()
        assert listener.events == ["bind", "listen", "nonblocking"]
        assert Path(src).stat().st_mode & 0o777 == 0o600
        replace(src, dst)
    monkeypatch.setattr(transport.os, "replace", publish)
    transport._listen(public, listener)
    assert public.exists() and public.stat().st_mode & 0o777 == 0o600
    assert not listener.path.exists()


@pytest.mark.parametrize("failure", ["chmod", "listen", "replace"])
def test_failed_startup_cleans_up_and_can_resume(tmp_path, monkeypatch, failure):
    tmp_path.chmod(0o700)
    public = tmp_path / "mcp.sock"
    listener = Listener(public, failure)
    monkeypatch.setattr(transport.socket, "socket", lambda *a: listener)
    def fail(*args):
        assert not public.exists()
        raise OSError("startup failed")
    with monkeypatch.context() as m:
        if failure != "listen":
            m.setattr(transport.os, failure, fail)
        with pytest.raises(OSError):
            transport.serve(public, lambda _: None, [], lambda: True)
    assert listener.closed and not public.exists() and not listener.path.exists()
    resumed = Listener(public)
    transport._listen(public, resumed)
    assert public.exists() and not resumed.path.exists()
