"""Render (Manim a saját conda-környezetében, a manim.sh-n át), összeomlás-kivonat, összefésülés,
ffprobe (K8a), a végleges hang Opus-mentése és a nyugta."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path

GYOKER = Path(__file__).resolve().parent.parent
MANIM_SH = GYOKER / "manim.sh"
FPS = 30
MINOSEG = {"480p": ("-ql", "480p30"), "1080p": ("-qh", "1080p30")}


def jelenet_osztaly(kod: Path) -> str:
    """A jelenetek.py egyetlen VideoJelenet-osztálya."""
    nevek = re.findall(r"^class\s+(\w+)\(\s*VideoJelenet\s*\)", kod.read_text(encoding="utf-8"), re.M)
    if len(nevek) != 1:
        raise ValueError(f"a {kod.name}-ban pontosan egy VideoJelenet-osztály kell, van: {nevek or 'nincs'}")
    return nevek[0]


def render(mappa: Path, media: Path, minoseg: str, log_ut: Path, idokorlat_s: float) -> dict:
    """Manim-render; visszaad: {kod (0 vagy 3), mp4, s, animacio, gyorsitotar, kivonat (összeomlásnál)}."""
    kapcsolo, almappa = MINOSEG[minoseg]
    osztaly = jelenet_osztaly(mappa / "jelenetek.py")
    env = {k: v for k, v in os.environ.items() if k not in ("CSAK", "IG")}
    env["VIDEO_MAPPA"] = str(mappa)
    env["COLUMNS"] = "200"                   # a rich-napló ne tördeljen (a kivonat soronként keres)
    cmd = [str(MANIM_SH), kapcsolo, "--fps", str(FPS), "--save_sections", "--progress_bar", "none",
           "--media_dir", str(media), "jelenetek.py", osztaly]
    naplo = mappa / "render_naplo.json"
    naplo.unlink(missing_ok=True)            # ami a render után itt van, az ennek a futásnak a naplója
    with open(log_ut, "a", encoding="utf-8") as log:
        log.write(f"\n=== render {minoseg}: {' '.join(cmd)}\n")
        log.flush()
        eleje = log.tell()
        t0 = time.monotonic()
        try:
            p = subprocess.run(cmd, cwd=mappa, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=idokorlat_s)
            kod = p.returncode
        except subprocess.TimeoutExpired:
            kod = "idokorlat"
        s = time.monotonic() - t0
    with open(log_ut, encoding="utf-8", errors="replace") as f:
        f.seek(eleje)
        szoveg = f.read()
    mp4 = media / "videos" / "jelenetek" / almappa / f"{osztaly}.mp4"
    eredmeny = {"s": round(s, 1), "mp4": mp4, "osztaly": osztaly,
                "animacio": len(re.findall(r"Animation \d+ : ", szoveg)),
                "gyorsitotar": len(re.findall(r"Animation \d+ : Using cached", szoveg))}
    if kod == "idokorlat":
        return {**eredmeny, "kod": 2, "kivonat": [f"a render nem fért az időkorlátba ({idokorlat_s:.0f} s)"]}
    if kod != 0 or not mp4.exists() or not naplo.exists():
        return {**eredmeny, "kod": 3, "kivonat": kivonat(szoveg, kod)}
    return {**eredmeny, "kod": 0}


def allokep(mappa: Path, media: Path, lepes: str, log_ut: Path, idokorlat_s: float) -> Path:
    """A lépés végállapotának 1080p-s állóképe (IG=<lépés>, -qh -s); a teljes render naplóját nem írja felül."""
    osztaly = jelenet_osztaly(mappa / "jelenetek.py")
    naplo, mentes = mappa / "render_naplo.json", mappa / "render_naplo.json.kivagat"
    env = {k: v for k, v in os.environ.items() if k != "CSAK"}
    env.update(VIDEO_MAPPA=str(mappa), IG=lepes, COLUMNS="200")
    kepek = media / "images" / "jelenetek"
    regi = {p: p.stat().st_mtime for p in kepek.glob("*.png")} if kepek.exists() else {}
    if naplo.exists():
        naplo.replace(mentes)
    try:
        with open(log_ut, "a", encoding="utf-8") as log:
            log.write(f"\n=== kivágat {lepes}\n")
            log.flush()
            subprocess.run([str(MANIM_SH), "-qh", "--fps", str(FPS), "-s", "--progress_bar", "none", "--media_dir",
                            str(media), "jelenetek.py", osztaly], cwd=mappa, env=env, stdout=log,
                           stderr=subprocess.STDOUT, timeout=idokorlat_s, check=True)
    finally:
        if mentes.exists():
            mentes.replace(naplo)
    uj = [p for p in kepek.glob("*.png") if regi.get(p) != p.stat().st_mtime]
    if not uj:
        raise FileNotFoundError("a Manim nem mentett állóképet")
    return max(uj, key=lambda p: p.stat().st_mtime)


def kivonat(szoveg: str, kod) -> list[str]:
    """Render-összeomlás ≤ 15 sorban: a kivétel, a jelenetek.py/videotar utolsó kerete, LaTeX-nél a hibás sor."""
    sorok = [re.sub(r"[│╭╮╰╯─]+", " ", s).strip() for s in szoveg.splitlines()]
    sorok = [s for s in sorok if s]
    ki = [f"render-összeomlás (kilépési kód {kod})"]
    keretek = [s for s in sorok if re.search(r"(jelenetek\.py|videotar/\w+\.py)[:\"]?,? ?(line )?\d+", s)]
    if keretek:
        hol = re.search(r"(jelenetek\.py|videotar/\w+\.py)\S*?[:,]? ?(line )?(\d+)(,? in \w+)?", keretek[-1])
        ki.append("utolsó keret: " + (hol.group(0) if hol else keretek[-1][:200]))
        i = len(sorok) - 1 - sorok[::-1].index(keretek[-1])
        jel = [s for s in sorok[i + 1:i + 10] if s.startswith("❱")]     # a rich-traceback a hibás sort így jelöli
        ki += ["  " + (jel[0] if jel else sorok[i + 1] if i + 1 < len(sorok) else "")[:200]]
    tex = [i for i, s in enumerate(sorok) if s.startswith("! ")]
    if tex:
        ki.append("LaTeX: " + sorok[tex[0]][:200])
        ki += ["  " + s[:200] for s in sorok[tex[0] + 1:tex[0] + 3]]
    hibak = [s for s in sorok if re.match(r"^(\w+\.)*\w*(Error|Exception|Hiba)\b:?", s)]
    if hibak:
        ki.append("kivétel: " + hibak[-1][:300])
    elif not tex:
        ki += [s[:200] for s in sorok[-6:]]
    return ki[:15]


def sha256(ut: Path) -> str:
    h = hashlib.sha256()
    with open(ut, "rb") as f:
        for blokk in iter(lambda: f.read(1 << 20), b""):
            h.update(blokk)
    return h.hexdigest()


def ffprobe_adat(mp4: Path) -> dict:
    """A nyugtához: hossz, felbontás, fps, kodekek (a K8a-t a kapu.k8a méri)."""
    p = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(mp4)],
                       capture_output=True, text=True, check=True)
    d = json.loads(p.stdout)
    video = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), {})
    return {"hossz_s": round(float(d.get("format", {}).get("duration", 0)), 3),
            "felbontas": [video.get("width"), video.get("height")], "fps": video.get("r_frame_rate"),
            "kodek": [s.get("codec_name") for s in d.get("streams", [])]}


def opus_mentes(wav: Path, cel: Path, log_ut: Path) -> None:
    """A végleges hang kis mentése (48 kbit/s Opus, 5 percre kb. 2 MB): lemezhibánál a videó ebből és a
    forrásból az eredeti időzítéssel újraépül."""
    tmp = cel.with_name(cel.stem + ".tmp.opus")
    with open(log_ut, "a", encoding="utf-8") as log:
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(wav), "-c:a", "libopus", "-b:a", "48k",
                        "-map_metadata", "-1", str(tmp)], check=True, stdout=log, stderr=subprocess.STDOUT)
    tmp.replace(cel)
