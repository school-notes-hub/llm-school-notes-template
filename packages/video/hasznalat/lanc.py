"""Usage-video CLI: validate input, select a work folder, dispatch and classify errors."""

import argparse
import fcntl
import os
import re
import shutil
import time
import traceback
from pathlib import Path
from jsonschema.exceptions import ValidationError
from lanc.hangok import Megallt
from school_notes2.local.common import load, today
from school_notes2.state.errors import SnError
from .adatok import read, write
from .jeloltek import listing
from .elonezet import build_path, candidate_files, preview
from .gyartas import produce
from .vegleges import finalize


def arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tanulo")
    parser.add_argument("build", nargs="?")
    mode = parser.add_mutually_exclusive_group()
    for name in ("jeloltek", "elonezet"):
        mode.add_argument("--" + name, metavar="BUILD")
    for name in ("vegleges", "meres", "takarit"):
        mode.add_argument("--" + name, action="store_true")
    parser.add_argument("--tantargy")
    parser.add_argument("--lecke")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--out", type=Path)
    return parser.parse_args(argv)


def validate_arguments(args):
    if (args.elonezet or args.build) and (not args.tantargy or not args.lecke):
        raise ValueError("--tantargy és --lecke szükséges")
    if os.environ.get("VIDEO_CSONK") == "1" and not args.out:
        raise ValueError("VIDEO_CSONK=1 csak külön --out mappával használható")


def output_folder(args, local):
    folder = local.repo / ".school-notes/out/hasznalat"
    previous = sorted(
        p
        for p in folder.glob("*")
        if re.fullmatch(r"\d{8}", p.name) and (p / "valasztas.json").is_file()
    )
    if args.out:
        out = args.out.resolve()
    elif not args.elonezet and not args.jeloltek and previous:
        out = previous[-1]
    else:
        out = folder / today().replace("-", "")
    out.mkdir(parents=True, exist_ok=True)
    if not args.out and args.elonezet and not (out / "kepek").exists():
        cache = (
            Path.home()
            / ".cache/school-notes/hasznalat"
            / local.name
            / out.name
            / "kepek"
        )
        cache.mkdir(parents=True, exist_ok=True)
        (out / "kepek").symlink_to(cache, target_is_directory=True)
    return out


def dispatch(args, local, out):
    if args.jeloltek:
        choices, rejected = candidate_files(local, build_path(args.jeloltek), out)
        text = listing(choices, rejected)
        (out / "jeloltek.txt").write_text(text)
        print("\n".join(text.splitlines()[:10]))
        return 0 if choices else 2
    if args.meres:
        print((out / "meres.json").read_text())
        return 0
    if args.takarit:
        if not (out / "nyugta.json").exists():
            raise ValueError("csak végleges nyugta után takarítható")
        shutil.rmtree(out / "media", ignore_errors=True)
        return 0
    if args.vegleges:
        return finalize(local, out)
    if args.elonezet:
        return (
            0
            if preview(
                local, build_path(args.elonezet), out, args.tantargy, args.lecke
            )["kep_zold"]
            else 1
        )
    if args.build:
        selected = read(out / "valasztas.json")
        if (
            selected["build"] != str(build_path(args.build))
            or selected["tantargy"] != args.tantargy
            or selected["lecke"].split("/")[-1] != args.lecke.split("/")[-1]
        ):
            raise ValueError("a választás eltér az előnézettől")
        return produce(local, out)
    raise ValueError("válassz műveletet")


def execute(args):
    started = time.monotonic()
    validate_arguments(args)
    local = load(args.tanulo, args.config)
    out = output_folder(args, local)
    with (out / ".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        code = dispatch(args, local, out)
    if not args.meres:
        write(
            out / "meres.json",
            {
                "gepi_s": round(time.monotonic() - started, 3),
                "kod": code,
                "llm_token": 0,
                "mod": "elonezet" if args.elonezet else "gyartas",
            },
        )
    print(f"Használat: kód {code}; {out}; részletek: kapu.json, tabla.txt, lapok/")
    return code


def main(argv=None):
    args = arguments(argv)
    try:
        return execute(args)
    except (ValueError, OSError, ValidationError, SnError, Megallt) as error:
        print("MEGÁLLT: " + str(error))
        return 2
    except Exception as error:
        if args.out and args.out.exists():
            with (args.out / "video.log").open("a") as log:
                traceback.print_exc(file=log)
        print("ESZKÖZHIBA: " + type(error).__name__ + ": " + str(error))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
