"""jingo — thin FastAPI pronunciation-scoring adapter around jingo_engine.

Engine purity: this file is the only place that imports jingo_engine + the
app glue modules; jingo_engine itself stays framework-free. The engine is
constructed lazily so tests can monkeypatch `_engine` without installing
ctranslate2."""
import logging
import os
import time
from collections import defaultdict

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import config
from .provider import JsonPhoneticsProvider
from .jwt_util import sign_answer_jwt
from .audio import download_and_normalize, normalize_upload

logger = logging.getLogger("jingo")
logging.basicConfig(level=logging.INFO)

_provider = JsonPhoneticsProvider(records_dir=config.RECORDS_DIR)


def _build_engine():
    """Construct the real engine lazily. Returns None if unavailable."""
    try:
        from jingo_engine import Engine, EngineConfig
    except Exception as exc:  # pragma: no cover - deployment-only path
        logger.error("jingo_engine import failed: %s", exc)
        return None
    eng = Engine(EngineConfig(model_dir=config.MODEL_DIR))
    return eng if eng.available else None


_engine = _build_engine()


class ScoreRequest(BaseModel):
    problemJWT: str
    exercise_id: str
    language: str
    audio_url: str


app = FastAPI(title="jingo pronunciation scorer", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.ALLOWED_ORIGIN],
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["*"],
)

# Sliding-window per-client rate limit for the unauthenticated practice
# endpoint. Process-local (assumes a single uvicorn worker for the POC).
_practice_hits = defaultdict(list)
_MAX_TRACKED_IPS = 4096


def _client_ip(request: Request) -> str:
    # Trust the rightmost X-Forwarded-For entry — the hop added by our own
    # single, trusted Caddy reverse proxy — so the limit is keyed on the real
    # client, not the proxy's loopback address. Falls back to the socket peer
    # when the header is absent (direct/local access). Assumes exactly one
    # trusted proxy in front; revisit if the topology gains hops.
    xff = request.headers.get("x-forwarded-for")
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return request.client.host if request.client else "unknown"


def _practice_rate_limit(request: Request) -> None:
    now = time.time()
    ip = _client_ip(request)
    window, limit = config.PRACTICE_RATE_WINDOW_S, config.PRACTICE_RATE_MAX
    # Bound memory: evict stale/empty buckets so distinct source IPs can't
    # accumulate without limit over long uptime.
    if len(_practice_hits) > _MAX_TRACKED_IPS:
        for k in [k for k, v in list(_practice_hits.items())
                  if not v or now - v[-1] >= window]:
            del _practice_hits[k]
    hits = [t for t in _practice_hits.get(ip, ()) if now - t < window]
    if len(hits) >= limit:
        raise HTTPException(status_code=429, detail="Too many attempts; slow down.")
    hits.append(now)
    _practice_hits[ip] = hits


def _score_payload(req: ScoreRequest, status: str, *, overall=None,
                  weak_tags=None, duration_s=None) -> dict:
    return {
        "status": status,
        "overall": overall,
        "weak_tags": weak_tags or [],
        "provisional": True,
        "duration_s": duration_s,
        "exercise_id": req.exercise_id,
        "language": req.language,
    }


def _completion_answer(req: ScoreRequest, status: str) -> dict:
    score = _score_payload(req, status)
    return {"answerJWT": sign_answer_jwt(req.problemJWT, score, config.JWT_SECRET),
            "feedback": score}


def _trim_phonemes(phoneme_scores) -> list:
    """Slim the engine's per-phoneme scores down to what the UI chips need."""
    trimmed = []
    for ps in phoneme_scores or []:
        unc = ps.get("uncertainty") or {}
        trimmed.append({
            "phoneme": ps.get("phoneme"),
            "score": ps.get("score"),
            "tag": ps.get("tag"),
            "reliable": ps.get("reliable", True),
            "abstain": bool(ps.get("abstain") or unc.get("abstain")),
            "band": unc.get("band"),
        })
    return trimmed


def _word_spans(record) -> list:
    """Per-word spans (text + phone range into the flat phoneme_scores list) so
    the UI can roll the per-sound scores up to real words. Emitted only when the
    record carries word text for every span (see authoring/gen_word_records.py);
    otherwise empty and the UI shows the flat per-sound view."""
    words = (record or {}).get("words") or []
    if not words or not all(w.get("text") for w in words):
        return []
    return [{"text": w["text"], "start": w.get("start"), "len": w.get("len")}
            for w in words]


@app.get("/health")
def health():
    return {"engine_available": _engine is not None,
            "model_dir": config.MODEL_DIR,
            "records_dir": config.RECORDS_DIR,
            "contract": "1.1"}


@app.post("/score")
def score(req: ScoreRequest):
    if _engine is None:
        return _completion_answer(req, "engine_unavailable")
    record = _provider.get(req.language, req.exercise_id)
    if record is None:
        return _completion_answer(req, "provider_miss")
    wav_path = None
    try:
        try:
            wav_path = download_and_normalize(req.audio_url, "/tmp/jingo")
        except Exception as exc:
            logger.info("audio unreachable: %s", exc)
            return _completion_answer(req, "audio_unreachable")
        try:
            payload = _engine.score_exercise(wav_path, req.language, req.exercise_id, _provider)
        except (ValueError, RuntimeError) as exc:
            logger.info("unscoreable: %s", exc)
            return _completion_answer(req, "unscoreable")
        if payload is None:
            return _completion_answer(req, "provider_miss")
        score = _score_payload(
            req, "scored",
            overall=payload.get("overall"),
            weak_tags=payload.get("weak_tags", []),
            duration_s=payload.get("duration_s"),
        )
        # Sign only the minimal score (gradebook integrity); return a richer feedback
        # object with the per-phoneme breakdown for the student UI (display-only).
        feedback = dict(score)
        feedback["phoneme_scores"] = _trim_phonemes(payload.get("phoneme_scores"))
        feedback["words"] = _word_spans(record)
        return {"answerJWT": sign_answer_jwt(req.problemJWT, score, config.JWT_SECRET),
                "feedback": feedback}
    finally:
        if wav_path and os.path.exists(wav_path):
            os.remove(wav_path)


@app.post("/practice-score")
async def practice_score(
    request: Request,
    audio: UploadFile = File(...),
    exercise_id: str = Form(...),
    language: str = Form(...),
):
    """Ungraded practice: score inline audio against exercise_id and return the
    per-phoneme feedback ONLY (no answerJWT, no gradebook, no stored audio)."""
    _practice_rate_limit(request)
    if _engine is None:
        raise HTTPException(status_code=503, detail="engine unavailable")
    record = _provider.get(language, exercise_id)
    if record is None:
        raise HTTPException(status_code=404, detail="unknown exercise")
    data = await audio.read(config.MAX_UPLOAD_BYTES + 1)
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="audio too large")
    wav_path = None
    try:
        try:
            wav_path = normalize_upload(data, "/tmp/jingo", config.MAX_AUDIO_SECONDS)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        try:
            payload = _engine.score_exercise(wav_path, language, exercise_id, _provider)
        except (ValueError, RuntimeError):
            raise HTTPException(status_code=422, detail="unscoreable")
        if payload is None:
            raise HTTPException(status_code=404, detail="unknown exercise")
        return {
            "status": "scored",
            "overall": payload.get("overall"),
            "weak_tags": payload.get("weak_tags", []),
            "provisional": True,
            "phoneme_scores": _trim_phonemes(payload.get("phoneme_scores")),
            "words": _word_spans(record),
            "exercise_id": exercise_id,
            "language": language,
        }
    finally:
        if wav_path and os.path.exists(wav_path):
            os.remove(wav_path)