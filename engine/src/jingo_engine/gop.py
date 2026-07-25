"""Acoustic Goodness-of-Pronunciation (GOP) scorer.

Computes genuine per-phoneme pronunciation scores from learner audio using a
CTranslate2-converted wav2vec2 phoneme-CTC acoustic model. Runtime dependencies
are ctranslate2 + numpy only -- NO torch -- so this runs inside a packaged app.

Pipeline (validated in the Phase-2 spike):
  audio -> model.encode() -> frame logits (T x 392) -> log-softmax
        -> CTC Viterbi alignment of the canonical phone-id sequence
        -> per-phone GOP (log-posterior + competitor ratio; length-variant AND
           dialectal-equivalence merged -- see the calibration asset)
        -> calibrate to 0-100, aggregate to words.

The canonical phone-id sequence comes from the shared contract (built offline by
the content phonemizer or supplied directly by the embedding application).

Calibration: the 0-100 mapping is a normalized logistic whose parameters live in
the versioned calibration asset (``assets/calibration-v1.json``), PROVISIONAL
until validated on human-rated learner audio. Two alignment remedies for
low-scoring short phones were tested and rejected (frame-window dilation
over-forgave wrong-text audio; a +/-1-frame rescue barely moved native ratios),
so the low end is compressed in the calibration curve instead. Note this does
NOT verify the alignment is correct: CTC is peaky (~95% of phones are scored on
a single frame) and no independent forced-aligner comparison has been done.
"""
from __future__ import annotations

import json
import wave
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import numpy as np

from .calibration import load_calibration

try:  # ctranslate2 is bundled at runtime; keep import errors actionable
    import ctranslate2
except ImportError:  # pragma: no cover
    ctranslate2 = None

BLANK_ID = 0
SAMPLE_RATE = 16000

# Scoring knobs come from the versioned calibration asset (single source of
# truth; see calibration.py). The module-level names are kept for backward
# compatibility with existing scripts/tests that import them.
_CAL = load_calibration()
CALIBRATION_MIDPOINT = _CAL.curve_midpoint
CALIBRATION_SLOPE = _CAL.curve_slope
# Dialectal / allophonic equivalence classes: phone STRINGS scored as a single
# class - a canonical phone earns FULL credit if the learner produces ANY
# member (logsumexp over the group in ``_phone_logp``). Every member is an
# accepted standard realization of the target sound (es yeismo, velar-nasal
# assimilation, fr nasal merger, es spirantization) - a deliberate pedagogical
# choice for a beginner app; penalizing the difference would only generate
# false "mispronunciation" alarms. Rationale + history: the calibration asset
# notes and phonemes/README.md. Composition with length-mark stripping: classes
# are keyed by the *base* form (see ``_base``), and only tokens present in the
# model vocab are merged (guarded in ``_equivalence_base_map``), so a class
# referencing an absent token degrades safely to a smaller group.
EQUIVALENCE_CLASSES: list[frozenset[str]] = list(_CAL.equivalence_classes)


# --------------------------------------------------------------------------- #
# Audio + math helpers
# --------------------------------------------------------------------------- #
def load_wav_16k_mono(path: str) -> np.ndarray:
    """Load a 16 kHz mono 16-bit PCM WAV, normalized (zero-mean/unit-var)."""
    with wave.open(path, "rb") as w:
        if w.getframerate() != SAMPLE_RATE or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError(f"{path}: expected 16kHz mono 16-bit PCM")
        raw = w.readframes(w.getnframes())
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    return (audio - audio.mean()) / np.sqrt(audio.var() + 1e-7)


def log_softmax(x: np.ndarray) -> np.ndarray:
    x = x - x.max(-1, keepdims=True)
    return x - np.log(np.exp(x).sum(-1, keepdims=True))


def _base(token: str) -> str:
    """Collapse length/diacritic variants so u, uː, u: share a class."""
    return token.replace("ː", "").replace(":", "").replace("ˑ", "")


def _equivalence_base_map(known_bases: set[str]) -> dict[str, str]:
    """Map each class member's *base* to a single canonical class key.

    Built defensively against the actual vocab: only members whose base is
    present in ``known_bases`` participate, and a class is only merged when it
    still has >=2 present members. The canonical key is the lexicographically
    smallest present base, so every member of a class resolves to the same key
    and therefore the same scoring group.
    """
    base_map: dict[str, str] = {}
    for cls in EQUIVALENCE_CLASSES:
        present = sorted({_base(p) for p in cls} & known_bases)
        if len(present) < 2:
            continue  # nothing to merge once vocab-filtered; leave bases as-is
        key = present[0]
        for b in present:
            base_map[b] = key
    return base_map


@lru_cache(maxsize=4)
def _variant_groups(vocab_path: str) -> dict[int, tuple[int, ...]]:
    """phone-id -> ids of vocab tokens scored together.

    Two mergers are composed, both keyed off the length-stripped ``_base`` form:
      1. length/diacritic variants (u / uː / u: share a base), and
      2. the dialectal EQUIVALENCE_CLASSES above (yeísmo, velar-nasal
         assimilation, the French nasal merger, Spanish spirantization).
    The class key folds equivalent bases onto one shared key, so every token in
    a class — including any that also carries a length mark — lands in the same
    group and earns full credit through the group logsumexp.
    """
    vocab = json.loads(open(vocab_path).read())
    known_bases = {_base(tok) for tok in vocab if not tok.startswith("<")}
    base_map = _equivalence_base_map(known_bases)

    def _key(tok: str) -> str:
        b = _base(tok)
        return base_map.get(b, b)

    key_to_ids: dict[str, list[int]] = {}
    for tok, i in vocab.items():
        if not tok.startswith("<"):
            key_to_ids.setdefault(_key(tok), []).append(i)
    groups: dict[int, tuple[int, ...]] = {}
    for tok, i in vocab.items():
        if not tok.startswith("<"):
            groups[i] = tuple(sorted(set(key_to_ids[_key(tok)])))
    return groups


def calibrate(ratio: float, midpoint: float = CALIBRATION_MIDPOINT,
              slope: float = CALIBRATION_SLOPE) -> float:
    """Map a per-phone GOP ratio (<=0; 0 = perfect) to a 0-100 score.

    Normalized logistic: an S-curve through ``midpoint``, rescaled so a perfect
    phone (ratio 0) scores exactly 100. As a monotone transform it does not
    change which phone ranks above which -- the gain over the earlier
    exponential is in *absolute placement*: the low end is compressed (a single
    weak frame is not a hard zero) and the native/accented/wrong cohorts land
    on the intended 0-100 bands. Non-finite ratios score 0.
    """
    r = min(float(ratio), 0.0)
    if not np.isfinite(r):
        return 0.0
    raw = 1.0 / (1.0 + np.exp(-slope * (r - midpoint)))
    ceil = 1.0 / (1.0 + np.exp(slope * midpoint))  # value at ratio == 0
    return float(np.clip(100.0 * raw / ceil, 0.0, 100.0))


def min_ctc_frames(ids: list[int]) -> int:
    """Minimum frames for a valid CTC path: one per phone, plus a mandatory
    blank between identical consecutive phones."""
    return len(ids) + sum(1 for a, b in zip(ids, ids[1:]) if a == b)


# --------------------------------------------------------------------------- #
# Scorer
# --------------------------------------------------------------------------- #
@dataclass
class PhonemeScore:
    phoneme: str
    score: float
    frames: int
    logpost: float
    ratio: float


@dataclass
class GopResult:
    phoneme_scores: list[PhonemeScore]
    word_scores: list[dict[str, Any]] = field(default_factory=list)
    overall: float = 0.0
    duration_s: float = 0.0

    def as_dimension(self) -> float:
        return round(self.overall, 1)


class GopScorer:
    """Loads a converted wav2vec2 phoneme-CTC model and scores utterances."""

    def __init__(self, ct2_model_dir: str, vocab_path: str, *, device: str = "cpu",
                 compute_type: str = "int8") -> None:
        if ctranslate2 is None:  # pragma: no cover
            raise RuntimeError("ctranslate2 is required for acoustic phoneme scoring")
        self._model = ctranslate2.models.Wav2Vec2(ct2_model_dir, device=device,
                                                   compute_type=compute_type)
        self._groups = _variant_groups(vocab_path)

    def _frame_logprobs(self, wav_path: str) -> tuple[np.ndarray, float]:
        audio = load_wav_16k_mono(wav_path)
        feats = np.ascontiguousarray(audio.reshape(1, 1, -1), dtype=np.float32)
        out = self._model.encode(ctranslate2.StorageView.from_array(feats), to_cpu=True)
        return log_softmax(np.array(out)[0]), len(audio) / SAMPLE_RATE

    def _phone_logp(self, logp: np.ndarray, phone_id: int) -> np.ndarray:
        grp = self._groups.get(phone_id)
        if not grp:
            return logp[:, phone_id]
        sub = logp[:, list(grp)]
        mx = sub.max(-1)
        return mx + np.log(np.exp(sub - mx[:, None]).sum(-1))  # logsumexp over variants

    @staticmethod
    def _ctc_align(logp: np.ndarray, ids: list[int]) -> np.ndarray:
        """Viterbi CTC alignment -> frame -> phone index (-1 for blank frames)."""
        T = logp.shape[0]
        ext = [BLANK_ID]
        for p in ids:
            ext += [p, BLANK_ID]
        L = len(ext)
        neg = -1e30
        dp = np.full((T, L), neg)
        bp = np.zeros((T, L), dtype=np.int32)
        dp[0, 0] = logp[0, ext[0]]
        if L > 1:
            dp[0, 1] = logp[0, ext[1]]
        for t in range(1, T):
            for l in range(L):
                best, arg = dp[t - 1, l], l
                if l - 1 >= 0 and dp[t - 1, l - 1] > best:
                    best, arg = dp[t - 1, l - 1], l - 1
                if l - 2 >= 0 and ext[l] != BLANK_ID and ext[l] != ext[l - 2] and dp[t - 1, l - 2] > best:
                    best, arg = dp[t - 1, l - 2], l - 2
                dp[t, l] = best + logp[t, ext[l]]
                bp[t, l] = arg
        l = L - 1 if dp[T - 1, L - 1] >= dp[T - 1, L - 2] else L - 2
        frame_phone = np.full(T, -1, dtype=np.int32)
        for t in range(T - 1, -1, -1):
            if ext[l] != BLANK_ID:
                frame_phone[t] = (l - 1) // 2
            l = bp[t, l]
        return frame_phone

    def score(self, wav_path: str, phonetics: dict[str, Any]) -> GopResult:
        """Score an utterance against a canonical phonetics record (from the
        content phonemizer). ``phonetics`` must carry ``ids`` (phone-id seq),
        ``phones`` and optional ``words`` spans."""
        ids: list[int] = phonetics["ids"]
        phones: list[str] = phonetics["phones"]
        if not ids:
            raise ValueError("phonetics record has no phone ids")
        logp, dur = self._frame_logprobs(wav_path)
        if logp.shape[0] < min_ctc_frames(ids):
            # No valid CTC path exists (e.g. truncated recording vs a long
            # phrase). _ctc_align would silently backtrack through unreachable
            # states and mark every phone deleted; refuse instead so the
            # service degrades to "no acoustic score".
            raise ValueError(
                f"audio too short to align: {logp.shape[0]} frames for "
                f"{len(ids)} phones ({dur:.2f}s)"
            )
        frame_phone = self._ctc_align(logp, ids)
        per_frame_max = logp.max(-1)

        scores: list[PhonemeScore] = []
        for i, pid in enumerate(ids):
            plp = self._phone_logp(logp, pid)
            frames = np.where(frame_phone == i)[0]
            if len(frames) == 0:
                # Whenever a valid CTC path exists, Viterbi assigns every
                # phone >=1 frame (verified by brute force), so this branch
                # only fires if the alignment itself failed -- score 0 rather
                # than fabricating evidence from unrelated frames.
                logpost = float(plp.max())
                ratio = float("-inf")
                nframes = 0
            else:
                logpost = float(plp[frames].mean())
                ratio = float((plp[frames] - per_frame_max[frames]).mean())
                nframes = int(len(frames))
            scores.append(PhonemeScore(phones[i], round(calibrate(ratio), 1),
                                       nframes, round(logpost, 3), round(ratio, 3)))

        word_scores = self._aggregate_words(scores, phonetics.get("words", []))
        overall = float(np.mean([s.score for s in scores])) if scores else 0.0
        return GopResult(scores, word_scores, round(overall, 1), round(dur, 3))

    @staticmethod
    def _aggregate_words(scores: list[PhonemeScore], words: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for w in words:
            start, length = w.get("start", 0), w.get("len", 0)
            seg = scores[start:start + length]
            if not seg:
                continue
            out.append({
                "phones": [s.phoneme for s in seg],
                "score": round(float(np.mean([s.score for s in seg])), 1),
                "weakest": min(seg, key=lambda s: s.score).phoneme,
            })
        return out
