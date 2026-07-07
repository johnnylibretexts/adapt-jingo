import time
import jwt
import pytest
from app.jwt_util import sign_answer_jwt


def test_sign_answer_jwt_is_hs256_and_round_trips():
    secret = "shared-webwork-secret"
    token = sign_answer_jwt("opaque-problem-jwt", {"status": "scored", "overall": 86.4}, secret)
    header = jwt.get_unverified_header(token)
    assert header["alg"] == "HS256"
    payload = jwt.decode(token, secret, algorithms=["HS256"])
    assert payload["problemJWT"] == "opaque-problem-jwt"
    assert payload["score"]["overall"] == 86.4
    assert payload["score"]["status"] == "scored"


def test_sign_answer_jwt_rejects_wrong_secret():
    token = sign_answer_jwt("p", {"status": "scored"}, "right-secret")
    try:
        jwt.decode(token, "wrong-secret", algorithms=["HS256"])
        assert False, "should have raised"
    except jwt.InvalidSignatureError:
        pass


def test_sign_answer_jwt_includes_exp_after_iat_default_ttl():
    now = 1_000_000
    token = sign_answer_jwt("opaque-problem-jwt", {"status": "scored"}, "secret", now=now)
    # now is far in the past on the wall clock -- skip exp verification here,
    # we're only inspecting the claim values, not testing expiry enforcement.
    payload = jwt.decode(token, "secret", algorithms=["HS256"], options={"verify_exp": False})
    assert payload["iat"] == now
    assert payload["exp"] == now + 3600  # default JINGO_ANSWER_JWT_TTL_SECONDS
    assert payload["exp"] > payload["iat"]


def test_sign_answer_jwt_respects_ttl_env_and_expires(monkeypatch):
    monkeypatch.setenv("JINGO_ANSWER_JWT_TTL_SECONDS", "1")
    now = int(time.time()) - 10  # already 10s in the past relative to "now"
    token = sign_answer_jwt("p", {"status": "scored"}, "secret", now=now)
    unverified = jwt.decode(token, "secret", algorithms=["HS256"], options={"verify_exp": False})
    assert unverified["exp"] == now + 1

    with pytest.raises(jwt.ExpiredSignatureError):
        jwt.decode(token, "secret", algorithms=["HS256"])