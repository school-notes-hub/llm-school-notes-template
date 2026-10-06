"""Fix-52b: the fix-52 review's findings. The 🔖 textbook check looks at the whole pointer (a
middle dot inside it does not end it), counts a Roman chapter or lesson number, is blind to
HTML comments and inline code, and judges every pointer of a line on its own (M1); the
"the textbook does not cover the topic" line stays allowed (M3); a figure stopped by unjudged
runs gets its `--clear` command even when it is also parked (M4); the status names the parked
figures with the command that frees them (M5)."""

import pytest

from school_notes2.flows import fix_progress, reopen, status_text, unjudged
from school_notes2.state.files import read_json, write_json
from school_notes2.wiki import check
from tests.flows import test_fix51
from tests.flows.test_fix49 import world  # noqa: F401
from tests.flows.test_fix51 import PARKED, ledger
from tests.flows.test_fix52 import OTHER, TOPIC, two_banners
from tests.operations.test_round import cfg  # noqa: F401


@pytest.mark.parametrize("line", [
    "🔖 Tankönyv: A reformáció · 45-47. oldal",                     # a middle dot inside the pointer
    "<sub>🗓️ Óra: 2026-09-11 · 🔖 Tankönyv: A reformáció · 45-47. oldal.</sub>",
    "🔖 Tankönyv: III. fejezet, A reformáció lecke",                 # a Roman chapter number
    "🔖 Tankönyv: IV. lecke: A reformáció",
    "🔖 Tankönyv: lecke IV, A reformáció",
    "🔖 Tankönyv: a 9. évfolyamos tankönyv ezt a témát nem tárgyalja.",   # a stated fact (M3)
    "<!-- 🔖 Tankönyv: később -->",                                  # an HTML comment is not visible
    "A `🔖 Tankönyv:` sor a lecke helyét adja.",                     # inline code is not visible
    "🔖 Tankönyv: 3. lecke · 🔖 Munkafüzet: 12. oldal",              # each pointer has its number
])
def test_a_good_or_invisible_textbook_pointer_is_not_flagged(line):
    assert check.textbook_lines(TOPIC, line) == []


@pytest.mark.parametrize("line", [
    "🔖 Tankönyv: a kapcsolódó lecke még nincs azonosítva.",
    "🔖 Tankönyv: lecke · 🗓️ Óra: 2026-09-11",                      # the next label's date is not its number
    "🔖 Tankönyv: 3. lecke · 🔖 Munkafüzet: nincs",                  # the second pointer on its own
    "🔖 Tankönyv: nincs · 🔖 Munkafüzet: 12. oldal",                 # the first one on its own
    "🔖 Tankönyv: a lecke Indiáról szól",                            # a word starting with I is no numeral
    "`kód` 🔖 Tankönyv: nincs <!-- 12 -->",                         # the comment's digit does not count
])
def test_a_pointer_without_a_number_is_flagged(line):
    assert check.textbook_lines(TOPIC, line) == [1]


def test_a_comment_over_several_lines_keeps_the_line_numbers():
    text = "# A\n<!--\n🔖 Tankönyv: majd\n-->\n🔖 Tankönyv: nincs meg\n"
    assert check.textbook_lines(TOPIC, text) == [5]


def test_the_check_message_offers_the_not_covered_line():
    assert "does not cover the topic" in check.TEXTBOOK_MESSAGE


def stopped_and_parked(ctx):
    two_banners(ctx)
    ledger(ctx, ("rejected",))
    write_json(fix_progress.path(ctx), {f"figure:{OTHER}": PARKED})
    write_json(unjudged.path(ctx), {OTHER: {"run_ids": ["a", "b", "c"], "at": "x"}})


def test_a_parked_figure_stopped_by_unjudged_runs_gets_the_clear_command(world):
    ctx, _ = world
    stopped_and_parked(ctx)
    answer = reopen.request(ctx, [f"figure:{OTHER}"])
    assert answer.startswith("Nem rögzítettem semmit")
    assert f"school-notes status --clear {ctx.name} unjudged --continue" in answer
    assert f"after the clear, school-notes status --reopen {ctx.name} figure:{OTHER}" in answer
    assert "következő javító futás" not in answer and "next fix run" not in answer
    assert list(read_json(fix_progress.path(ctx), {})) == [f"figure:{OTHER}"]     # nothing lifted
    assert status_text.collect(ctx)["parked_figures"] == []                        # its own line, not this one
    unjudged.reset(ctx)
    assert reopen.request(ctx, [f"figure:{OTHER}"]).startswith("parkolás feloldva")


def test_the_status_names_the_parked_figures_with_the_command_that_frees_them(world, monkeypatch):
    ctx, _ = world
    two_banners(ctx)
    ledger(ctx, ("rejected",))
    write_json(fix_progress.path(ctx), {f"figure:{OTHER}": PARKED})
    data = status_text.collect(ctx)
    assert data["parked_figures"] == [f"figure:{OTHER}"]
    assert (f"Parkoló ábra (fizetős keret nélkül feloldható): school-notes status --reopen {ctx.name} "
            f"figure:{OTHER}") in status_text.render(data)
    monkeypatch.setattr(test_fix51, "FID", OTHER)            # used up: freeing it brings no new attempt
    ledger(ctx)
    assert status_text.collect(ctx)["parked_figures"] == []
    assert "Parkoló ábra" not in status_text.render(status_text.collect(ctx))
