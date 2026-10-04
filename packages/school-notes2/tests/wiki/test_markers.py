import pytest

from school_notes2.wiki import markers

TEXT = "kézi\n" + markers.wrap("a", "régi\n") + "köz\n" + markers.wrap("b", "") + "vége\n"


def test_read_replace_roundtrip():
    assert markers.names(TEXT) == ["a", "b"]
    assert markers.read(TEXT, "a") == "régi\n"
    new = markers.replace(TEXT, "b", "új")
    assert markers.read(new, "b") == "új\n" and new.startswith("kézi\n") and new.endswith("vége\n")


def test_empty_all_keeps_hand_written_text():
    empty = markers.empty_all(TEXT)
    assert markers.read(empty, "a") == "" and "köz\n" in empty


def test_strip_removes_marker_lines_only():
    assert markers.strip(TEXT) == "kézi\nrégi\nköz\nvége\n"


def test_check_rejects_unpaired_and_duplicate():
    with pytest.raises(markers.MarkerError):
        markers.check(markers.OPEN.format(name="a") + "\n")
    with pytest.raises(markers.MarkerError):
        markers.check(markers.wrap("a", "") + markers.wrap("a", ""))
    with pytest.raises(markers.MarkerError):
        markers.replace("x\n", "a", "y")


@pytest.mark.parametrize("name", ["pending", "pending-section-a", "pending-figure-a"])
def test_nested_notice_cleanup_preserves_standalone_and_line_boundaries(name):
    notice = markers.wrap(name, "notice")
    other = markers.wrap("figure-a", "![image](a.png)")
    text = notice + markers.wrap("notes", notice + notice + "body\n") + other
    expected = notice + markers.wrap("notes", "body\n") + other
    assert markers.clean_nested_notices(text) == expected
    assert markers.clean_nested_notices(expected) == expected
    markers.check(expected)
    assert markers.is_notice(name)
    assert not markers.is_notice("notes")


def test_outside_uses_outermost_extent():
    text = "intro\n" + markers.wrap("notes", "heading\n" + markers.wrap("pending", "notice")) + "end\n"
    assert markers.outside(text, text.index("notice")) == text.rindex("end")
    assert markers.outside(text, 0) == 0
