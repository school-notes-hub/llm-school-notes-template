"""The owner's verbatim clauses are part of the prompt contract (plan 12)."""

import pytest

from school_notes2.llm import argv

ROLES = ['writer', 'fix', 'reviewer', 'figure-review', 'reader-1', 'reader-2', 'recheck']


def prompt(role, mode='file', grade=9):
    return argv.prompt(role, mode, grade=grade)


PRINCIPLE = (
    'A cél a termék lehető legjobbra fejlesztése: segítsen egy 14–17 éves gyereknek tanulni, '
    'a modern technikával egyszerűsítse és könnyítse meg a tananyag megtanulását. '
    'A tulajdonos is egy szereplő („owner agent”): dönthet, milyen legyen a termék, '
    'de csak akkor kell neki megfelelni, ha az a célt előreviszi. Teljes őszinteség: '
    'ha egy tulajdonosi ötlet határozottan rossz, azt ki kell mondani, indokkal és jobb javaslattal.'
)
STRUCTURE = (
    'A jegyzetnek úgy kell felépítenie az átadandó anyagot, ahogy egy tanuló, az emberi agy '
    'be tudja fogadni: lépésről lépésre, egymásra épülve; nem ugrálhat a témák között.'
)


@pytest.mark.parametrize('role', ['writer', 'fix', 'reviewer'])
def test_shared_owner_clauses_are_complete(role):
    text = prompt(role)
    assert text.startswith(PRINCIPLE + '\n\n')
    assert 'Ha egy szabályt vagy utasítást a célnak határozottan ártónak látsz, azt a lépést ne hajtsd végre.' in text
    assert '`owner_notes`' in text
    assert STRUCTURE in text
    assert '🔖' in text and '📎' in text
    assert text == prompt(role)


@pytest.mark.parametrize('role', ['writer', 'fix'])
def test_writer_role_and_independent_check_contract(role):
    text = prompt(role)
    assert 'A jegyzetíró szerepe: az adott terület (tantárgy) szakértője és tanára, nem szövegátíró.' in text
    assert '„1 kg = 1000 m” → javítás és jelzés; „1 kg = 1000” (lemaradt mértékegység) → „1 kg = 1000 g”' in text
    scope = 'az egész oldalon:' if role == 'writer' else 'a saját módosításodon.'
    assert 'Mielőtt a `check`-et hívod, menj végig a checklistán ' + scope in text
    assert 'A `check` nem talál meg mindent; a nulla figyelmeztetés nem jelenti, hogy kész vagy.' in text
    if role == 'writer':
        assert 'Ha a téma már létezik, az új órát oda építsd be, ahol a tanulás logikája kéri; a nem érintett bekezdéseket ne írd át.' in text
    assert 'Tulajdonos: az ábra helyes legyen' in text
    assert '„A lektor és a jegyzetíró nem ért egyet a 3. bekezdésben.”' in prompt('fix')
    assert '„A tankönyv szerint X, a füzetben Y áll. Melyiket tanultátok az órán? Addig X-et használjuk.”' in prompt('fix')


def test_nightly_uses_current_output_contract_without_transcription_goal():
    file_text, stdout_text = prompt('reviewer'), prompt('reviewer', 'stdout')
    assert '/out/review.json' in file_text and '/out/review.json' not in stdout_text
    assert '{output_instruction}' not in file_text
    assert 'az átírás hűségét a fotóhoz' not in file_text
    assert 'A tantárgy tanáraként nézd át a teljes témakört:' in file_text
    assert 'A tételek nem jelölik ki, mit nézz: amiről nincs tétel, azt is te találod meg.' in file_text
    assert 'A tankönyvet és a tanári anyagot ne nézd át önmagukban.' in file_text
    assert 'Magad nem kérdezel a családtól' in file_text
    assert 'family_questions' not in file_text
    assert 'relates_to' in file_text
    for text in (file_text, stdout_text):
        assert 'suggestion, category, relates_to' in text
        assert '`assigned.json`, `diff.patch`, `input.json`' in text
        assert '`items[{key, verdict, answer}]`' in text
        assert 'még válasz nélküli `fixed` és `disagree` lezárásokról' in text
        assert 'amit a mai kimenet nem tud külön ítéletként rögzíteni' not in text
    with pytest.raises(ValueError):
        prompt('unknown')


def test_fix_has_no_ingest_or_whole_page_assignment():
    text = prompt('fix')
    for ingest in ('Olvasd végig a kijelölt forrásoldalakat', 'Minden tanulható elemet',
                   'az új órát oda építsd be', 'Az órai jegyzetoldal rövid',
                   'az egész oldalon', 'Minden füzethibát javítottál'):
        assert ingest not in text
    assert 'a kiosztott review-tételeket, függő ábrákat és a kiosztott témaoldalak infografika-döntését kezeld' in text
    assert 'Tételen kívüli sort figyelmeztetés miatt sem írsz át' in text
    assert '`coverage[]`' in text


@pytest.mark.parametrize('role', ['writer', 'fix', 'reviewer'])
def test_prompts_use_role_names(role):
    text = prompt(role)
    assert 'Astra' not in text and 'Claude-review' not in text
    if role == 'reviewer':
        assert 'jegyzetet készítesz' not in text
        assert 'a jegyzetnek ezt kell elérnie; te ezt méred' in text
    else:
        assert '- Kérdés a forrásról.\n' in text


def test_fix_restores_required_question_and_drawing_clauses():
    text, writer = prompt('fix'), prompt('writer')
    owner_question = next(line for line in writer.splitlines() if line.startswith('A tulajdonos szabálya'))
    assert owner_question in text
    assert 'Javítsd a füzetedben is: 1 kg = 1000 g.' in text
    drawing = next(line for line in writer.splitlines() if line.startswith('Füzetrajz:'))
    assert drawing in text
    commission = next(line for line in writer.splitlines() if line.startswith('A `.school-notes/figures/'))
    assert commission in text
    assert text.count('Rossz:') == 2 and text.count('Jó:') == 2
    assert 'A kiosztott ábrajavításon belül:' in text


def test_repair_uses_writer_with_verbatim_preservation_clause():
    text = prompt('writer')
    assert 'Minden helyes állítást, magyarázatot, példát és ⚠️ javítást őrizz meg. Ezek jelölése marad. Csak a formát változtasd: a forrást leíró mondatból tárgyi állítás legyen. Ami már javítva van, azt ne javítsd újra.' in text
    assert '`mode: repair`' in text and '`repair_targets`' in text
    assert 'a szövegük külön menetben készül' in text


@pytest.mark.parametrize('role', ROLES)
def test_reader_yardstick_is_the_learners_grade(role):
    """G-4: no fixed reader age; the tool fills the configured school year."""
    ninth, twelfth = prompt(role, grade=9), prompt(role, grade=12)
    assert '{grade}' not in ninth and '9. évfolyamos' in ninth
    assert ninth.replace('9. évfolyamos', '<g>') == twelfth.replace('12. évfolyamos', '<g>')
    assert ninth == prompt(role, grade=9)


@pytest.mark.parametrize('grade', [0, -3, None, '9', True])
def test_prompt_needs_a_positive_grade(grade):
    with pytest.raises(ValueError):
        argv.prompt('writer', grade=grade)


def test_owner_question_rule_names_roles_not_learners():
    lines = {role: next(line.strip() for line in prompt(role).splitlines()
                        if line.strip().startswith('A tulajdonos szabálya')) for role in ('writer', 'fix')}
    assert lines['writer'] == lines['fix']
    assert lines['writer'].startswith('A tulajdonos szabálya (tulajdonosi szöveg, tanulónév helyett szereppel): „maradnak, minden oldalon. Bármi lehet benne, amit a tanuló vagy a tulajdonos meg tud válaszolni')


def test_reader_gets_the_complete_owner_yardstick():
    reviewer = next(line for line in prompt('reviewer').splitlines()
                    if line.startswith('A tulajdonosi mérce'))
    assert reviewer in prompt('reader-1')
    assert STRUCTURE in prompt('reader-1')


def test_figure_review_considers_teacher_ownership_and_request_route():
    text = prompt('figure-review')
    assert 'valószínűleg a tanár saját műve-e (vízjel, kiadói tördelés, fotó)' in text
    assert 'Kétség esetén `repair`; a külön engedélyt a kérelemlista útján kell tisztázni.' in text
    assert '`approved_figure_requests`' in prompt('writer')


@pytest.mark.parametrize('role', ['writer', 'fix'])
def test_writer_requires_own_svg_source_and_tool_render_for_raster(role):
    text = prompt(role)
    assert ('Saját SVG-nél a `source` maga az SVG; saját raszterhez a '
            '`tools/visual_tools.py` rajzolóeszközzel készült render kell.') in text
    assert 'maga az SVG is lehet' not in text


def test_targeted_nightly_instruction_is_not_an_owner_quote():
    line = next(line for line in prompt("reviewer", grade=9).splitlines() if line.startswith("Célzott mód"))
    assert "„" not in line and "”" not in line


@pytest.mark.parametrize('role', ['reader-1', 'reviewer'])
def test_infographic_review_instruction_precedes_output_contract(role):
    text = (argv.Path(argv.__file__).with_name('prompts') / (role + '.txt')).read_text()
    assert text.index('Hiányzó áttekintő ábrát') < text.index('{output_instruction}')
    assert 'ábra' in text[text.index('Hiányzó áttekintő ábrát'):text.index('{output_instruction}')]
