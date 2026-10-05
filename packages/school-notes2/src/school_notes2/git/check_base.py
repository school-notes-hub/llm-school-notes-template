"""Read-only Git tree for checks, without copying assets or changing the worktree."""

from ..state.safefs import _match


class Tree:
    def __init__(self, git, base):
        self.git, self.base = git, base
        self.entries, self.content = {}, {}

    def entry(self, rel):
        if rel not in self.entries:
            result = self.git.run("ls-tree", "-z", self.base, "--", rel)
            rows = [row.split(b"\t", 1) for row in result.stdout.split(b"\0") if row]
            self.entries[rel] = next((head.split() for head, name in rows
                                      if name.decode() == rel), None)
        return self.entries[rel]

    def is_file(self, repo, rel):
        entry = self.entry(rel)
        return bool(entry and entry[0] in (b"100644", b"100755"))

    def is_dir(self, repo, rel):
        entry = self.entry(rel)
        return bool(entry and entry[1] == b"tree")

    def read_bytes(self, repo, rel):
        if not self.is_file(repo, rel):
            raise FileNotFoundError(rel)
        if rel not in self.content:
            self.content[rel] = self.git.run("cat-file", "blob", self.entry(rel)[2].decode()).stdout
        return self.content[rel]

    def read_text(self, repo, rel, *, errors="strict"):
        return self.read_bytes(repo, rel).decode("utf-8", errors)

    def glob(self, repo, root, pattern):
        result = self.git.run("ls-tree", "-r", "--name-only", "-z", self.base, "--", root)
        return sorted(name.decode() for name in result.stdout.split(b"\0")
                      if name and _match(name.decode().split("/"), pattern.split("/"))
                      and self.is_file(repo, name.decode()))
