"""Embeddable engine facade: EngineConfig + Engine.score() -> versioned payload.

This is the surface other applications import (see README quickstart). It has
NO web-framework, database, or content-pack dependencies: everything the
engine needs arrives via :class:`EngineConfig` or the ``score()`` arguments.

The scoring contract (CONTRACT_VERSION) is the stable I/O promise: bumping the
model, curve, or engine internals bumps a version field in the payload, never
the caller's code. Payload shape::

    {
      "overall": float 0-100,
      "phoneme_scores": [{"phoneme","score","tag","frames","reliable","uncertainty"}, ...],
      "word_scores":    [{"phones","score","weakest","reliable"}, ...],
      "tag_scores":     {tag: float},
      "weak_tags":      [tag, ...],
      "duration_s":     float,
      "model":          str,
      "engine_version": str,
      "contract_version": str,
      "calibration_version": str,
      "provisional":    bool,
    }
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .calibration import DEFAULT_CALIBRATION_PATH, DEFAULT_VOCAB_PATH, Calibration, load_calibration

ENGINE_VERSION = "0.2.1"
CONTRACT_VERSION = "1.1"

MODEL_FILES = ("model.bin", "config.json", "vocabulary.json")


@dataclass(frozen=True)
class EngineConfig:
    """Everything the engine needs, passed explicitly by the embedding app."""

    model_dir: str | Path
    vocab_path: str | Path = DEFAULT_VOCAB_PATH
    calibration_path: str | Path = DEFAULT_CALIBRATION_PATH
    device: str = "cpu"
    compute_type: str = "int8"


@runtime_checkable
class PhoneticsProvider(Protocol):
    """How an app supplies canonical phonetics records and tag maps.

    A *record* is the shared-contract dict: ``{"phones": [...], "ids": [...],
    "words": [{"start", "len", "phones"}, ...]}`` (see contract.phonetics_for).
    Johnny Lingo's content-pack loader is one implementation; other apps can
    back this with their own storage, or skip providers entirely and pass
    records straight to :meth:`Engine.score`.
    """

    def get(self, language: str, exercise_id: str) -> dict[str, Any] | None: ...

    def tag_map(self, language: str) -> dict[str, str | None]: ...


def model_complete(model_dir: str | Path) -> bool:
    d = Path(model_dir)
    return all((d / name).exists() for name in MODEL_FILES)


class Engine:
    """A configured scorer instance. Pure ``audio -> payload``; no persistence."""

    def __init__(self, config: EngineConfig) -> None:
        self.config = config
        self.calibration: Calibration = load_calibration(str(config.calibration_path))
        self._scorer = None

    # -- availability ------------------------------------------------------ #
    @property
    def available(self) -> bool:
        return model_complete(self.config.model_dir) and Path(self.config.vocab_path).exists()

    def _get_scorer(self):
        if self._scorer is None:
            from .gop import GopScorer

            self._scorer = GopScorer(
                str(self.config.model_dir),
                str(self.config.vocab_path),
                device=self.config.device,
                compute_type=self.config.compute_type,
            )
        return self._scorer

    def phone_is_reliable(self, phone: str) -> bool:
        return self.calibration.phone_is_reliable(phone)

    # -- scoring ------------------------------------------------------------ #
    def score(
        self,
        audio_path: str | Path,
        record: dict[str, Any],
        *,
        tag_map: dict[str, str | None] | None = None,
    ) -> dict[str, Any]:
        """Score one utterance against a canonical phonetics ``record``.

        Raises on invalid input (no ids, unreadable audio, too-short audio) -
        embedding apps that want graceful degradation catch and fall back
        (Johnny Lingo's adapter returns None to trigger its text-proxy path).
        """
        if not record or not record.get("ids"):
            raise ValueError("phonetics record has no phone ids")
        result = self._get_scorer().score(str(audio_path), record)
        return build_payload(
            result, record, tag_map=tag_map, calibration=self.calibration,
            model_name=Path(self.config.model_dir).name,
        )

    def score_exercise(
        self,
        audio_path: str | Path,
        language: str,
        exercise_id: str,
        provider: PhoneticsProvider,
    ) -> dict[str, Any] | None:
        """Provider-mediated convenience: returns None when the provider has no
        record (mirrors the raise-vs-None split: bad *lookups* are None, bad
        *inputs* raise)."""
        record = provider.get(language, exercise_id)
        if not record or not record.get("ids"):
            return None
        return self.score(audio_path, record, tag_map=provider.tag_map(language))


def build_payload(
    result: Any,
    record: dict[str, Any],
    *,
    tag_map: dict[str, str | None] | None = None,
    calibration: Calibration | None = None,
    model_name: str = "",
) -> dict[str, Any]:
    """Assemble the versioned contract payload from a raw GopResult.

    Pure function — separated from :class:`Engine` so adapters/tests can drive
    it with any scorer (including stubs) while keeping the contract assembly
    in one place.
    """
    cal = calibration or load_calibration()
    tag_map = tag_map or {}
    phoneme_scores: list[dict[str, Any]] = []
    tag_totals: dict[str, list[float]] = {}
    aggregate_values: list[float] = []
    exclude_abstain = _exclude_abstain_from_aggregates(cal)
    for ps in result.phoneme_scores:
        tag = tag_map.get(ps.phoneme)
        reliable = cal.phone_is_reliable(ps.phoneme)
        uncertainty = cal.phone_uncertainty(
            ps.phoneme, ps.score, ps.frames, reliable=reliable,
        )
        phone_payload = {
            "phoneme": ps.phoneme,
            "score": ps.score,
            "tag": tag,
            "frames": ps.frames,
            "reliable": reliable,
        }
        if uncertainty is not None:
            phone_payload["uncertainty"] = uncertainty
            phone_payload["abstain"] = uncertainty["abstain"]
        phoneme_scores.append(phone_payload)
        if _phone_is_actionable(phone_payload, exclude_abstain):
            aggregate_values.append(ps.score)
            if tag:
                tag_totals.setdefault(tag, []).append(ps.score)

    tag_scores = {tag: round(sum(v) / len(v), 1) for tag, v in tag_totals.items()}
    weak_tags = sorted(t for t, s in tag_scores.items() if s < cal.weak_tag_threshold)
    # User-facing aggregates ignore unactionable phones; if somehow every phone
    # is gated out, fall back to the scorer's own overall rather than 0.
    overall = (
        round(sum(aggregate_values) / len(aggregate_values), 1)
        if aggregate_values
        else result.as_dimension()
    )
    return {
        "overall": overall,
        "phoneme_scores": phoneme_scores,
        "word_scores": _aggregate_words(
            phoneme_scores,
            record.get("words", []),
            exclude_abstain=exclude_abstain,
        ),
        "tag_scores": tag_scores,
        "weak_tags": weak_tags,
        "duration_s": result.duration_s,
        "model": model_name,
        "engine_version": ENGINE_VERSION,
        "contract_version": CONTRACT_VERSION,
        "calibration_version": cal.version,
        "provisional": cal.provisional,
    }


def _exclude_abstain_from_aggregates(cal: Calibration) -> bool:
    return bool(cal.uncertainty and cal.uncertainty.aggregate_gate == "exclude_abstain")


def _phone_is_actionable(phone: dict[str, Any], exclude_abstain: bool) -> bool:
    if not phone.get("reliable", True):
        return False
    if exclude_abstain and phone.get("abstain") is True:
        return False
    return True


def _aggregate_words(
    phoneme_scores: list[dict[str, Any]], words: list[dict[str, Any]], *,
    exclude_abstain: bool = False,
) -> list[dict[str, Any]]:
    """Per-word rollup over the payload phone dicts (mirrors GopScorer's word
    aggregation but skips unactionable phones). A word made up entirely of
    unreliable/abstained phones is flagged ``reliable: false`` with its raw
    score — consumers must not surface its score/weakest as feedback."""
    out: list[dict[str, Any]] = []
    for w in words:
        start, length = w.get("start", 0), w.get("len", 0)
        seg = phoneme_scores[start:start + length]
        if not seg:
            continue
        actionable_seg = [p for p in seg if _phone_is_actionable(p, exclude_abstain)]
        basis = actionable_seg or seg
        out.append({
            "phones": [p["phoneme"] for p in seg],
            "score": round(sum(p["score"] for p in basis) / len(basis), 1),
            "weakest": min(basis, key=lambda p: p["score"])["phoneme"],
            "reliable": bool(actionable_seg),
        })
    return out


@lru_cache(maxsize=4)
def get_engine(model_dir: str, vocab_path: str, calibration_path: str,
               device: str = "cpu", compute_type: str = "int8") -> Engine:
    """Cached Engine factory keyed on the config tuple (model loads are heavy)."""
    return Engine(EngineConfig(model_dir, vocab_path, calibration_path, device, compute_type))
