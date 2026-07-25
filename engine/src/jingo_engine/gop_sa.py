"""EXPERIMENTAL: CTC self-alignment (SA) and alignment-free (AF) GOP modes.

Motivation (research report, Decision 3): CTC-posterior GOP beats
forced-alignment GOP across multiple studies (GOP-SA AUC 0.905 and fully
alignment-free 0.914 vs a 0.796 forced-alignment baseline in arXiv 2507.16838;
NOCASA-2025 winner was alignment-free CTC GOP). Our production scorer already
*aligns* with the CTC model itself, so the remaining gaps are:

- **SA** — score on the *soft* forward-backward occupancy instead of the
  one-best Viterbi path: each phone's competitor ratio is weighted over every
  frame the lattice says the phone plausibly occupies, attacking the
  single-frame peakiness (~95% of phones currently scored on one 20 ms frame).
- **AF** — marginalized substitution scoring: the phone's score is the
  full-sequence CTC log-likelihood drop when the phone is replaced by a
  wildcard ("any non-blank token"), normalized by expected duration. This is
  the *unrestricted-substitution* alignment-free variant (the strongest in
  Parikh 2025), computed with a batched forward pass per utterance.

Approximation note (AF): the wildcard keeps the original lattice's
same-label skip rules; a substitution that would collide with a neighboring
identical label is not re-derived. Rare and benign for es/fr sequences.

This module deliberately does NOT change GopScorer or the public contract —
production stays on Viterbi until the harness evaluation picks a winner
(shadow-before-switch). Use :class:`ModeScorer` to get per-phone raw ratios
for all three modes in one pass.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .gop import BLANK_ID, GopScorer, min_ctc_frames

_NEG = -1e30


def _ext_and_skip(ids: list[int]) -> tuple[np.ndarray, np.ndarray]:
    ext = [BLANK_ID]
    for p in ids:
        ext += [p, BLANK_ID]
    ext_arr = np.asarray(ext, dtype=np.int64)
    allow_skip = np.zeros(len(ext_arr), dtype=bool)
    allow_skip[2:] = (ext_arr[2:] != BLANK_ID) & (ext_arr[2:] != ext_arr[:-2])
    return ext_arr, allow_skip


def _logsumexp3(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> np.ndarray:
    m = np.maximum(a, np.maximum(b, c))
    m_safe = np.where(m <= _NEG, 0.0, m)
    with np.errstate(divide="ignore"):
        out = m + np.log(np.exp(a - m_safe) + np.exp(b - m_safe) + np.exp(c - m_safe))
    return np.where(m <= _NEG, _NEG, out)


def ctc_forward(emis: np.ndarray, allow_skip: np.ndarray) -> tuple[np.ndarray, float]:
    """Log-space CTC forward over pre-built extended emissions (T x L).

    Supports batching: ``emis`` may be (N, T, L) with a shared ``allow_skip``;
    returns (alpha, logZ) with matching leading dims.
    """
    batched = emis.ndim == 3
    if not batched:
        emis = emis[None]
    N, T, L = emis.shape
    alpha = np.full((N, T, L), _NEG)
    alpha[:, 0, 0] = emis[:, 0, 0]
    if L > 1:
        alpha[:, 0, 1] = emis[:, 0, 1]
    for t in range(1, T):
        prev = alpha[:, t - 1]
        s1 = np.concatenate((np.full((N, 1), _NEG), prev[:, :-1]), axis=1)
        s2 = np.concatenate((np.full((N, 2), _NEG), prev[:, :-2]), axis=1)
        s2 = np.where(allow_skip[None, :], s2, _NEG)
        alpha[:, t] = emis[:, t] + _logsumexp3(prev, s1, s2)
    tail = alpha[:, T - 1, L - 1]
    if L > 1:
        m = np.maximum(tail, alpha[:, T - 1, L - 2])
        tail = m + np.log(np.exp(tail - m) + np.exp(alpha[:, T - 1, L - 2] - m))
    if not batched:
        return alpha[0], float(tail[0])
    return alpha, tail


def ctc_backward(emis: np.ndarray, allow_skip: np.ndarray) -> np.ndarray:
    """Log-space CTC backward: beta[t, l] = mass of suffix paths *after* t
    (emission at t excluded), so alpha + beta - logZ is the occupancy."""
    T, L = emis.shape
    beta = np.full((T, L), _NEG)
    beta[T - 1, L - 1] = 0.0
    if L > 1:
        beta[T - 1, L - 2] = 0.0
    for t in range(T - 2, -1, -1):
        nxt = beta[t + 1] + emis[t + 1]
        s1 = np.concatenate((nxt[1:], [_NEG]))
        s2 = np.concatenate((nxt[2:], [_NEG, _NEG]))
        allow2 = np.concatenate((allow_skip[2:], [False, False]))
        s2 = np.where(allow2, s2, _NEG)
        beta[t] = _logsumexp3(nxt, s1, s2)
    return beta


@dataclass
class ModeRatios:
    """Per-phone raw GOP ratios (<=0; 0 = perfect) under each scoring mode."""

    phones: list[str]
    viterbi: list[float]
    sa: list[float]
    af: list[float]
    duration_s: float


class ModeScorer:
    """Wraps a production GopScorer to emit raw ratios for all modes at once."""

    def __init__(self, scorer: GopScorer) -> None:
        self._s = scorer

    def ratios(self, wav_path: str, phonetics: dict) -> ModeRatios:
        ids: list[int] = phonetics["ids"]
        phones: list[str] = phonetics["phones"]
        if not ids:
            raise ValueError("phonetics record has no phone ids")
        logp, dur = self._s._frame_logprobs(wav_path)
        T = logp.shape[0]
        if T < min_ctc_frames(ids):
            raise ValueError(f"audio too short to align: {T} frames for {len(ids)} phones")

        ext, allow_skip = _ext_and_skip(ids)
        L = len(ext)
        per_frame_max = logp.max(-1)
        # non-blank wildcard for AF substitution
        nonblank = np.delete(logp, BLANK_ID, axis=1)
        wild = nonblank.max(-1)

        # group-merged log-probs per unique phone id (consistent with production)
        plp_by_id = {pid: self._s._phone_logp(logp, pid) for pid in set(ids)}

        # extended emissions (T x L): blanks from logp, phones from group logp
        emis = np.empty((T, L))
        emis[:, 0::2] = logp[:, BLANK_ID][:, None]
        for k, pid in enumerate(ids):
            emis[:, 2 * k + 1] = plp_by_id[pid]

        # ---- Viterbi baseline (identical math to production) -------------- #
        frame_phone = self._s._ctc_align(logp, ids)
        vit: list[float] = []
        for i, pid in enumerate(ids):
            frames = np.where(frame_phone == i)[0]
            if len(frames) == 0:
                vit.append(float("-inf"))
            else:
                vit.append(float((plp_by_id[pid][frames] - per_frame_max[frames]).mean()))

        # ---- SA: occupancy-weighted competitor ratio ----------------------- #
        alpha, logZ = ctc_forward(emis, allow_skip)
        beta = ctc_backward(emis, allow_skip)
        gamma = alpha + beta - logZ  # log occupancy per (t, l)
        sa: list[float] = []
        occ_mass: list[float] = []
        for i, pid in enumerate(ids):
            w = np.exp(np.clip(gamma[:, 2 * i + 1], -60.0, 0.0))
            mass = float(w.sum())
            occ_mass.append(mass)
            if mass < 1e-6:
                sa.append(float("-inf"))
            else:
                sa.append(float(((plp_by_id[pid] - per_frame_max) * w).sum() / mass))

        # ---- AF: batched wildcard-substitution likelihood ratio ------------ #
        N = len(ids)
        emis_batch = np.broadcast_to(emis, (N, T, L)).copy()
        for i in range(N):
            emis_batch[i, :, 2 * i + 1] = wild
        _, logZ_wild = ctc_forward(emis_batch, allow_skip)
        af = [
            float(min(0.0, logZ - float(logZ_wild[i])) / max(1.0, occ_mass[i]))
            for i in range(N)
        ]

        return ModeRatios(phones, vit, sa, af, round(dur, 3))
