# adapt-jingo

**jingo** is the pronunciation-assessment engine used by [ADAPT](https://adapt.libretexts.org)'s
`pronunciation` question type. It scores a learner's spoken-audio submission against a
reference pronunciation at the phoneme level and reports the result back to ADAPT's
gradebook.

This repository packages jingo as four independent, MIT-licensed parts:

| Part | What it is |
|---|---|
| [`service/`](service/) | A FastAPI scoring service exposing a `/score` endpoint. This is the network-facing component ADAPT talks to. |
| [`engine/`](engine/) | `jingo_engine` — the scoring library. Computes Goodness of Pronunciation (GOP) over a CTranslate2-exported wav2vec2 phoneme model. Torch-free at runtime. **Does not bundle the model itself.** |
| [`authoring/`](authoring/) | Build-time grapheme-to-phoneme (G2P) tooling used to construct language packs (word lists + reference phoneme sequences) consumed by the engine. |
| [`adapt-integration/`](adapt-integration/) | The ADAPT-side changes required to wire the `pronunciation` question type to a running jingo service, delivered as patches (`patches/`) and copy-in files (`files/`). |
| [`tts/`](tts/) | `jingo-tts` — a small self-hosted text-to-speech service powering the **"Hear it"** button, so a learner can hear a model pronunciation before recording. **Pluggable engine** (`TTS_ENGINE`): open-source [Kokoro-82M](https://github.com/hexgrad/kokoro) (Apache-2.0, default) or Piper, or optional cloud voices (Gemini / **Amazon Polly**) for the most natural output. On-demand + cached; a pitch-preserving `TTS_RATE` tempo knob slows delivery for learners. |

## Architecture

Student records audio in ADAPT's `pronunciation` question type. The audio is uploaded to
object storage (e.g. MinIO). ADAPT then calls the jingo `service/` `/score` endpoint, which
uses `engine/` to score the submitted audio's phonemes against the question's reference
pronunciation. The service returns a score and a per-phoneme breakdown, which ADAPT signs
into an answer JWT and posts back into its own gradebook. See
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full diagram and component
responsibilities. *(Added in a later phase of this repo.)*

## "Hear it" exemplar audio (optional)

Alongside *scoring* a learner's attempt, jingo can *play a model pronunciation* of the
prompt via the optional [`tts/`](tts/) service. When ADAPT is configured with a TTS URL, the
`pronunciation` question shows a **🔊 Hear it** button above the recorder — "listen, then
record." It synthesizes on demand from the same text as the question (no per-word audio files
to manage), caches the result, and the demo cache is pre-warmed so playback is instant.
Spanish + French supported.

The engine is pluggable via `TTS_ENGINE` (see [`tts/README.md`](tts/README.md)): the default
is open-source **Kokoro-82M** (Apache-2.0). For the most natural voices, an optional
**Amazon Polly** backend uses generative es-MX (**Mía**) and fr-FR (**Léa**) voices — opt-in,
needs an AWS IAM key pair, so it stays inert until credentials are supplied. `TTS_RATE`
(default `1.0`; `<1` = slower) applies a pitch-preserving tempo change across every engine so
the model pronunciation can be a touch slower for clarity.

## Implementing this in your ADAPT (what you need)

To run the full pronunciation feature on your own LibreTexts ADAPT instance, you need **two
things from this repo**: the self-hosted **service(s)**, and the **ADAPT-side integration**.
Everything here is MIT and self-hostable — no proprietary dependency is required (the optional
Amazon Polly TTS voice is the one opt-in exception, and the default TTS engine is open-source).

1. **Deploy the scorer** — the [`service/`](service/) FastAPI app + the [`engine/`](engine/)
   library, as a container. It needs the phoneme **model** (not bundled; the engine's
   downloader fetches `facebook/wav2vec2-xlsr-53-espeak-cv-ft` → CTranslate2 at deploy time)
   and a **records directory** (the per-exercise reference pronunciations). Set a shared
   `WEBWORK_JWT_SECRET` (same value as ADAPT) so signed problem/answer JWTs verify. See
   [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).
2. **(Optional) Deploy jingo-tts** — the [`tts/`](tts/) service for the 🔊 "Hear it" button.
   Default engine is open-source Kokoro; optionally Amazon Polly for the most natural voices.
   Point ADAPT at it with `PRONUNCIATION_TTS_URL`. Skip this and scoring still works — the
   button is just hidden. See [`tts/README.md`](tts/README.md).
3. **Apply the ADAPT-side integration** — [`adapt-integration/`](adapt-integration/) packages
   the ~13 ADAPT files (the `pronunciation` question type, the `PronunciationQuestion.vue`
   widget with Hear-it / practice-embed / word-level views, the DB migration, the
   `libretexts:import-language-pack` command, the JWT/sync wiring) as a **15-patch series**
   (`git am patches/*.patch`) plus clean copy-in snapshots. Full step-by-step +
   post-apply checklist in [`adapt-integration/INTEGRATION.md`](adapt-integration/INTEGRATION.md).
   Then `npm i` + rebuild the SPA, `php artisan migrate`, and set
   `window.config.pronunciationServiceUrl` (+ `pronunciationTtsUrl` if using Hear-it).
4. **Author/import a language pack** — build reference records with the
   [`authoring/`](authoring/) G2P tools (`gen_word_records.py`, espeak/phonemizer, Mac/Linux
   with espeak-ng), then `php artisan libretexts:import-language-pack` to load a course.
   Optional: embed **login-free practice** anywhere by iframing
   `/embed/pronunciation?exercise_id=…&lang=…&prompt=…` with `allow="microphone"`.

**You do not need any private fork** — `adapt-integration/` applies onto upstream ADAPT
(`git am -3` if your tree has diverged). This repo is the single, self-contained source.

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for the full stand-up walkthrough (service,
model, language pack, ADAPT wiring).

## Model

jingo scores audio using `facebook/wav2vec2-xlsr-53-espeak-cv-ft` (Apache-2.0), exported to
CTranslate2 format. **No model weights are committed to this repository** — the engine
fetches/exports the model at deploy time.

## Scoring — how a score is produced

jingo scores at the **phoneme** level and rolls up to a single 0–100 number.

1. **Forced alignment + GOP.** The wav2vec2 phoneme model emits per-frame
   posteriors over the espeak phoneme inventory. For each expected phoneme in the
   reference sequence, the engine computes a **Goodness of Pronunciation (GOP)
   ratio** — roughly, the log-probability the model assigned to the *expected*
   phoneme minus the best competing phoneme, over the frames aligned to it. The
   ratio is `≤ 0`, where **`0` = a perfect match** and more-negative = worse.
2. **Calibration curve (primary knob).** Each raw GOP ratio is mapped to 0–100
   through a **normalized logistic** curve
   (`score = 100 · σ(slope·(ratio − midpoint)) / σ(slope·midpoint@0)`), so a
   perfect phoneme scores exactly 100. The curve lives in a swappable JSON asset,
   **not** in code:
   [`engine/src/jingo_engine/assets/calibration-v1.json`](engine/src/jingo_engine/assets/calibration-v1.json)
   → `curve: { midpoint, slope }`.
3. **Overall = mean (secondary knob).** The word/utterance `overall` is the
   **arithmetic mean** of the reliable per-phoneme scores. One bad sound among
   several good ones is therefore *diluted* — if you want isolated mistakes to
   bite harder, this is the place to change the aggregation (e.g. penalize the
   worst phoneme, or use a low percentile instead of the mean).

### Current curve — **STRICT** (`midpoint −2.0, slope 1.5`, `v1.2-strict-2026.07`)

| Sound quality | GOP ratio | Score |
|---|---|---|
| perfect | 0 | 100 |
| nearly perfect | −0.5 | 95 |
| mildly off | −1.0 | 86 |
| noticeably off | −1.5 | 71 |
| clearly off | −2.0 | 52 |
| quite wrong | −3.0 | 19 |
| very wrong | −4.0 | 5 |

**Making it stricter or looser:** move `midpoint` toward `0` and/or raise `slope`
to be **stricter** (the same audio scores lower); move `midpoint` more negative
and/or lower `slope` to be **more lenient**. The prior default was `−3.0 / 1.3`
(much more forgiving: "clearly off" scored ~80). Because the curve is baked into
the engine package at install time, **changing it requires rebuilding the jingo
image** (`docker compose build` in the jingo deploy dir) and restarting the
container — a plain restart is not enough.

### Other scoring knobs (also in the calibration JSON)

- **`weak_tag_threshold`** — phonemes scoring below this are surfaced to the
  learner as "sounds to review."
- **`unreliable_phones`** — a quarantine list of phonemes the model can't judge
  dependably (per real-audio verdicts). These are shown greyed-out ("not judged
  confidently") and, with `aggregate_gate: reliable_only`, are **excluded from
  the overall mean** rather than dragging it down.
- **`equivalence_classes`** — accepted standard/dialectal realizations that are
  scored as one class (e.g. Spanish *yeísmo* `ʝ/j/ʎ`, spirantization `β/b`, French
  nasal mergers), so a valid regional variant isn't marked wrong.
- **`uncertainty`** — shadow split-conformal confidence bands per phoneme; a
  conservative *abstain* recommendation the UI can honor, not an automatic score
  change.

### Feedback display (in ADAPT's UI)

`PronunciationQuestion.vue` defaults to a **word-level** view: the scorer returns
per-word spans (`words: [{text, start, len}]`) alongside the flat `phoneme_scores`,
and the UI rolls the per-sound scores up to the real words — colouring each word so a
learner sees *which word* to fix, in normal spelling. The raw IPA per-phoneme chips sit
under a collapsible **"Show sounds (IPA)"** toggle. When a record has no per-word text
(e.g. an elision merge, or a pack not yet regenerated with word text), the UI falls back
to the flat per-sound chips.

Colours come from the calibrated score in both views: **≥ 75 = good** (green),
**≥ 60 = ok** (amber), **otherwise = needs work** (red); quarantined/low-confidence
phonemes render grey with a `–`. Word colour is the mean of the word's reliable sounds.

### Important caveats (from the engine's own calibration notes)

- All calibration values are **PROVISIONAL** — the curve was fit on a
  synthetic-TTS proxy and triaged against real audio (TalkBank/YouTube), not on
  human-rated learner audio.
- Absolute thresholds are **channel-sensitive** — mic, codec, and room noise
  shift the raw ratios, which is exactly why every score is flagged *provisional
  — treat as approximate* in the UI.
- Real-audio triage found the previous low end **too lenient**; the STRICT curve
  above is the response to that (and to operator feedback that scoring was too
  generous).

## Accuracy disclaimer

Scoring produced by jingo is **provisional** (`provisional: true` in engine output). It is a
practice-and-feedback aid, **not** a validated, high-stakes, or clinical pronunciation
assessment tool. Calibration has not been independently verified against a clinical or
standardized benchmark.

## License

MIT — see [`LICENSE`](LICENSE). This covers all four parts of this repository, including the
engine (whose scoring approach is relicensed under MIT for this project). The wav2vec2 model
itself is separately licensed (Apache-2.0) and is not distributed here.
