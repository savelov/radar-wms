# token_utils.py
import time, hmac, hashlib, base64, json
import geoip2.database
import os

SECRET = b"**********************"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(BASE_DIR, "GeoLite2-Country.mmdb")
reader = geoip2.database.Reader(db_path)

ALLOWED = {"RU", "BY", "KZ", "UA", "PL", "EE", "LT", "LV", "GE"}

def is_allowed_country(ip):
    try:
        response = reader.country(ip)
        return response.country.iso_code in ALLOWED
    except:
        return False

def generate_token(client_ip):
    payload = {
        "exp": int(time.time()) + 60,  # valid 60 seconds
        "ip": client_ip
    }

    raw = json.dumps(payload, separators=(",", ":")).encode()
    sig = hmac.new(SECRET, raw, hashlib.sha256).digest()

    raw_b64 = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")

    return f"{raw_b64}.{sig_b64}"


def validate_token(token, client_ip):
    try:
        raw_b64, sig_b64 = token.split(".")

        raw = base64.urlsafe_b64decode(raw_b64 + "===")
        sig = base64.urlsafe_b64decode(sig_b64 + "===")

        expected_sig = hmac.new(SECRET, raw, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected_sig):
            return False

        payload = json.loads(raw.decode())

        if payload["exp"] < time.time():
            return False

        if payload["ip"] != client_ip:
            print("TOKEN ip not matched:", payload["ip"])
#            return False

#        if not is_allowed_country(client_ip):
#            return False

        return True

    except Exception as e:
        print("TOKEN ERROR:", e)
        return False