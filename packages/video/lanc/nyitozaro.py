"""Nyitókép (cím, a podcast-intró elejével) és zárókép (az utolsó kép elhalványul, visszajön a cím, outró).

A lánc teszi be a --vegleges összefésülésnél, az író kódja nem tartalmazza. A kapu (K1–K12) a fő renderen fut,
így a K8 felirat-szabálya és a K11 hossza ezt a két részt nem látja; a K8a az összefésült fájlon méri, hogy
továbbra is pontosan egy videó- és egy hangsáv van.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from .hangok import Megallt
from .render import FPS, MANIM_SH, MINOSEG

NYITO_S, ZARO_S = 5.0, 5.0
ZENE = Path(os.environ.get("VIDEO_ZENE", Path.home() / "jegyzet" / "podcast-zene"))
INTRO, OUTRO = ZENE / "intro.mp3", ZENE / "outro.mp3"
ZENE_HANGERO = 0.7                     # a podcast keverésével egyezően
NYITO_HALKUL_S, ZARO_HALKUL_S = 1.0, 2.0
JELENET = Path(__file__).resolve().parent / "nyitozaro_jelenet.py"


def _h1(ut: Path) -> str | None:
    """Az első # sor szövege, a vezető jelek (emoji, szóköz) nélkül."""
    if not ut.exists():
        return None
    for sor in ut.read_text(encoding="utf-8").splitlines():
        if sor.startswith("# "):
            return re.sub(r"^[^\w(„]+", "", sor[2:]).strip() or None
    return None


def cimek(repo: Path | None, tantargy: str, lap: str, cim: str | None, tantargy_nev: str | None) -> tuple[str, str]:
    """(tantárgy, cím): a hívásból, különben a tanulói wiki tantárgyi indexének és a témalapnak a címsorából."""
    oldal = lap.rsplit("-", 1)[0]
    wiki = repo / "wiki" / tantargy if repo else None
    targy = tantargy_nev or (wiki and _h1(wiki / "index.md"))
    tema = cim or (wiki and _h1(wiki / f"{oldal}.md"))
    if not targy or not tema:
        hol = f"{wiki}/index.md, {oldal}.md" if wiki else "tesztmappa"
        raise Megallt(f"nyitókép: nincs {'tantárgynév' if not targy else 'cím'} ({hol}); add meg: "
                      "--tantargy-nev és --cim")
    return targy, tema


def _hossz(ut: Path) -> float:
    p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=nb_frames",
                        "-of", "json", str(ut)], capture_output=True, text=True, check=True)
    return int(json.loads(p.stdout)["streams"][0]["nb_frames"]) / FPS


def kepek(fo_mp4: Path, media: Path, minoseg: str, targy: str, cim: str, log_ut: Path,
          idokorlat_s: float) -> dict:
    """Az utolsó kocka kivétele, a két kép renderje; visszaad: {nyito, zaro: Path, nyito_s, zaro_s: float}."""
    for z in (INTRO, OUTRO):
        if not z.exists():
            raise Megallt(f"nyitókép: hiányzik a zene: {z}")
    utolso = media / "nyitozaro" / "utolso.png"
    utolso.parent.mkdir(parents=True, exist_ok=True)
    kapcsolo, almappa = MINOSEG[minoseg]
    env = {**os.environ, "NZ_CIM": cim, "NZ_TANTARGY": targy, "NZ_UTOLSO": str(utolso),
           "NZ_NYITO_S": str(NYITO_S), "NZ_ZARO_S": str(ZARO_S)}
    with open(log_ut, "a", encoding="utf-8") as log:
        log.write("\n=== nyitó- és zárókép\n")
        log.flush()
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-sseof", "-1", "-i", str(fo_mp4), "-update", "1",
                        str(utolso)], check=True, stdout=log, stderr=subprocess.STDOUT)
        try:
            p = subprocess.run([str(MANIM_SH), kapcsolo, "--fps", str(FPS), "--progress_bar", "none",
                                "--media_dir", str(media / "nyitozaro"), str(JELENET), "Nyito", "Zaro"],
                               cwd=media, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=idokorlat_s)
        except subprocess.TimeoutExpired:
            raise Megallt(f"nyitókép: a render nem fért az időkorlátba ({idokorlat_s:.0f} s)") from None
    hely = media / "nyitozaro" / "videos" / JELENET.stem / almappa
    ki = {"nyito": hely / "Nyito.mp4", "zaro": hely / "Zaro.mp4"}
    if p.returncode or not all(v.exists() for v in ki.values()):
        raise Megallt(f"nyitókép: a render nem sikerült (kód {p.returncode}; video.log)")
    return {**ki, "nyito_s": _hossz(ki["nyito"]), "zaro_s": _hossz(ki["zaro"])}


def osszefesul(nz: dict, fo_mp4: Path, wav: Path, cel: Path, log_ut: Path, *, threads: int | None = None) -> None:
    """Nyitókép + fő videó + zárókép egy videósávba (újrakódolva: egyenletes kulcskocka 2 s-onként, 1:1 képpont, bt709,
    mert a másolt összefűzés lejátszóban akadhat), alá intró + narráció + outró
    egy hangsávba; felirat-, fejezet- és metaadat-sáv nélkül (K8a)."""
    lista = cel.with_name(cel.stem + ".lista.txt")
    lista.write_text("".join(f"file '{p}'\n" for p in (nz["nyito"], fo_mp4, nz["zaro"])), encoding="utf-8")
    n, f, z = nz["nyito_s"], _hossz(fo_mp4), nz["zaro_s"]
    fmt = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"
    szuro = (f"[1:a]atrim=0:{n},asetpts=PTS-STARTPTS,volume={ZENE_HANGERO},"
             f"afade=t=out:st={n - NYITO_HALKUL_S}:d={NYITO_HALKUL_S},{fmt},apad,atrim=0:{n}[a0];"
             f"[2:a]{fmt},apad,atrim=0:{f}[a1];"
             f"[3:a]atrim=0:{z},asetpts=PTS-STARTPTS,volume={ZENE_HANGERO},"
             f"afade=t=out:st={z - ZARO_HALKUL_S}:d={ZARO_HALKUL_S},{fmt},apad,atrim=0:{z}[a2];"
             "[a0][a1][a2]concat=n=3:v=0:a=1[a]")
    try:
        with open(log_ut, "a", encoding="utf-8") as log:
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lista),
                            "-i", str(INTRO), "-i", str(wav), "-i", str(OUTRO), "-filter_complex", szuro,
                            "-map", "0:v:0", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                            "-pix_fmt", "yuv420p", "-g", "60", "-keyint_min", "60", "-sc_threshold", "0", "-vf", "setsar=1",
                            "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv", "-c:a", "aac", "-b:a", "160k",
                            "-map_metadata", "-1", "-map_chapters", "-1", "-sn", "-dn", "-movflags", "+faststart",
                            *(["-threads", str(threads)] if threads else []),
                            str(cel)], check=True, stdout=log, stderr=subprocess.STDOUT)
    finally:
        lista.unlink(missing_ok=True)


def nyugta(nz: dict, targy: str, cim: str) -> dict:
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()  # noqa: E731
    return {"tantargy": targy, "cim": cim, "nyito_s": round(nz["nyito_s"], 3), "zaro_s": round(nz["zaro_s"], 3),
            "intro_sha256": sha(INTRO), "outro_sha256": sha(OUTRO), "hangero": ZENE_HANGERO}
