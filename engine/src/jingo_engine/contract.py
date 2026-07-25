"""SHARED PHONEME CONTRACT for Johnny Lingo phoneme acoustic scoring.

Single source of truth shared by Phase 1 (offline G2P content pipeline) and
Phase 2/3 (GOP scorer). Pin this so the producer and consumer cannot drift.

Acoustic model : facebook/wav2vec2-xlsr-53-espeak-cv-ft  (vocab.json, 392 tokens)
G2P engine     : phonemizer + espeakng-loader (espeak-ng 1.52) -- BUILD-TIME ONLY
                 (GPL; the bundled lib is used to generate IPA and is never shipped)

Canonical method: let espeak emit its OWN phone + word boundaries via a phone
Separator. This preserves French liaison (the liaison consonant stays attached
to its word) and avoids cross-word vowel merges, and every espeak phone is
already a member of the model's 392-symbol vocabulary (verified 100% coverage on
the es/fr content packs).

Runtime note: only ``load_vocab_set`` / ``map_to_vocab`` are needed at scoring
time (pure-stdlib + the model vocab). ``get_g2p`` imports phonemizer/espeak and
is build-time only -- never call it from the packaged app.
"""
from __future__ import annotations

import json
import os
import unicodedata
from functools import lru_cache

# ---- G2P settings: the content phonemizer MUST use these exact values ------
ESPEAK_LANG = {"es": "es-419", "fr": "fr-fr"}   # es-419 = Latin-American (seseo)
PHONE_SEP, WORD_SEP = " ", " | "
G2P_VERSION = "espeak-ng-1.52"


def get_g2p():
    """Return ``g2p(text, lang_code) -> list[list[str]]`` (words -> canonical
    phones). BUILD-TIME ONLY: requires phonemizer + espeakng_loader installed.

    Reuses a **persistent** ``EspeakBackend`` per language instead of the top-level
    ``phonemize()`` convenience call. ``phonemize()`` rebuilds the espeak backend on
    every invocation (~1.1 s/call -- it dominates bulk G2P; a 3000-clip calibration
    scan took ~1 h). Reusing the backend is ~100x faster and produces byte-identical
    output (verified on es/fr Common Voice sentences). ``g2p.batch(texts, lang)``
    phonemizes a whole list in one backend call for callers that can bulk it."""
    import espeakng_loader
    from phonemizer.backend import EspeakBackend
    from phonemizer.backend.espeak.wrapper import EspeakWrapper
    from phonemizer.separator import Separator

    os.environ.setdefault("ESPEAK_DATA_PATH", espeakng_loader.get_data_path())
    EspeakWrapper.set_library(espeakng_loader.get_library_path())
    sep = Separator(phone=PHONE_SEP, word=WORD_SEP, syllable="")
    backends: dict = {}

    def _backend(lang_code: str):
        backend = backends.get(lang_code)
        if backend is None:
            backend = EspeakBackend(
                lang_code, with_stress=False, preserve_punctuation=False,
                language_switch="remove-flags", words_mismatch="ignore",
            )
            backends[lang_code] = backend
        return backend

    def _split(out: str) -> list[list[str]]:
        words = []
        for w in out.split("|"):
            phones = [unicodedata.normalize("NFC", p) for p in w.strip().split() if p.strip()]
            if phones:
                words.append(phones)
        return words

    def g2p(text: str, lang_code: str) -> list[list[str]]:
        out = _backend(lang_code).phonemize([text], separator=sep, strip=True)[0]
        return _split(out)

    def g2p_batch(texts, lang_code: str) -> list[list[list[str]]]:
        outs = _backend(lang_code).phonemize(list(texts), separator=sep, strip=True)
        return [_split(o) for o in outs]

    g2p.batch = g2p_batch  # optional bulk API; per-call g2p already reuses the backend
    return g2p


@lru_cache(maxsize=4)
def load_vocab(vocab_path: str) -> tuple[dict, frozenset]:
    """Return (token->id mapping, set of phone tokens excluding <specials>)."""
    vocab = json.loads(open(vocab_path).read())
    vocab = {unicodedata.normalize("NFC", k): v for k, v in vocab.items()}
    phones = frozenset(t for t in vocab if not t.startswith("<"))
    return vocab, phones


def map_to_vocab(phones: list[str], vocab_path: str) -> dict:
    """Map espeak phones onto the model vocab. Returns mapped phones (with <unk>
    for any out-of-vocab symbol), their ids, and coverage (expected 1.0 for es/fr)."""
    vocab, phone_set = load_vocab(vocab_path)
    unk_id = vocab.get("<unk>", 3)
    mapped, ids, unknown = [], [], []
    for p in phones:
        p = unicodedata.normalize("NFC", p)
        if p in phone_set:
            mapped.append(p)
            ids.append(vocab[p])
        else:
            mapped.append("<unk>")
            ids.append(unk_id)
            unknown.append(p)
    cov = 1.0 - len(unknown) / max(1, len(phones))
    return {"phonemes": mapped, "ids": ids, "unknown": unknown, "coverage": round(cov, 3)}


def phonetics_for(text: str, lang: str, g2p, vocab_path: str) -> dict:
    """Build the canonical phonetics record Phase 1 stores per phrase.

    ``phones`` is the flat canonical phone sequence (the GOP target); ``words``
    carries per-word spans into that flat list for word<->phoneme UI mapping.
    """
    lang_code = ESPEAK_LANG[lang]
    words = g2p(text, lang_code)
    flat = [p for w in words for p in w]
    chk = map_to_vocab(flat, vocab_path)
    spans, cursor = [], 0
    for w in words:
        spans.append({"start": cursor, "len": len(w), "phones": w})
        cursor += len(w)
    return {
        "lang": lang,
        "espeak_voice": lang_code,
        "g2p": G2P_VERSION,
        "phones": flat,
        "ids": chk["ids"],
        "words": spans,
        "coverage": chk["coverage"],
        "unknown": chk["unknown"],
    }
