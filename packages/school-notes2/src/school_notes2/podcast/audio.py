"""From the scenes' speech to the published MP3.

1. **Voice track** as in the approved samples (`minta3.py`): 0.3 s silence, the scenes with
   0.6 s between them, 1.0 s at the end; two-pass `loudnorm` (I −16, TP −1.5, LRA 11, linear),
   kept lossless (WAV) instead of the samples' 64 kbit/s intermediate MP3.
2. **Mix** exactly as the owner approved it on 2026-10-08 (`kevero.sh`, „tökéletes”): only the
   owner's Suno track, at both ends – its first 20 s (full for 8 s, down to 50 % by 11.5 s, to
   5 % by 12 s when the voice starts at 12 s, out by 16 s) and its last 20 s (from 6 s before the
   voice ends, 10 → 18 %, full 1.5 s after the last word, the track's own ending closes the
   episode); the voice loudness-normalised alone, the music at a fixed gain. `MIX_GRAPH` is the
   script's filter graph, unchanged to the parameter.
3. **Encoding** (the only part that differs from `kevero.sh`, which wrote 128 kbit/s stereo):
   64 kbit/s CBR **mono** MP3, 48 kHz. The speech is mono (the model gives 24 kHz mono, the mixer
   only copies it to both channels); only the music at the two ends is stereo. 64 kbit/s mono is
   0.48 MB a minute: a 3–4 minute episode with the 26 s of music is 1.6–2.2 MB. Bit-exact flags,
   input metadata dropped, ID3v2.3 with only `title` (the episode) and `album` (the show):
   the same input gives the same bytes."""

import json
import re
import shutil
import subprocess
from pathlib import Path

from ..state.errors import Prerequisite
from .speech import RATE

LEAD, GAP_SCENE, TAIL = 0.3, 0.6, 1.0
VOICE_START = 12.0               # the mix delays the voice by 12 s (adelay=12000)
END_MUSIC = 26.0                 # the episode is the voice track + 26 s (20 s outro − 6 s overlap + 12 s)
BITRATE = "64k"
CHANNELS = "1"

MIX_GRAPH = (
    "[0:a]aresample=48000,atrim=0:20,asetpts=PTS-STARTPTS,volume=0.7,"
    "volume='if(lt(t,8),1,if(lt(t,11.5),1-0.5*(t-8)/3.5,if(lt(t,12),0.5-0.45*(t-11.5)/0.5,"
    "if(lt(t,16),0.05*(1-(t-12)/4),0))))':eval=frame[i];"
    "[1:a]aresample=48000,loudnorm=I=-16:TP=-2:LRA=11,aresample=48000,aformat=channel_layouts=stereo,"
    "adelay=12000|12000[v];"
    "[2:a]aresample=48000,asetpts=PTS-STARTPTS,volume=0.7,"
    "volume='if(lt(t,6),0.10+0.08*t/6,if(lt(t,7.5),0.18+0.82*(t-6)/1.5,1))':eval=frame,adelay=$OS|$OS[o];"
    "[i][v][o]amix=inputs=3:normalize=0,alimiter=limit=0.89[a]")

EXACT = ["-fflags", "+bitexact", "-flags:a", "+bitexact", "-map_metadata", "-1"]


def tools() -> None:
    for name in ("ffmpeg", "ffprobe"):
        if shutil.which(name) is None:
            raise Prerequisite(f"{name} hiányzik", todo="sudo apt install ffmpeg")


def silence(seconds: float) -> bytes:
    return b"\0\0" * int(RATE * seconds)


def voice_track(scenes: list[bytes]) -> tuple[bytes, list[float]]:
    """(the joined PCM, each scene's start in seconds within it)."""
    parts, starts, pos = [silence(LEAD)], [], LEAD
    for n, pcm in enumerate(scenes):
        if n:
            parts.append(silence(GAP_SCENE))
            pos += GAP_SCENE
        starts.append(round(pos, 3))
        parts.append(pcm)
        pos += len(pcm) / 2 / RATE
    parts.append(silence(TAIL))
    return b"".join(parts), starts


def _run(args: list[str]) -> subprocess.CompletedProcess:
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg: " + " ".join(proc.stderr.strip().splitlines()[-3:])[:400])
    return proc


def normalized(pcm: Path, wav: Path) -> None:
    """Two-pass loudnorm of the raw voice into a 24 kHz mono WAV."""
    raw = ["-f", "s16le", "-ar", str(RATE), "-ac", "1", "-i", str(pcm)]
    first = _run([*raw, "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"])
    m = json.loads(first.stderr[first.stderr.rindex("{"):first.stderr.rindex("}") + 1])
    af = (f"loudnorm=I=-16:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
          f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:"
          "linear=true")
    _run(["-y", *raw, "-af", af, "-ar", str(RATE), "-ac", "1", "-c:a", "pcm_s16le", *EXACT, str(wav)])


def duration(path: Path) -> float:
    proc = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                           str(path)], capture_output=True, text=True, check=True)
    return float(proc.stdout.strip())


def mix_graph(voice: Path) -> str:
    """The filter graph with `$OS` as `kevero.sh` computes it: int((12 + D − 6) × 1000), D the
    voice file's duration as ffprobe prints it."""
    proc = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                           str(voice)], capture_output=True, text=True, check=True)
    offset = int((12 + float(proc.stdout.strip()) - 6) * 1000)
    return MIX_GRAPH.replace("$OS", str(offset))


def mix(voice: Path, music: Path, out: Path, *, title: str, album: str) -> None:
    _run(["-y", "-v", "error", "-i", str(music), "-i", str(voice), "-sseof", "-20", "-i", str(music),
          "-filter_complex", mix_graph(voice), "-map", "[a]",
          "-c:a", "libmp3lame", "-b:a", BITRATE, "-ac", CHANNELS, "-bitexact", *EXACT,
          "-id3v2_version", "3", "-metadata", f"title={title}", "-metadata", f"album={album}", str(out)])


def speech_mp3(pcm: bytes) -> bytes:
    """A scene's raw speech as a 64 kbit/s mono MP3 (bit-exact) for the transcription: the size the
    measured Whisper run sent (a 3.6 minute episode, 1.7 MB) instead of a 10 MB WAV."""
    import tempfile
    tools()
    with tempfile.TemporaryDirectory(prefix="sn-podcast-stt-") as tmp:
        raw, out = Path(tmp) / "scene.pcm", Path(tmp) / "scene.mp3"
        raw.write_bytes(pcm)
        _run(["-y", "-f", "s16le", "-ar", str(RATE), "-ac", "1", "-i", str(raw), "-c:a", "libmp3lame",
              "-b:a", BITRATE, "-ac", "1", *EXACT, str(out)])
        return out.read_bytes()


def ffmpeg_version() -> str:
    proc = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
    first = proc.stdout.splitlines()[0] if proc.stdout else ""
    found = re.match(r"ffmpeg version (\S+)", first)
    return found[1] if found else "unknown"


def episode(scenes: list[bytes], music: Path, work: Path, *, title: str,
            album: str) -> tuple[bytes, list[float], float]:
    """The published MP3's bytes, each scene's start in the final episode and its length (s)."""
    tools()
    if not music.is_file():
        raise Prerequisite(f"a zene nincs meg: {music}", todo="[podcast] music a config.toml-ban, vagy a fájl a helyére")
    pcm, starts = voice_track(scenes)
    (work / "voice.pcm").write_bytes(pcm)
    normalized(work / "voice.pcm", work / "voice.wav")
    mix(work / "voice.wav", music, work / "episode.mp3", title=title, album=album)
    out = work / "episode.mp3"
    return out.read_bytes(), [round(VOICE_START + s, 3) for s in starts], round(duration(out), 1)
