"""Versioned calibration config for the pronunciation engine.

All scoring knobs (curve, weak-tag threshold, reliability quarantine,
dialectal equivalence classes) live in a JSON asset, NOT in source, so that
(a) the calibration pipeline writes config instead of editing code, and
(b) embedding applications can supply their own calibration without forking.

The packaged default is ``assets/calibration-v1.json`` - PROVISIONAL until
validated on human-rated learner audio (the asset says so itself).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
DEFAULT_CALIBRATION_PATH = ASSETS_DIR / "calibration-v1.json"
DEFAULT_VOCAB_PATH = ASSETS_DIR / "model_vocab.json"


@dataclass(frozen=True)
class PhoneUncertaintyBand:
    n: int
    band: float
    native_p10: float | None = None
    native_p50: float | None = None
    native_p90: float | None = None
    frame_p50: float | None = None


@dataclass(frozen=True)
class UncertaintyConfig:
    enabled: bool
    method: str
    aggregate_gate: str
    confidence: float
    min_band: float
    default_band: float
    max_abstain_band: float
    min_native_observations: int
    min_frames: int
    phone_bands: dict[str, PhoneUncertaintyBand]


@dataclass(frozen=True)
class Calibration:
    version: str
    provisional: bool
    curve_midpoint: float
    curve_slope: float
    weak_tag_threshold: float
    unreliable_phones: frozenset[str]
    equivalence_classes: tuple[frozenset[str], ...]
    uncertainty: UncertaintyConfig | None = None

    @property
    def unreliable_bases(self) -> frozenset[str]:
        return frozenset(_phone_base(p) for p in self.unreliable_phones)

    def phone_is_reliable(self, phone: str) -> bool:
        return _phone_base(phone) not in self.unreliable_bases

    def phone_uncertainty(self, phone: str, score: float, frames: int, *,
                          reliable: bool) -> dict[str, object] | None:
        """Return a shadow uncertainty band for one scored phone.

        The default asset uses split-conformal native score bands: the band is
        the 90% quantile of ``100 - native_score`` for the phone. It is a
        conservative *abstain recommendation*, not an automatic user-facing
        threshold change; consumers can ignore it until their UI/validation is
        ready.
        """
        cfg = self.uncertainty
        if cfg is None or not cfg.enabled:
            return None

        band_info = cfg.phone_bands.get(phone) or cfg.phone_bands.get(_phone_base(phone))
        n = band_info.n if band_info else 0
        if band_info and n >= cfg.min_native_observations:
            band = max(cfg.min_band, band_info.band)
            reason = "ok"
        elif band_info:
            band = max(cfg.min_band, cfg.default_band, band_info.band)
            reason = "low_native_n"
        else:
            band = max(cfg.min_band, cfg.default_band)
            reason = "no_native_band"

        abstain = False
        if not reliable:
            abstain = True
            reason = "quarantined_phone"
        elif frames < cfg.min_frames:
            abstain = True
            reason = "too_few_frames"
        elif band > cfg.max_abstain_band:
            abstain = True
            reason = "wide_native_band"

        score_f = float(score)
        return {
            "method": cfg.method,
            "confidence": cfg.confidence,
            "band": round(float(band), 1),
            "lower": round(max(0.0, score_f - band), 1),
            "upper": round(min(100.0, score_f + band), 1),
            "abstain": abstain,
            "reason": reason,
            "native_n": n,
        }


def _phone_base(phone: str) -> str:
    """Length-mark-insensitive form (u / uː / u: match). Mirrors gop._base."""
    return phone.replace("ː", "").replace(":", "").replace("ˑ", "")


@lru_cache(maxsize=8)
def load_calibration(path: str | None = None) -> Calibration:
    """Load and validate a calibration config (default: the packaged asset)."""
    p = Path(path) if path else DEFAULT_CALIBRATION_PATH
    raw = json.loads(p.read_text(encoding="utf-8"))
    curve = raw["curve"]
    uncertainty = _load_uncertainty(raw.get("uncertainty"))
    return Calibration(
        version=str(raw["calibration_version"]),
        provisional=bool(raw.get("provisional", True)),
        curve_midpoint=float(curve["midpoint"]),
        curve_slope=float(curve["slope"]),
        weak_tag_threshold=float(raw["weak_tag_threshold"]),
        unreliable_phones=frozenset(raw["unreliable_phones"]),
        equivalence_classes=tuple(frozenset(c) for c in raw["equivalence_classes"]),
        uncertainty=uncertainty,
    )


def _load_uncertainty(raw: dict | None) -> UncertaintyConfig | None:
    if not raw:
        return None
    bands = {
        str(phone): PhoneUncertaintyBand(
            n=int(info["n"]),
            band=float(info["band"]),
            native_p10=_maybe_float(info.get("native_p10")),
            native_p50=_maybe_float(info.get("native_p50")),
            native_p90=_maybe_float(info.get("native_p90")),
            frame_p50=_maybe_float(info.get("frame_p50")),
        )
        for phone, info in raw.get("phone_bands", {}).items()
    }
    return UncertaintyConfig(
        enabled=bool(raw.get("enabled", True)),
        method=str(raw.get("method", "split_conformal_native_score_band")),
        confidence=float(raw.get("confidence", 0.9)),
        aggregate_gate=str(raw.get("aggregate_gate", "reliable_only")),
        min_band=float(raw.get("min_band", 5.0)),
        default_band=float(raw.get("default_band", 35.0)),
        max_abstain_band=float(raw.get("max_abstain_band", 45.0)),
        min_native_observations=int(raw.get("min_native_observations", 8)),
        min_frames=int(raw.get("min_frames", 1)),
        phone_bands=bands,
    )


def _maybe_float(value: object) -> float | None:
    return None if value is None else float(value)
