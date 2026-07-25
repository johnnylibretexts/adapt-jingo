#!/usr/bin/env python3
"""Generate jingo phonetics records for a list of words — the reusable authoring
primitive behind content-based pronunciation drills.

For each word it runs G2P (phonemizer + espeak via jingo_engine) and writes one
`{out}/{lang}/{exercise_id}.json` record in the exact shape the scorer's
JsonPhoneticsProvider reads. Words whose G2P coverage is < 1.0 are skipped and
reported (they can't be scored reliably).

G2P runs on the Mac only (the box has no espeak). Copy the resulting {lang}/
records into the scorer's JINGO_RECORDS_DIR (e.g. /opt/libretexts/jingo/records).

Input formats (one entry per line):
    word                     # id auto-derived: es-w-<ascii-slug>
    exercise_id<TAB>word     # explicit id

Usage (with the johnny-lingo-v2 venv that has jingo_engine[g2p]):
    .venv/bin/python gen_word_records.py --words words.txt --out ./out --lang es
"""
import argparse
import json
import os
import re
import sys
import unicodedata

# jingo_engine lives in the johnny-lingo-v2 engine source tree.
ENGINE_SRC = os.environ.get("JINGO_ENGINE_SRC",
                            "/Users/johnnyrobot/code/johnny-lingo-v2/engine/src")
sys.path.insert(0, ENGINE_SRC)
from jingo_engine import DEFAULT_VOCAB_PATH            # noqa: E402
from jingo_engine.contract import get_g2p, phonetics_for  # noqa: E402


def slug_id(word, lang):
    ascii_ = unicodedata.normalize("NFKD", word).encode("ascii", "ignore").decode()
    return f"{lang}-w-" + re.sub(r"[^a-z]", "", ascii_.lower())


# A displayable word token: starts with a letter, keeps internal apostrophes/
# hyphens (J'aime, belle-sœur, week-end), drops bare punctuation ("?", ",").
_WORD_TOKEN_RE = re.compile(r"[^\W\d_][\w'’-]*", re.UNICODE)


def _attach_word_text(text, spans):
    """Label each espeak word-span with its source token so the UI can colour
    real words. espeak only ever MERGES tokens across elisions (e.g. "Qu'est-ce
    que" -> one span), never splits one, so equal counts make a 1:1 zip safe. On
    a mismatch we leave text off and the UI falls back to the flat per-sound view."""
    tokens = _WORD_TOKEN_RE.findall(text or "")
    if spans and len(tokens) == len(spans):
        for span, tok in zip(spans, tokens):
            span["text"] = tok
    return spans


def record(word, lang, g2p):
    rec = phonetics_for(word, lang, g2p, str(DEFAULT_VOCAB_PATH))
    if rec.get("coverage", 0) < 1.0:
        return None, rec.get("unknown")
    words = _attach_word_text(word, rec.get("words", []))
    return {
        "lang": rec.get("lang", lang), "phones": rec["phones"], "ids": rec["ids"],
        "words": words, "coverage": rec.get("coverage", 1.0),
        "unknown": rec.get("unknown", []), "espeak_voice": rec.get("espeak_voice"),
    }, None


def parse_line(line, lang):
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if "\t" in line:
        ex_id, word = line.split("\t", 1)
        return ex_id.strip(), word.strip()
    return slug_id(line, lang), line


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--words", required=True, help="word list file")
    ap.add_argument("--out", required=True, help="records output dir")
    ap.add_argument("--lang", default="es")
    args = ap.parse_args()

    out_dir = os.path.join(args.out, args.lang)
    os.makedirs(out_dir, exist_ok=True)
    g2p = get_g2p()
    written = skipped = 0
    for raw in open(args.words, encoding="utf-8"):
        parsed = parse_line(raw, args.lang)
        if not parsed:
            continue
        ex_id, word = parsed
        rec, unknown = record(word, args.lang, g2p)
        if rec is None:
            print(f"  skip (coverage<1): {word!r} unknown={unknown}")
            skipped += 1
            continue
        with open(os.path.join(out_dir, ex_id + ".json"), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
        written += 1
    print(f"wrote {written} records to {out_dir}  (skipped {skipped})")


if __name__ == "__main__":
    main()
