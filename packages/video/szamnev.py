"""Magyar számnév-olvasó a kapunak (K2, K10): vékony réteg a lánc olvasóján (`lanc.szavak`).

Egy olvasó van, a `lanc.szavak.egy_szo` és `egysegek`; ez a modul csak a kapu régi neveit adja.
`ertek(szo)`: egy szó értéke vagy None („hatás”, „hátra”, „egyre”, „mínusz” → None).
`szoros(szo)`: -szor/-szer/-ször számnév (az „n×” jel csak ilyen szóhoz párosodhat).
`ertekek(szavak)`: a szólista értékei, többszavas alakkal („mínusz három” = −3, ha előtte nem szám
áll; „hat mínusz három” = 6, None, 3; „két egész öt tized” = 2,5); az érték a kifejezés első szaván
áll, a többin None.
"""

from __future__ import annotations

from lanc.szavak import egy_szo, egysegek, sima  # noqa: F401  (sima: a kapu innen veszi)


def ertek(szo: str) -> float | int | None:
    return egy_szo(szo)[0]


def szoros(szo: str) -> bool:
    v, szor = egy_szo(szo)
    return v is not None and szor


def ertekek(szavak: list[str]) -> list[float | int | None]:
    ki: list = [None] * len(szavak)
    for u in egysegek(szavak):
        ki[u["idx"][0]] = u["ertek"]
    return ki
