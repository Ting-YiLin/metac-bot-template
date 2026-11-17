"""Public-key sealed MiniBench queue. No plaintext forecasts in public Git history.

Private X25519 key is domain-separated from existing METACULUS_TOKEN using HKDF.
Work receives only the public key, never the token.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

VERSION=1
INFO=b"BTF3_MINIBENCH_QUEUE_X25519_PRIVATE_V1"
AAD=b"BTF3_MINIBENCH_SCORING_FORECAST_V1"

def b64(x:bytes)->str:
    return base64.b64encode(x).decode("ascii")
def unb64(x:str)->bytes:
    return base64.b64decode(x,validate=True)
def pubbytes(key):
    return key.public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
def private_from_token(token:str):
    if not isinstance(token,str) or len(token)<20:
        raise ValueError("TOKEN_MISSING_OR_TOO_SHORT")
    seed=HKDF(algorithm=hashes.SHA256(),length=32,salt=b"BTF3_WORK_QUEUE_V1",
              info=INFO).derive(token.encode("utf-8"))
    return x25519.X25519PrivateKey.from_private_bytes(seed)
def public_document(token):
    key=private_from_token(token).public_key()
    raw=pubbytes(key)
    return {"version":VERSION,"scheme":"X25519-HKDF-SHA256-AES256GCM",
            "public_key_base64":b64(raw),
            "public_key_id":hashlib.sha256(raw).hexdigest()[:20],
            "scope":"MINIBENCH_WORK_FORECAST_ENCRYPTION_ONLY",
            "note":"Public encryption key; cannot submit a forecast"}
def seal(payload:dict,public_doc:dict)->dict:
    if public_doc.get("version")!=VERSION or public_doc.get("scope")!="MINIBENCH_WORK_FORECAST_ENCRYPTION_ONLY":
        raise ValueError("INVALID_PUBLIC_DOC")
    raw=unb64(public_doc["public_key_base64"])
    if hashlib.sha256(raw).hexdigest()[:20]!=public_doc.get("public_key_id"):
        raise ValueError("PUBLIC_KEY_ID_MISMATCH")
    receiver=x25519.X25519PublicKey.from_public_bytes(raw)
    ephemeral=x25519.X25519PrivateKey.generate()
    ep=pubbytes(ephemeral.public_key())
    secret=ephemeral.exchange(receiver)
    key=HKDF(algorithm=hashes.SHA256(),length=32,salt=b"BTF3_EPH_V1",
             info=AAD+ep+raw).derive(secret)
    nonce=os.urandom(12)
    plaintext=json.dumps(payload,ensure_ascii=False,separators=(",",":")).encode("utf-8")
    if len(plaintext)>40000: raise ValueError("PAYLOAD_TOO_LARGE")
    ciphertext=AESGCM(key).encrypt(nonce,plaintext,AAD)
    return {"version":VERSION,"key_id":public_doc["public_key_id"],
            "ephemeral_pub":b64(ep),"nonce":b64(nonce),"ciphertext":b64(ciphertext)}
def unseal(envelope:dict,token:str)->dict:
    if not isinstance(envelope,dict) or set(envelope)!={"version","key_id","ephemeral_pub","nonce","ciphertext"} or envelope["version"]!=VERSION:
        raise ValueError("INVALID_ENVELOPE")
    priv=private_from_token(token)
    raw=pubbytes(priv.public_key())
    if hashlib.sha256(raw).hexdigest()[:20]!=envelope["key_id"]:
        raise ValueError("QUEUE_KEY_ROTATED")
    ep=unb64(envelope["ephemeral_pub"])
    nonce=unb64(envelope["nonce"])
    ciphertext=unb64(envelope["ciphertext"])
    if len(ep)!=32 or len(nonce)!=12 or not (16<len(ciphertext)<60000):
        raise ValueError("BAD_CIPHERTEXT_DIMENSIONS")
    other=x25519.X25519PublicKey.from_public_bytes(ep)
    secret=priv.exchange(other)
    key=HKDF(algorithm=hashes.SHA256(),length=32,salt=b"BTF3_EPH_V1",
             info=AAD+ep+raw).derive(secret)
    return json.loads(AESGCM(key).decrypt(nonce,ciphertext,AAD))

def main():
    p=argparse.ArgumentParser()
    p.add_argument("command",choices=["public","encrypt","decrypt"])
    p.add_argument("--public",dest="public_path")
    p.add_argument("--input")
    p.add_argument("--output",required=True)
    a=p.parse_args()
    if a.command=="public":
        data=public_document(os.environ.get("METACULUS_TOKEN",""))
    elif a.command=="encrypt":
        data=seal(json.loads(Path(a.input).read_text(encoding="utf-8")),
                  json.loads(Path(a.public_path).read_text(encoding="utf-8")))
    else:
        data=unseal(json.loads(Path(a.input).read_text(encoding="utf-8")),
                    os.environ.get("METACULUS_TOKEN",""))
    Path(a.output).write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("SEALED_QUEUE_OPERATION_SUCCESS" if a.command!="decrypt" else "QUEUE_DECRYPTED_TO_PRIVATE_WORKSPACE")

if __name__=="__main__":main()
