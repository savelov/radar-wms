# token_utils.py
import time, hmac, hashlib, base64, json
try:
    import geoip2.database
except ImportError:
    geoip2 = None
import os

SECRET = b"**********************"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(BASE_DIR, "GeoLite2-Country.mmdb")

# Opened lazily and forgivingly.  The country check below is not switched on,
# but this module is now imported by vector_wms.wsgi as well, and a missing
# .mmdb raising at import time would take the phenomena layer down with it.
try:
    reader = geoip2.database.Reader(db_path)
except Exception as e:
    print("GEOIP unavailable:", e)
    reader = None

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

# ---------------------------------------------------------------------------
# Per-IP budget for /get_token
#
# A re-hosting proxy funnels all of its users through one egress address,
# while a real viewer is one tab on one address.  That is the only difference
# between them the server can see - referers and user agents are whatever the
# client says they are - so the budget is per client IP.
#
# The state has to be shared: mod_wsgi runs several daemon processes, and a
# counter held in one of them would let the same caller spend the budget
# again in each.  SQLite on tmpfs is the shared store; it is not the radar
# database, so a busy limiter cannot slow the WAL down, and it costs nothing
# on reboot because an empty budget file just means everyone starts full.
#
# Tune with the environment, not by editing this: WMS_TOKEN_BURST is how many
# tokens one address may take at once, WMS_TOKEN_PER_MIN how fast the budget
# refills.  demo.js asks for one token every 30 s, so a viewer sits at 2/min.
# ---------------------------------------------------------------------------

import sqlite3, threading

RATE_DB      = os.environ.get("WMS_TOKEN_RATE_DB", "/dev/shm/wms_token_rate.sqlite")
RATE_BURST   = float(os.environ.get("WMS_TOKEN_BURST", 60))
RATE_PER_MIN = float(os.environ.get("WMS_TOKEN_PER_MIN", 60))

_rate_lock = threading.Lock()
_rate_conn = None
_rate_calls = 0


def _rate_db():
    """The shared budget, opened once per process."""
    global _rate_conn
    if _rate_conn is None:
        # autocommit, so the BEGIN IMMEDIATE below is the only transaction
        # and it starts by taking the write lock rather than upgrading to it
        conn = sqlite3.connect(RATE_DB, timeout=5.0, check_same_thread=False,
                               isolation_level=None)
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("CREATE TABLE IF NOT EXISTS bucket ("
                     "ip TEXT PRIMARY KEY, tokens REAL NOT NULL, ts REAL NOT NULL)")
        conn.commit()
        _rate_conn = conn
    return _rate_conn


def allow_token_request(client_ip):
    """True if this address may mint another token right now.

    Fails open.  A limiter that cannot reach its own state must not be the
    thing that takes the WMS down, so every error here ends in True and a
    line in the error log.
    """
    global _rate_calls
    now = time.time()
    try:
        with _rate_lock:
            conn = _rate_db()
            # IMMEDIATE, not the default deferred transaction: reading the
            # balance and spending it has to be one atomic step.  Deferred,
            # every daemon process reads the same balance and every one of
            # them spends it, which hands out the budget once per process.
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute("SELECT tokens, ts FROM bucket WHERE ip=?",
                                   (client_ip,)).fetchone()
                if row is None:
                    tokens = RATE_BURST
                else:
                    # refill for the time that passed, never above the burst
                    tokens = min(RATE_BURST,
                                 row[0] + (now - row[1]) * RATE_PER_MIN / 60.0)

                allowed = tokens >= 1.0
                if allowed:
                    tokens -= 1.0

                conn.execute("INSERT INTO bucket (ip, tokens, ts) VALUES (?,?,?) "
                             "ON CONFLICT(ip) DO UPDATE SET tokens=?, ts=?",
                             (client_ip, tokens, now, tokens, now))

                # drop addresses that have been full for an hour, so the file
                # does not grow with every one-off visitor
                _rate_calls += 1
                if _rate_calls % 1000 == 0:
                    conn.execute("DELETE FROM bucket WHERE ts < ?", (now - 3600,))

                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

        if not allowed:
            print("TOKEN rate limit:", client_ip)
        return allowed

    except Exception as e:
        print("TOKEN rate limit unavailable:", e)
        return True
