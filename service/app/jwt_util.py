"""JWS HS256 signing for the answerJWT. ADAPT verifies two ways:
  - JWTController::validateSignature uses hash_hmac('sha256', header.payload, secret)
  - JWTController::getPayload uses web-token Load::jss(['HS256']) with the same secret
PyJWT's HS256 uses the secret bytes directly as the HMAC key, matching both."""
import os
import time
import jwt

ALG = "HS256"

# Generous default: gradeback happens immediately after scoring, so a 1hr
# TTL cannot break the normal flow. Overridable per-deploy.
DEFAULT_TTL_SECONDS = 3600


def sign_answer_jwt(problem_jwt: str, score: dict, secret: str, now: int = None) -> str:
    if now is None:
        now = int(time.time())
    ttl = int(os.environ.get("JINGO_ANSWER_JWT_TTL_SECONDS", str(DEFAULT_TTL_SECONDS)))
    payload = {
        "problemJWT": problem_jwt,
        "score": score,
        "iat": now,
        "exp": now + ttl,
    }
    return jwt.encode(payload, secret, algorithm=ALG)