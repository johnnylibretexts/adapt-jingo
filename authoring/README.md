# Authoring — G2P pack-building tools

These scripts build pronunciation-drill **content packs** (JSON) with embedded
phonetics records, for import into ADAPT via `php artisan
libretexts:import-language-pack`. They are **build-time, Mac-only tools** —
nothing here ships in the product or runs on the box.

## Why Mac-only

Generating a phonetics record requires grapheme-to-phoneme (G2P) conversion,
which depends on `phonemizer` + the `espeak-ng` backend (GPL-licensed).
Because the rest of `adapt-jingo` is MIT-licensed, the GPL G2P toolchain is
kept out of the shipped engine and out of the box entirely — it only ever
runs here, offline, by whoever is authoring a pack. The output (a JSON pack
of plain phoneme strings and integer ids) carries no GPL encumbrance.

Do not attempt to run these scripts on the Hostinger box; there is no G2P
toolchain there and there shouldn't be.

## Environment setup

Use the `johnny-lingo-v2` venv (or any Python 3.10+ venv), and install the
engine's optional G2P extra:

```bash
pip install 'jingo_engine[g2p]'
```

This pulls in `phonemizer` and `espeakng-loader` so `jingo_engine.contract`
can call out to `espeak-ng` under the hood. If you're working directly out
of a `johnny-lingo-v2` checkout instead of an installed package, the
equivalent manual setup is:

```bash
pip install phonemizer espeakng-loader
# then make sure engine/src is on PYTHONPATH, e.g.:
export PYTHONPATH="$HOME/code/johnny-lingo-v2/engine/src:$PYTHONPATH"
```

## Workflow: word list -> phonetics record -> pack

1. **Pick target words/phrases** for a lesson (e.g. Spanish Unit 1 vowels:
   `ala`, `eco`, `iglú`, `oso`, `uva`).
2. **Run G2P** on each string via `jingo_engine.contract.phonetics_for(text,
   language, g2p, vocab_path)`. This returns a record with:
   - `phones` — the phoneme sequence (IPA-ish symbols from the espeak-ng
     `_espeak-ng` phoneme set used by the `facebook/wav2vec2-xlsr-53-espeak-cv-ft`
     model)
   - `ids` — those phones mapped to integer vocabulary ids
   - `coverage` — fraction of phones that had a known id (should be `1.0`;
     both scripts here raise if it isn't, since an unknown phoneme means the
     drill can't be scored correctly)
   - `words`, `unknown`, `espeak_voice` — bookkeeping/debug fields
3. **Embed the record** on the drill (`drill["phonetics_record"] = rec`) and
   write the pack out as JSON. The runtime engine never re-runs G2P — it
   trusts whatever `phones`/`ids` are baked into the pack at authoring time.
4. **Import into ADAPT** as an admin/CLI step (not an instructor UI flow):
   ```bash
   php artisan libretexts:import-language-pack path/to/pack.json
   ```

### Scripts in this directory

- **`build_pack.py`** — builds a full pack from scratch for a language
  (`--language es|fr --out <path>`). Contains the in-line Spanish 1 / French
  1 Unit 1 course definitions (units, lessons, drills, exam) and runs G2P on
  every `type: "pronunciation"` drill's `target_text`.
- **`augment_spanish_pack.py`** — idempotently appends a follow-on lesson
  (12 more words/short phrases) to an existing Spanish pack JSON and wires
  the new drills into the Unit 1 exam. Usage:
  ```bash
  python augment_spanish_pack.py <in_pack.json> <out_pack.json>
  ```

Both scripts must be run with the G2P-capable venv described above — they
`import jingo_engine` directly.

## The phoneme -> id vocabulary

The `ids` in a phonetics record are indexes into the **model's own
`vocabulary.json`** (shipped with `facebook/wav2vec2-xlsr-53-espeak-cv-ft`,
Apache-2.0, downloaded at deploy time — no weights are committed to this
repo). The id for a given phoneme is simply that phoneme's position
(array index) in `vocabulary.json`. `jingo_engine` handles this mapping
internally via `DEFAULT_VOCAB_PATH`; authoring scripts should never
hand-maintain their own phoneme->id table.

## Spanish tap vs. trill

Spanish distinguishes two rhotic sounds that are easy to conflate when
writing prompts:

- **Tap `ɾ`** — the single "r" in words like `pero` ("but"). One quick
  flap of the tongue.
- **Trill `r`** — the "rr" in words like `perro` ("dog"), or a word-initial
  `r` (`rosa`). Multiple rapid taps.

These are phonemically distinct (`pero` vs `perro` is a minimal pair), so
drills that target this contrast (see `es-u1-l2` in `build_pack.py`) rely on
G2P correctly emitting `ɾ` vs `r` for the two target strings — don't assume
they're interchangeable when writing new prompts.

## Re-importing after edits

There is no instructor-facing "add a word" UI today (see the pronunciation
authoring roadmap for the planned in-UI, on-demand G2P feature). Until then,
the cycle is: edit/extend a pack's source data in one of these scripts (or
add a new script following the same pattern) -> re-run it on the Mac -> hand
the resulting JSON to an admin to import via `php artisan
libretexts:import-language-pack`.
