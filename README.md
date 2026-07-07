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

## Architecture

Student records audio in ADAPT's `pronunciation` question type. The audio is uploaded to
object storage (e.g. MinIO). ADAPT then calls the jingo `service/` `/score` endpoint, which
uses `engine/` to score the submitted audio's phonemes against the question's reference
pronunciation. The service returns a score and a per-phoneme breakdown, which ADAPT signs
into an answer JWT and posts back into its own gradebook. See
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full diagram and component
responsibilities. *(Added in a later phase of this repo.)*

## Quickstart

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for how to stand up the service, obtain the
phoneme model, build or import a language pack, and connect it to an ADAPT instance.
*(Added in a later phase of this repo.)*

## Model

jingo scores audio using `facebook/wav2vec2-xlsr-53-espeak-cv-ft` (Apache-2.0), exported to
CTranslate2 format. **No model weights are committed to this repository** — the engine
fetches/exports the model at deploy time.

## Accuracy disclaimer

Scoring produced by jingo is **provisional** (`provisional: true` in engine output). It is a
practice-and-feedback aid, **not** a validated, high-stakes, or clinical pronunciation
assessment tool. Calibration has not been independently verified against a clinical or
standardized benchmark.

## License

MIT — see [`LICENSE`](LICENSE). This covers all four parts of this repository, including the
engine (whose scoring approach is relicensed under MIT for this project). The wav2vec2 model
itself is separately licensed (Apache-2.0) and is not distributed here.
