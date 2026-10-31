#!/usr/bin/env python3
"""Captive-portal watchdog for a flaky public hotspot.

Every pass (systemd timer, ~3 min):
  1. probe real internet (generate_204)
  2. classify the portal state via wifi_login.py --status:
       STATE:online        -> hart behind the portal, all good
       STATE:login-needed  -> gateway captive-redirects (device unauthenticated)
       STATE:blocked       -> gateway not reachable at all (hotspot/L2 hiccup)
3. act:
        login-needed -> re-login with the stored voucher code from code.txt
        blocked      -> stay quiet; after ROTATE_AFTER_BLOCKED consecutive
                        blocked passes, rotate the WiFi MAC for a fresh lease
  4. notify any state change over Telegram (if configured).

Single code reuse policy: the one voucher in code.txt is reused for every
unauthenticated pass until the portal rejects it. On rejection the watchdog
rotates the MAC after ROTATE_AFTER_LOGIN_FAIL consecutive failures (a project
voucher is often bound per-device, so a fresh MAC can still consume it), and
if that keeps failing it stops churning identity, notifies 'NEED VOUCHER CODE',
and waits — drop a fresh code into code.txt whenever it arrives.

MAC rotation: implemented below (get_default_iface / rotate_mac). It only ever
touches a Wi-Fi-like default interface (wlan*/wlp*/wlx*/wlo*), never a wired
one, and falls back to re-applying DHCP (dhclient, else nmcli) after the swap.
"""
import json
import os
import re
import secrets
import subprocess
import sys
from datetime import datetime

BASE = os.environ.get("WIFI_WATCHDOG_HOME") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
WDIR = os.path.join(BASE, "watchdog")


def _default_python():
    candidates = [
        os.path.join(BASE, "plenv", "bin", "python"),
        os.path.join(BASE, ".venv", "Scripts", "python.exe"),
        os.path.join(BASE, "venv", "Scripts", "python.exe"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return sys.executable


PY = os.environ.get("WIFI_WATCHDOG_PYTHON") or _default_python()
WIFI_LOGIN = os.path.join(BASE, "wifi_login.py")
LOGFILE = os.path.join(WDIR, "watchdog.log")
STATE_FILE = os.path.join(WDIR, "state.json")
CODE_FILE = os.path.join(WDIR, "code.txt")
TG_FILE = os.path.join(WDIR, "telegram.conf")

PROBE_URL = "https://www.google.com/generate_204"

PROBE_TIMEOUT = 10
STATUS_TIMEOUT = 110   # wifi_login --status worst case
LOGIN_TIMEOUT = 180    # wifi_login --code worst case

ROTATE_AFTER_BLOCKED = 3       # consecutive unreachable passes before rotating
ROTATE_AFTER_LOGIN_FAIL = 2    # consecutive voucher rejections before rotating
WIFI_PREFIXES = ("wlan", "wlp", "wlx", "wlo")


def log(msg):
    line = f"{datetime.now().isoformat()} {msg}"
    try:
        with open(LOGFILE, "a") as fh:
            fh.write(line + "\n")
    except Exception:
        pass
    print(line, file=sys.stderr, flush=True)


def run(cmd, timeout, env=None):
    """Run a command, return (rc, stdout, stderr)."""
    e = dict(os.environ)
    bundled = os.path.join(BASE, "ms-playwright")
    if os.path.isdir(bundled):
        e.setdefault("PLAYWRIGHT_BROWSERS_PATH", bundled)
    if env:
        e.update(env)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=e)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return -9, "", "timeout expired"
    except Exception as exc:
        return -1, "", str(exc)


def load_state():
    try:
        with open(STATE_FILE) as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_state(st):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(st, fh)
    os.replace(tmp, STATE_FILE)


def get_code():
    try:
        with open(CODE_FILE) as fh:
            for ln in fh:
                ln = ln.strip()
                if ln:
                    return ln
        return ""
    except Exception:
        return ""


def tg_send(text):
    tok = chat = ""
    try:
        with open(TG_FILE) as fh:
            for ln in fh:
                ln = ln.strip()
                if ln.startswith("TOKEN="):
                    tok = ln[6:]
                elif ln.startswith("CHAT="):
                    chat = ln[5:]
    except Exception:
        return False
    if not tok or not chat:
        return False
    rc, _, _ = run(["curl", "-s", "-m", "10",
                    "-F", f"chat_id={chat}",
                    "-F", f"text={text}",
                    f"https://api.telegram.org/bot{tok}/sendMessage"], 15)
    return rc == 0


def maybe_notify(st, text, force=False):
    cur = f"{datetime.now():%Y-%m-%d %H:%M}"
    if not force and st.get("event") == text:
        return
    st["event"] = text
    tg_send(f"[{cur}] {text}")


def probe():
    rc, so, _ = run(["curl", "-s", "-m", str(PROBE_TIMEOUT), "-o", os.devnull,
                     "-w", "%{http_code}", PROBE_URL], PROBE_TIMEOUT + 5)
    return rc == 0 and so.strip() in ("200", "204")


def classify():
    """Run wifi_login.py --status; return online|login-needed|blocked."""
    rc, so, _ = run([PY, WIFI_LOGIN, "--status"], STATUS_TIMEOUT)
    for ln in so.splitlines():
        if ln.startswith("STATE:"):
            return ln.split(":", 1)[1].strip()
    return "blocked" if rc != 0 else "unknown"


def try_login():
    code = get_code()
    if not code:
        return "no-code"
    rc, so, _ = run([PY, WIFI_LOGIN, "--code", code], LOGIN_TIMEOUT)
    for ln in so.splitlines():
        if ln.startswith("STATE:"):
            return ln.split(":", 1)[1].strip()
    return "failed" if rc != 0 else "unknown"


def get_default_iface():
    """Default-route interface name, or '' if there is none."""
    rc, so, _ = run(["ip", "route", "show", "default"], 10)
    if rc == 0:
        m = re.search(r"\bdev\s+(\S+)", so)
        if m:
            return m.group(1)
    return ""


def gen_mac():
    bites = bytearray(secrets.token_bytes(6))
    bites[0] = (bites[0] & 0xFE) | 0x02   # locally administered, unicast
    return ":".join(f"{b:02x}" for b in bites)


def _refresh_lease(iface):
    """Try dhclient first, then NetworkManager, to pick up a new lease."""
    rc, _, _ = run(["ip", "link", "set", iface, "up"], 20)
    run(["sleep", "5"], 10)
    rc, _, _ = run(["command", "-v", "dhclient"], 5)
    if rc == 0:
        run(["dhclient", "-4", "-pf", f"/run/dhclient.{iface}.pid", iface], 30)
        return
    rc, _, _ = run(["command", "-v", "nmcli"], 5)
    if rc == 0:
        run(["nmcli", "device", "reapply", iface], 30)


def rotate_mac(dry_run=False):
    """Swap the Wi-Fi MAC for a fresh one; returns the new MAC or ''."""
    iface = get_default_iface()
    if not iface or not iface.startswith(WIFI_PREFIXES):
        log(f"rotate: skipped, default iface {iface!r} is not Wi-Fi")
        return ""
    new = gen_mac()
    if dry_run:
        log(f"rotate: [dry] would set {iface} -> {new}")
        return new
    for step in (["ip", "link", "set", iface, "down"],
                 ["ip", "link", "set", iface, "address", new],
                 ["ip", "link", "set", iface, "up"]):
        rc, _, err = run(step, 20)
        if rc != 0:
            log(f"rotate: step failed {' '.join(step)} -> {err.strip() or rc}")
            return ""
    _refresh_lease(iface)
    log(f"rotate: {iface} -> {new}")
    return new


def do_pass(st):
    if probe():
        st["last_state"] = "online"
        st["blocked_streak"] = 0
        st["login_fail_streak"] = 0
        save_state(st)
        log("probe: ONLINE")
        if st.get("prev_online") is not True:
            maybe_notify(st, "ONLINE (internet reachable)", force=True)
        st["prev_online"] = True
        save_state(st)
        return 0

    st["prev_online"] = False
    save_state(st)
    log("probe: offline, classifying portal state")
    state = classify()
    st["last_state"] = state
    save_state(st)
    log(f"classify: STATE={state}")

    if state == "login-needed":
        st["blocked_streak"] = 0
        save_state(st)
        res = try_login()
        log(f"login result: {res}")
        if res == "online":
            st["login_fail_streak"] = 0
            save_state(st)
            maybe_notify(st, "LOGGED IN - internet restored", force=True)
            return 0
        if res == "no-code":
            maybe_notify(st, "NEED VOUCHER CODE (portal reachable, code.txt empty)")
            return 2
        if res == "login-failed":
            st["login_fail_streak"] = st.get("login_fail_streak", 0) + 1
            save_state(st)
            if st["login_fail_streak"] >= ROTATE_AFTER_LOGIN_FAIL:
                newmac = rotate_mac()
                if newmac:
                    st["login_fail_streak"] = 0
                    save_state(st)
                    maybe_notify(st,
                        f"LOGIN REJECTED - rotated MAC to {newmac}, will retry")
                else:
                    maybe_notify(st, "LOGIN REJECTED - voucher looks exhausted; need fresh code")
            else:
                maybe_notify(st, f"LOGIN REJECTED (attempt {st['login_fail_streak']}) - will retry")
            return 2
        maybe_notify(st, f"LOGIN UNCERTAIN ({res}) - will retry")
        return 1

    if state == "blocked":
        st["login_fail_streak"] = 0
        st["blocked_streak"] = st.get("blocked_streak", 0) + 1
        save_state(st)
        if st["blocked_streak"] >= ROTATE_AFTER_BLOCKED:
            newmac = rotate_mac()
            if newmac:
                st["blocked_streak"] = 0
                save_state(st)
                maybe_notify(st, f"GATEWAY UNREACHABLE - rotated MAC to {newmac}")
            else:
                log("rotate: no Wi-Fi iface available; keeping blocked streak")
        else:
            log(f"gateway unreachable this pass (streak {st['blocked_streak']}/{ROTATE_AFTER_BLOCKED}); will retry next cycle")
        return 0

    log("unknown portal state; will retry")
    return 1


def main():
    import argparse
    ap = argparse.ArgumentParser(description="captive-portal watchdog (login retry)")
    ap.add_argument("--run", action="store_true", help="single full pass (timer)")
    ap.add_argument("--probe", action="store_true", help="just curl the generator")
    ap.add_argument("--status", action="store_true", help="just classify portal state")
    ap.add_argument("--login-test", action="store_true",
                    help="force one login attempt with the stored code")
    ap.add_argument("--dry-rotate", action="store_true",
                    help="show which iface/MAC rotation would use (no change)")
    ap.add_argument("--test-telegram", action="store_true", help="send a test message")
    args = ap.parse_args()

    os.makedirs(WDIR, exist_ok=True)

    if args.test_telegram:
        ok = tg_send("Watchdog test message - if you see this, config is good.")
        print("telegram_send_ok" if ok else "telegram_config_missing_or_failed")
        return 0 if ok else 1

    if args.probe:
        ok = probe()
        print("ONLINE" if ok else "OFFLINE")
        return 0 if ok else 1

    if args.status:
        print("STATE=" + classify())
        return 0

    if args.login_test:
        res = try_login()
        print("RESULT=" + res)
        return 0 if res == "online" else 2

    if args.dry_rotate:
        newmac = rotate_mac(dry_run=True)
        print("DRY_ROTATE" + (f" iface -> {newmac}" if newmac else " no-wifi-default-iface"))
        return 0 if newmac else 1

    sys.exit(do_pass(load_state()))


if __name__ == "__main__":
    main()