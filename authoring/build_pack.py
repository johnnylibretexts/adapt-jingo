"""Build a content pack with embedded phonetics records.

Run on the Mac with the johnny-lingo-v2 venv (which has jingo_engine[g2p]):
  /Users/johnnyrobot/code/johnny-lingo-v2/.venv/bin/python \\
      -c "import sys; sys.path.insert(0, 'engine/src')" \\
      service/scripts/build_pack.py --language es --out service/packs/spanish-1.json

G2P (phonemizer + espeakng-loader) runs here ONLY. The box never runs this script.

Dev/demo content only. No clinical validity, channel-independent thresholds, or
human-label validation is claimed for these packs.
"""
import argparse
import json
from pathlib import Path

from jingo_engine import DEFAULT_VOCAB_PATH
from jingo_engine.contract import get_g2p, phonetics_for


# ---- v1 content: Spanish Unit 1 + French Unit 1 (one unit each) -------------
# Units 2-6 per language are follow-on authoring (same structure, same script).
#
# Grading policy (per-question-row, spec-faithful):
#   * es-u1-l1-e1 ("ala") and fr-u1-l1-e1 ("pâte") are graded 'score' so the
#     provisional-banner + score path + honesty guardrail (spec line 126) is
#     exercised end-to-end. The exam section references these drills by
#     exercise_id + points ONLY (Task 10's command reads grading from the
#     drill row and ignores any exam-section grading key, so we omit it).
#   * All other pronunciation drills are 'completion' (the default credit).
SPANISH = {
    "manifest": {"course_title": "Spanish 1 — Sonidos y palabras", "language": "es", "version": "1.0.0"},
    "course_code": "SPAN-1",
    "units": [{
        "id": "es-u1", "title": "Sonidos y saludos", "order": 1,
        "lessons": [
            {"id": "es-u1-l1", "title": "Las cinco vocales", "order": 1, "drills": [
                {"id": "es-u1-l1-e1", "type": "pronunciation", "prompt": "Escucha y repite: /a/ — «ala»", "target_text": "ala", "grading": "score"},
                {"id": "es-u1-l1-e2", "type": "pronunciation", "prompt": "/e/ — «eco»", "target_text": "eco", "grading": "completion"},
                {"id": "es-u1-l1-e3", "type": "pronunciation", "prompt": "/i/ — «iglú»", "target_text": "iglú", "grading": "completion"},
                {"id": "es-u1-l1-e4", "type": "pronunciation", "prompt": "/o/ — «oso»", "target_text": "oso", "grading": "completion"},
                {"id": "es-u1-l1-e5", "type": "pronunciation", "prompt": "/u/ — «uva»", "target_text": "uva", "grading": "completion"},
                {"id": "es-u1-l1-q1", "type": "qti-mc", "prompt": "¿Cómo se dice «hello»?",
                 "qti_spec": {"type": "multiple_choice", "prompt": "¿Cómo se dice «hello»?",
                               "choices": [["hola", True], ["adiós", False], ["gracias", False], ["perdón", False]]}},
            ]},
            {"id": "es-u1-l2", "title": "/r/ y /ɾ/", "order": 2, "drills": [
                {"id": "es-u1-l2-e1", "type": "pronunciation", "prompt": "Repite: «perro» (rr vibrante)", "target_text": "perro", "grading": "completion"},
                {"id": "es-u1-l2-e2", "type": "pronunciation", "prompt": "Repite: «pero» (r simple)", "target_text": "pero", "grading": "completion"},
                {"id": "es-u1-l2-q1", "type": "qti-mc", "prompt": "¿Cuánto es 3 + 2?",
                 "qti_spec": {"type": "multiple_choice", "prompt": "¿Cuánto es 3 + 2?",
                               "choices": [["5", True], ["4", False], ["6", False]]}},
            ]},
        ],
        "exam": {"title": "Examen Unidad 1", "questions": [
            {"exercise_id": "es-u1-l1-e1", "points": 5},
            {"exercise_id": "es-u1-l1-q1", "points": 3},
        ]},
    }],
}

FRENCH = {
    "manifest": {"course_title": "French 1 — Sons et mots", "language": "fr", "version": "1.0.0"},
    "course_code": "FREN-1",
    "units": [{
        "id": "fr-u1", "title": "Sons et salutations", "order": 1,
        "lessons": [
            {"id": "fr-u1-l1", "title": "Voyelles", "order": 1, "drills": [
                {"id": "fr-u1-l1-e1", "type": "pronunciation", "prompt": "Répétez : /a/ — «pâte»", "target_text": "pâte", "grading": "score"},
                {"id": "fr-u1-l1-e2", "type": "pronunciation", "prompt": "/e/ — «été»", "target_text": "été", "grading": "completion"},
                {"id": "fr-u1-l1-e3", "type": "pronunciation", "prompt": "/i/ — «midi»", "target_text": "midi", "grading": "completion"},
                {"id": "fr-u1-l1-e4", "type": "pronunciation", "prompt": "/o/ — «mot»", "target_text": "mot", "grading": "completion"},
                {"id": "fr-u1-l1-e5", "type": "pronunciation", "prompt": "/u/ — «où»", "target_text": "où", "grading": "completion"},
                {"id": "fr-u1-l1-e6", "type": "pronunciation", "prompt": "/y/ — «lune»", "target_text": "lune", "grading": "completion"},
                {"id": "fr-u1-l1-q1", "type": "qti-mc", "prompt": "Comment dit-on «hello» ?",
                 "qti_spec": {"type": "multiple_choice", "prompt": "Comment dit-on «hello» ?",
                               "choices": [["bonjour", True], ["au revoir", False], ["merci", False]]}},
            ]},
            {"id": "fr-u1-l2", "title": "Le son /y/ vs /u/", "order": 2, "drills": [
                {"id": "fr-u1-l2-e1", "type": "pronunciation", "prompt": "Répétez : «tu» (/y/)", "target_text": "tu", "grading": "completion"},
                {"id": "fr-u1-l2-e2", "type": "pronunciation", "prompt": "Répétez : «tout» (/u/)", "target_text": "tout", "grading": "completion"},
            ]},
        ],
        "exam": {"title": "Examen Unité 1", "questions": [
            {"exercise_id": "fr-u1-l1-e1", "points": 5},
            {"exercise_id": "fr-u1-l1-q1", "points": 3},
        ]},
    }],
}

PACKS = {"es": SPANISH, "fr": FRENCH}


def build_record(text: str, language: str) -> dict:
    g2p = get_g2p()
    rec = phonetics_for(text, language, g2p, str(DEFAULT_VOCAB_PATH))
    # Drop per-entry keys the runtime provider doesn't need (keep the engine contract)
    return {
        "lang": rec.get("lang", language),
        "phones": rec["phones"],
        "ids": rec["ids"],
        "words": rec.get("words", []),
        "coverage": rec.get("coverage", 1.0),
        "unknown": rec.get("unknown", []),
        "espeak_voice": rec.get("espeak_voice"),
    }


def build_pack(language: str, out_path: str) -> None:
    pack = json.loads(json.dumps(PACKS[language]))  # deep copy
    for unit in pack["units"]:
        for lesson in unit["lessons"]:
            for drill in lesson["drills"]:
                if drill["type"] == "pronunciation":
                    rec = build_record(drill["target_text"], language)
                    if rec["coverage"] < 1.0:
                        raise SystemExit(
                            f"coverage < 1.0 for {drill['id']} ({drill['target_text']!r}): "
                            f"{rec['coverage']} unknown={rec['unknown']}"
                        )
                    drill["phonetics_record"] = rec
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(pack, ensure_ascii=False, indent=2))
    print(f"wrote {out_path} ({language})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--language", choices=["es", "fr"], required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    build_pack(args.language, args.out)