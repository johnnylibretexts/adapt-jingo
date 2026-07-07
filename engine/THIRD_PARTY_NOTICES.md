# Third-Party Notices

This file is a public-release review aid, not a complete legal opinion.

- Runtime package dependencies:
  - `numpy`
  - `ctranslate2`
- External acoustic model:
  - Source model: `facebook/wav2vec2-xlsr-53-espeak-cv-ft`
  - Source model license recorded in `src/jingo_engine/assets/model-manifest.json`: `Apache-2.0`
  - Converted artifact format: CTranslate2 Wav2Vec2 int8
  - The converted CT2 artifact is not bundled in the Python wheel.
- Optional build-time G2P dependencies:
  - `phonemizer`
  - `espeakng-loader`
  - These are documented as build-time only and must not become runtime product
    dependencies unless a separate licensing review approves that use.

Before any public PyPI or marketplace release, refresh this notice from the
resolved lockfile and verify license compatibility for each runtime,
build-time, model, and packaging dependency.
