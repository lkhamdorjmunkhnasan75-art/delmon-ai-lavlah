"""Synthetic issuer only. No network, discovery, real OIDC or production key."""
import base64
import hashlib
import hmac
import json
import os
import re
import time
from uuid import UUID

ISSUER="https://identity.example.test"
AUDIENCE="delmon-lavlah-pilot"

def decode(part):
    if not re.fullmatch(r"[A-Za-z0-9_-]+",part):
        raise ValueError("Invalid token")
    data=base64.urlsafe_b64decode(part+"="*((-len(part))%4))
    if base64.urlsafe_b64encode(data).decode().rstrip("=")!=part:
        raise ValueError("Invalid token")
    return data

def unique_object(pairs):
    result={}
    for k,v in pairs:
        if k in result:raise ValueError("Duplicate claim")
        result[k]=v
    return result

def validate(token,key,now=None):
    if not isinstance(key,bytes) or len(key)<32 or not isinstance(token,str) or len(token)>4096:
        raise ValueError("Invalid token")
    try:
        a,b,c=token.split(".")
        signature=decode(c)
        if not hmac.compare_digest(signature,hmac.digest(key,(a+"."+b).encode("ascii"),"sha256")):
            raise ValueError("Invalid signature")
        header=json.loads(decode(a),object_pairs_hook=unique_object)
        claims=json.loads(decode(b),object_pairs_hook=unique_object)
        if header!={"alg":"HS256","typ":"JWT"} or not isinstance(claims,dict):
            raise ValueError("Invalid header")
        if set(claims)!={"iss","aud","sub","iat","exp","jti"} or claims["iss"]!=ISSUER or claims["aud"]!=AUDIENCE:
            raise ValueError("Invalid claims")
        now=int(time.time()) if now is None else now
        iat,exp=claims["iat"],claims["exp"]
        if type(iat) is not int or type(exp) is not int or not iat<=now<exp or not 0<exp-iat<=300:
            raise ValueError("Expired or invalid lifetime")
        if not isinstance(claims["sub"],str) or not re.fullmatch(r"synthetic-pilot-[12]",claims["sub"]):
            raise ValueError("Invalid subject")
        if str(UUID(claims["jti"]))!=claims["jti"]:raise ValueError("Invalid jti")
        return claims
    except (ValueError,TypeError,KeyError,AttributeError,UnicodeError,OverflowError):
        raise ValueError("Invalid synthetic identity") from None

def configured_key():
    if os.getenv("LAVLAH_ENV")!="pilot" or os.getenv("LAVLAH_PILOT_ONLY")!="1":
        raise ValueError("Synthetic issuer disabled")
    try:return bytes.fromhex(os.environ["LAVLAH_SYNTHETIC_KEY"])
    except (KeyError,ValueError):raise ValueError("Synthetic issuer disabled") from None
