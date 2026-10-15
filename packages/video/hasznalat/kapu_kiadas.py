"""Sound/output gates and explicit review exceptions."""

import json
import subprocess
from pathlib import Path


def h6(audio, add):
    if audio is None or audio.get("k10") or not audio.get("hossz_s"):
        add("H6", "", "", "hiányzó hangellenőrzés vagy K10 hiba")


def h7(output, duration, add):
    if output is None or not Path(output).is_file():
        add("H7", "", "", "nincs végleges videó")
        return
    probe = json_probe(output)
    streams = probe["streams"]
    videos = [s for s in streams if s["codec_type"] == "video"]
    audios = [s for s in streams if s["codec_type"] == "audio"]
    valid = (
        len(streams) == 2
        and len(videos) == len(audios) == 1
        and videos[0]["width"] == 1920
        and videos[0]["height"] == 1080
        and videos[0]["r_frame_rate"] == "30/1"
        and duration is not None
        and abs(float(probe["format"]["duration"]) - duration) <= 1 / 30
        and Path(output).stat().st_size <= 40_000_000
    )
    if not valid:
        add("H7", "", "", "méret, hossz, sávok vagy 40 MB határ eltérése")


def json_probe(path):
    return json.loads(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            ]
        )
    )


def exceptions(report, record, key):
    """A vezérlő indokolt, pontos leletre és review-kulcsra kötött felülbírálata."""
    if record.get("key") != key:
        raise ValueError("a kapukivétel kulcsa elavult")
    for item in record.get("kivetelek", []):
        if item.get("kod") in {"H3", "H5", "H10"} or not item.get("indok", "").strip():
            raise ValueError("H3/H5/H10 nem bírálható felül; indok kötelező")
        found = next(
            (
                f
                for f in report["leletek"]
                if all(f[k] == item.get(k, "") for k in ("lepes", "kod", "szereplo"))
            ),
            None,
        )
        if found is None:
            raise ValueError("a felülbírált lelet nem létezik")
        found.update(felulbiralva=True, indok=item["indok"])
    report["kep_zold"] = not any(not f.get("felulbiralva") for f in report["leletek"])
    report["kiadhato"] = report["kep_zold"] and not report.get("nem_mert")
    report["zold"] = report["kep_zold"] and (
        report.get("elonezet") or not report.get("nem_mert")
    )
    return report
