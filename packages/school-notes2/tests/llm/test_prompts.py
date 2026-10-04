"""The owner's verbatim clauses are part of the prompt contract (plan 12)."""

import pytest

from school_notes2.llm.argv import prompt

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
    assert 'Mielőtt a `check`-et hívod, menj végig a checklistán az egész oldalon:' in text
    assert 'A `check` nem talál meg mindent; a nulla figyelmeztetés nem jelenti, hogy kész vagy.' in text
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
    assert '`family_questions` []' in file_text
    with pytest.raises(ValueError):
        prompt('unknown')
