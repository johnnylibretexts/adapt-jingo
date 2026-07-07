import jwt
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