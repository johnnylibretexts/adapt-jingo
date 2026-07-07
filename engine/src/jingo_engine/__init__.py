"""johnnylingo-jingo: portable per-phoneme pronunciation-scoring engine.

Quickstart::

    from jingo_engine import Engine, EngineConfig

    engine = Engine(EngineConfig(model_dir="path/to/wav2vec2-xlsr-53-espeak-ct2"))
    payload = engine.score("attempt.wav", record)   # record: {"phones", "ids", "words"}

``record`` comes from the shared phoneme contract (``contract.phonetics_for``
at build time, or any store implementing :class:`PhoneticsProvider`).
"""
from .calibration import (  # noqa: F401
    DEFAULT_CALIBRATION_PATH,
    DEFAULT_VOCAB_PATH,
    Calibration,
    PhoneUncertaintyBand,
    UncertaintyConfig,
    load_calibration,
)
from .engine import (  # noqa: F401
    CONTRACT_VERSION,
    ENGINE_VERSION,
    MODEL_FILES,
    Engine,
    EngineConfig,
    PhoneticsProvider,
    get_engine,
    model_complete,
)
from .model_assets import (  # noqa: F401
    DEFAULT_HF_MODEL_FILENAME,
    DEFAULT_HF_MODEL_REPO_ID,
    DEFAULT_HF_MODEL_REVISION,
    DEFAULT_MODEL_MANIFEST_PATH,
    ModelAssetError,
    ensure_model,
    ensure_model_from_huggingface,
    huggingface_archive_url,
    load_model_manifest,
    verify_model_dir,
    verify_or_raise,
)

__version__ = ENGINE_VERSION
