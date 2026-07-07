# jingo_engine — portable pronunciation-scoring engine

`jingo_engine` is a per-phoneme Goodness-of-Pronunciation (GOP) scoring engine
for language-learning applications. Scoring runs over a CTranslate2 wav2vec2
phone-CTC model — **torch-free at runtime** (just `numpy` + `ctranslate2`),
fully offline on CPU. Spanish and French are calibrated today; the mechanics
are language-agnostic given a phone-CTC model and a G2P front end.

License: **MIT** (see `LICENSE`).

## Install

```sh
pip install ./engine
```

## Quickstart

```python
from jingo_engine import Engine, EngineConfig

engine = Engine(EngineConfig(model_dir="models/wav2vec2-xlsr-53-espeak-ct2"))
payload = engine.score("attempt.wav", record)   # 16 kHz mono PCM wav
print(payload["overall"], payload["weak_tags"])
```

`record` is a **phonetics record** — the canonical phone sequence the audio is
scored against:

```python
{"phones": ["b", "o", "l", "a"], "ids": [54, 27, 31, 5],
 "words": [{"start": 0, "len": 4, "phones": [...]}]}   # word spans optional
```

## Model asset — not bundled

The acoustic model (`facebook/wav2vec2-xlsr-53-espeak-cv-ft`, Apache-2.0,
converted to CTranslate2 int8) is **not** bundled with this package. Point
`EngineConfig.model_dir` at a local conversion of that model. See
[`../model/README.md`](../model/README.md) for how to obtain/convert it.

## Accuracy disclaimer

This engine is **provisional**: scoring payloads carry `"provisional": true`.
Calibration is unvalidated against human tutor ratings and is
channel-sensitive (close-mic vs. far-field). **This is not a clinical,
academic, hiring, certification, or high-stakes assessment tool** — see
`NOTICE.md` and `THIRD_PARTY_NOTICES.md` for the full disclaimers and
third-party licensing notes.
