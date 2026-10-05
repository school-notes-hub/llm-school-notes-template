import pytest

from school_notes2.config import ConfigError, Limits
from school_notes2.llm import launch
from school_notes2.llm.leases import acquire
from school_notes2.state.errors import Transient


@pytest.mark.parametrize("maximum", [0, -1, True, "3", 1.5])
def test_max_agents_requires_positive_integer(maximum):
    with pytest.raises(ConfigError):
        Limits(max_agents=maximum)


def test_home_exclusion_and_global_slots(tmp_path):
    assert Limits().max_agents == 3
    with acquire(tmp_path, "a", "reviewer", 2):
        with pytest.raises(Transient, match="home volume"):
            with acquire(tmp_path, "a", "reviewer", 2):
                pass
        with acquire(tmp_path, "a", "writer", 2):
            with pytest.raises(Transient, match="max_agents"):
                with acquire(tmp_path, "b", "reviewer", 2):
                    pass
    with acquire(tmp_path, "a", "reviewer", 2):
        pass


def test_role_names_and_home_assignment():
    names = {launch.container_name("a", run_id="run", role=r, unit="topic", attempt=1)
             for r in ("writer", "reader-1", "figure-review", "recheck")}
    assert len(names) == 4
    assert launch.container_name("a", run_id="run2", role="writer") not in names
    for name in ("reader-1", "recheck", "figure-review", "reviewer"):
        assert launch._volume_role(name) == "reviewer"
    assert launch._volume_role("fix") == "writer"
