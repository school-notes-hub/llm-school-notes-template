"""Build selection and silent capture, with measured figure eligibility."""

import subprocess
from pathlib import Path
from .adatok import ROOT, TEMPLATE, read, write
from .kitolt import validate, fill, contract
from .jeloltek import candidates, listing
from .kapu_h import gate
from .lapok_h import contacts, review


def build_path(value):
    path = Path(value).resolve()
    return path if (path / "payload.json").exists() else path / "build"


def surface_payload(build):
    payload = read(build / "payload.json")
    return {
        **payload,
        "pages": [
            {**p, "html": (build / "site" / p["route"] / "index.html").read_text()}
            for p in payload["pages"]
        ],
    }


def selection_files(local, build, out, subject, lesson, script_path):
    choices, rejected = candidate_files(local, build, out)
    (out / "jeloltek.txt").write_text(listing(choices, rejected))
    choice = next(
        (
            c
            for c in choices
            if c["tantargy"]["route"] == subject
            and c["lecke"]["route"] in (lesson, subject + "/" + lesson)
        ),
        None,
    )
    if choice is None:
        raise ValueError(
            "a választott tantárgy–lecke nincs a jelöltlistában; jeloltek.txt"
        )
    original, actors = read(script_path), read(ROOT / "szereplok.json")
    validate(original, actors)
    script, actors = fill(
        original, choice, {"ora-bizonytalan"} if choice["opcionalis"] else set()
    )
    commit = read(build / "build.json")["commit"]
    write_selection(out, local, build, subject, choice, script, actors, commit)
    return script, commit


def write_selection(out, local, build, subject, choice, script, actors, commit):
    write(out / "forgatokonyv-kitoltott.json", script)
    write(out / "szereplok.json", actors)
    write(
        out / "valasztas.json",
        {
            "tanulo": local.name,
            "tantargy": subject,
            "lecke": choice["lecke"]["route"],
            "build": str(build),
            "commit": commit,
        },
    )
    write(
        out / "felvetel.json",
        {
            "build": str(build),
            "out": str(out),
            "script": script,
            "actors": actors,
            "browserPath": str(local.cfg.browser),
            "commit": commit,
        },
    )


def preview(local, build, out, subject, lesson, script_path=ROOT / "forgatokonyv.json"):
    if not subject or not lesson:
        raise ValueError("--tantargy és --lecke szükséges")
    script, commit = selection_files(local, build, out, subject, lesson, script_path)
    subprocess.run(
        [
            "node",
            str(TEMPLATE / "packages/study-site/capture-usage.mjs"),
            str(out / "felvetel.json"),
        ],
        check=True,
        cwd=out,
    )
    measurements = read(out / "dobozok.json")
    script = read(out / "forgatokonyv-kitoltott.json")
    report = gate(
        script,
        measurements,
        payload=surface_payload(build),
        commit=commit,
        expected_commit=local.git().out("rev-parse", "HEAD").strip(),
        preview=True,
        image_dir=out,
    )
    for row in contract():
        report["leletek"].append(
            {
                "lepes": "",
                "kod": "H10",
                "szereplo": "",
                "uzenet": "sablonszöveg megváltozott: " + row["text"],
            }
        )
        report.update(kep_zold=False, zold=False, kiadhato=False)
    write(out / "kapu.json", report)
    contacts(out, script, measurements)
    review(out)
    return report


def candidate_files(local, build, out):
    config = {
        "build": str(build),
        "out": str(out),
        "browserPath": str(local.cfg.browser),
        "repo": str(local.repo),
    }
    write(out / "abra-felvetel.json", config)
    subprocess.run(
        [
            "node",
            str(TEMPLATE / "packages/study-site/usage-candidates.mjs"),
            str(out / "abra-felvetel.json"),
        ],
        check=True,
    )
    measured = read(out / "abra-meres.json")
    figures = measured["figures"]
    payload = read(build / "payload.json")
    classroom = read(out / "ora-forrasok.json")
    for page in payload["pages"]:
        page["usageClassroomParagraphs"] = classroom.get(page["route"], [])
        if page.get("navigation") == "home":
            page["usageThemeLabel"] = measured["surface"].get("temavalaszto", {}).get("text", "")
    return candidates(payload, figures)
