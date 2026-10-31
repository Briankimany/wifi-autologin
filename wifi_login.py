#!/usr/bin/env python3
"""Namonet WiFi captive-portal auto-login using Playwright (headless Chromium).

Flow:
  1. Open the captive portal entry (default http://10.10.0.1).
  2. The portal redirects -> http://namonet.wifi/login
     which auto-posts -> http://c.netpap.co.ke/management/login/
     (the page with the voucher input field).
  3. Fill the voucher input (#username) with the code and click submit (#btn-submit).
  4. Verify internet connectivity (generate_204) plus the portal /status success page.

Commands:
  python wifi_login.py --code A4B2C1     # login with a voucher code
  python wifi_login.py                    # code read from env WIFI_CODE
  python wifi_login.py --status           # check portal /status (logged in?)
  python wifi_login.py --logout           # disconnect via portal /logout

Options:
  python wifi_login.py --portal <url>     # override portal entry URL
  python wifi_login.py --headed           # visible browser (auto-falls back to
                                          #   headless if no X display is available)
Exit code 0 = success, 1 = failure.
"""
import argparse
import datetime
import os
import sys
from urllib.parse import urlsplit, urlunsplit

from playwright.sync_api import sync_playwright

PORTAL = "http://10.10.0.1"
CHECK_URL = "https://www.google.com/generate_204"
USERNAME_SELECTOR = "#username"
SUBMIT_SELECTOR = "#btn-submit"

# HTML snapshots are kept in RAM as the run progresses; they are only written
# to disk if an error occurs (so successful runs leave no files behind).
SNAPSHOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshots")
SNAPSHOTS = []
MAX_SNAPSHOTS = 24

# Dedicated browser cache bundled with this project, so Playwright installs
# from other projects (different versions) never prune our Chromium revision.
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_BUNDLED_BROWSERS = os.path.join(_APP_DIR, "ms-playwright")
if os.path.isdir(_BUNDLED_BROWSERS):
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", _BUNDLED_BROWSERS)

LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-background-networking",
    "--no-first-run",
]

# Optional system browser channel (e.g. "chrome", "msedge"). When set, the
# bundled Chromium download is not required.
CHANNEL = os.environ.get("WIFI_CHANNEL", "").strip()

LOGGED_IN_WORDS = ("connected", "logged in", "you are now", "uptime",
                   "ip address", "valid until", "successful", "welcome")
LOGGED_OUT_WORDS = ("logged out", "not logged in", "disconnected", "sign in",
                    "login now", "please login")


def launch(pw, headed):
    if headed and sys.platform != "win32" and not os.environ.get("DISPLAY"):
        print("[!] --headed requested but no DISPLAY/X server is available; "
              "running headless instead.")
        print("[!] (On a machine without a logged-in desktop, use headless or "
              "run under 'xvfb-run': xvfb-run -a python wifi_login.py --headed ...)")
        headed = False
    kwargs = {"headless": not headed, "args": LAUNCH_ARGS}
    if CHANNEL:
        kwargs["channel"] = CHANNEL
    return pw.chromium.launch(**kwargs)


def origin_of(portal):
    parts = urlsplit(portal)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def read_body(page):
    try:
        return page.inner_text("body").strip()
    except Exception:
        return ""


def grab(page, tag):
    try:
        SNAPSHOTS.append({
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
            "tag": tag,
            "url": page.url,
            "html": page.content(),
        })
        del SNAPSHOTS[:-MAX_SNAPSHOTS]
    except Exception:
        pass


def dump_snapshots(reason, page=None):
    last_url = ""
    if page is not None:
        try:
            last_url = page.url
        except Exception:
            pass
        grab(page, "final")
    try:
        os.makedirs(SNAPSHOT_DIR, exist_ok=True)
        base = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        if not SNAPSHOTS:
            path = os.path.join(SNAPSHOT_DIR, f"{base}_00_nohtml.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"error={reason}\n")
                f.write(f"last_url={last_url}\n")
                f.write("no html captured (page state unavailable)\n")
            print(f"[i] error snapshots -> {SNAPSHOT_DIR}")
            return
        lines = []
        for i, s in enumerate(SNAPSHOTS):
            path = os.path.join(SNAPSHOT_DIR, f"{base}_{i:02d}_{s['tag']}.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"<!-- ts={s['ts']} tag={s['tag']} url={s['url']} -->\n")
                f.write(s["html"])
            lines.append(f"{i:02d} {s['tag']}  url={s['url']}")
        with open(os.path.join(SNAPSHOT_DIR, f"{base}_meta.txt"), "w", encoding="utf-8") as f:
            f.write(f"error={reason}\n")
            f.write("\n".join(lines) + "\n")
        print(f"[i] error snapshots -> {SNAPSHOT_DIR}")
    except Exception as exc:
        print(f"[!] could not write snapshots: {exc}")


def report_page(page, label):
    print(f"[*] {label} page URL: {page.url}")
    body = read_body(page)
    if body:
        print(f"[*] {label} body:", body[:400].replace("\n", " | "))
    return body


def run(code, portal, headed):
    with sync_playwright() as pw:
        browser = launch(pw, headed)
        page = None
        try:
            page = browser.new_page(ignore_https_errors=True)
            page.set_default_timeout(30000)
            return do_login(page, code, portal)
        except Exception as exc:
            try:
                dump_snapshots(repr(exc), page=page)
            except Exception:
                pass
            raise
        finally:
            browser.close()


def do_login(page, code, portal):
    print(f"[*] Opening portal: {portal}")
    page.goto(portal, wait_until="domcontentloaded", timeout=30000)
    grab(page, "opened-portal")

    print("[*] Waiting for voucher login form (following portal redirects)...")
    grab(page, "waiting-form")
    page.wait_for_selector(USERNAME_SELECTOR, timeout=45000)
    page.wait_for_selector(SUBMIT_SELECTOR, timeout=10000)

    field = page.locator(USERNAME_SELECTOR)
    field.fill("")
    field.fill(code)
    print(f"[*] Entered voucher code ({len(code)} chars)")

    print("[*] Submitting...")
    try:
        page.locator(SUBMIT_SELECTOR).click()
    except Exception as exc:  # selector may detach if the page navigates mid-click
        print(f"[!] click raised ({exc}); continuing")
    page.wait_for_timeout(4000)
    grab(page, "post-submit")
    print(f"[*] post-submit URL: {page.url}")

    body = read_body(page)
    if body:
        print("[*] post-submit body snippet:", body[:400].replace("\n", " | "))

    msg = detect_message(body, page.url)
    if msg:
        print(f"[*] portal response: {msg}")

    try:
        page.screenshot(path="login_debug.png")
        print("[*] screenshot -> login_debug.png")
    except Exception:
        pass

    ok = verify_connectivity(page)
    if ok:
        print("[+] SUCCESS: internet connectivity confirmed after login")
        status_ok = check_status(page, origin_of(portal), "post-login")
        if not status_ok:
            print("[-] note: portal /status did not show a logged-in success message")
        print("STATE:online")
    else:
        print("[-] FAILURE: code submitted but connectivity not confirmed")
        print("STATE:login-failed")
    return ok


def detect_message(body, url):
    body_l = body.lower()
    success = body_l.count("connected") + body_l.count("logged in") \
        + body_l.count("login successful") + body_l.count("welcome")
    failure_hits = [w for w in ("invalid", "incorrect", "wrong", "error",
                                "failed login", "successful login", "expired", "denied",
                                "not valid", "does not exist") if w in body_l]
    if "err=" in url or "error=" in url:
        failure_hits.append("error-in-url")
    if success:
        return "SUCCESS signal seen in response page"
    if failure_hits:
        return "FAILURE signal: " + ", ".join(failure_hits)
    return ""


def verify_connectivity(page, attempts=4):
    for i in range(1, attempts + 1):
        try:
            resp = page.goto(CHECK_URL, wait_until="domcontentloaded", timeout=15000)
            url = resp.url if resp else page.url
            status = resp.status if resp else None
            if status in (200, 204) and "google.com" in url:
                return True
            blocked = any(h in url for h in ("10.10.0.1", "namonet", "netpap", "login"))
            print(f"[-] verify #{i}: status={status} url={url}"
                  + (" (still on portal)" if blocked else ""))
        except Exception as exc:
            print(f"[-] verify #{i}: error {exc}")
        page.wait_for_timeout(1500)
    return False


def check_status(page, origin, label="status"):
    url = origin.rstrip("/") + "/status"
    print(f"[*] Checking portal status at {url} ({label})")
    state = "blocked"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(1500)
        grab(page, "status-page")
        body = report_page(page, label)
        if "management/login" in page.url:
            print("[-] STATUS: not logged in (redirected to the captive login page)")
            state = "login-needed"
        else:
            hits = [w for w in LOGGED_IN_WORDS if w in body.lower()]
            if hits:
                print(f"[+] STATUS: logged in (signals: {', '.join(hits)})")
                state = "online"
            else:
                print("[-] STATUS: no logged-in success message on /status")
                state = "login-needed"
    except Exception as exc:
        try:
            final = page.url
        except Exception:
            final = ""
        if any(t in final for t in ("management/login", "namonet", "10.10.0.1")):
            print(f"[-] could not finish load {url} (gateway reachable, on: {final[:80]})")
            state = "login-needed"
        else:
            print(f"[-] could not load {url}: {exc}")
            state = "blocked"
    print(f"STATE:{state}")
    return state == "online"


def cmd_status(portal, headed):
    with sync_playwright() as pw:
        browser = launch(pw, headed)
        page = None
        try:
            page = browser.new_page(ignore_https_errors=True)
            page.set_default_timeout(20000)
            return check_status(page, origin_of(portal), "status")
        except Exception as exc:
            try:
                dump_snapshots(repr(exc), page=page)
            except Exception:
                pass
            raise
        finally:
            browser.close()


def cmd_logout(portal, headed):
    with sync_playwright() as pw:
        browser = launch(pw, headed)
        page = None
        try:
            page = browser.new_page(ignore_https_errors=True)
            page.set_default_timeout(20000)
            url = origin_of(portal).rstrip("/") + "/logout"
            print(f"[*] Logging out via {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
            except Exception as exc:
                print(f"[-] could not load {url}: {exc}")
                return False
            page.wait_for_timeout(1500)
            grab(page, "logout-page")
            body = report_page(page, "logout")
            if any(w in body.lower() for w in LOGGED_OUT_WORDS) \
                    or "management/login" in page.url:
                print("[+] LOGOUT: disconnected (back at the captive login page)")
                return True
            print("[-] LOGOUT: page did not confirm logout")
            return False
        except Exception as exc:
            try:
                dump_snapshots(repr(exc), page=page)
            except Exception:
                pass
            raise
        finally:
            browser.close()


def main():
    ap = argparse.ArgumentParser(
        description="Namonet WiFi captive-portal control: login / status / logout")
    ap.add_argument("--code", default=os.environ.get("WIFI_CODE", ""),
                    help="voucher code to log in with (or set env WIFI_CODE)")
    ap.add_argument("--portal", default=PORTAL,
                    help=f"captive portal entry URL (default {PORTAL})")
    ap.add_argument("--headed", action="store_true",
                    help="run with a visible browser window")
    ap.add_argument("--channel", default=os.environ.get("WIFI_CHANNEL", ""),
                    help='use an installed browser instead of bundled Chromium '
                         '(e.g. "chrome", "msedge"); also env WIFI_CHANNEL')
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument("--status", action="store_true",
                     help="check the portal /status page (is the device connected?)")
    grp.add_argument("--logout", action="store_true",
                     help="disconnect the device via the portal /logout page")
    args = ap.parse_args()

    global CHANNEL
    if args.channel:
        CHANNEL = args.channel.strip()

    if args.status:
        sys.exit(0 if cmd_status(args.portal, args.headed) else 1)
    if args.logout:
        sys.exit(0 if cmd_logout(args.portal, args.headed) else 1)
    if not args.code:
        ap.error("nothing to do: give --code CODE (login), or --status / --logout")

    ok = run(args.code, args.portal, args.headed)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()