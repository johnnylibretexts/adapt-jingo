"""JWS HS256 signing for the answerJWT. ADAPT verifies two ways:
  - JWTController::validateSignature uses hash_hmac('sha256', header.payload, secret)
  - JWTController::getPayload uses web-token Load::jss(['HS256']) with the same secret
PyJWT's HS256 uses the secret bytes directly as the HMAC key, matching both."""
import time
import jwt

ALG = "HS256"


def sign_answer_jwt(problem_jwt: str, score: dict, secret: str) -> str:
    payload = {
        "problemJWT": problem_jwt,
        "score": score,
        "iat": int(time.time()),
    }
    return jwt.encode(payload, secret, algorithm=ALG)