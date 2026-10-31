#!/usr/bin/env python3
"""Headless-Chromium smoke test for the auto-login environment.
Verifies Playwright can launch a browser on this machine.
Set WIFI_CHANNEL=chrome (or msedge) to use an installed browser.
"""
import os

from playwright.sync_api import sync_playwright


def main():
    kwargs = {
        "headless": True,
        "args": ["--no-sandbox", "--disable-dev-shm-usage", "--disable-background-networking"],
    }
    channel = os.environ.get("WIFI_CHANNEL", "")
    if channel:
        kwargs["channel"] = channel
    with sync_playwright() as p:
        browser = p.chromium.launch(**kwargs)
        page = browser.new_page()
        page.goto("about:blank")
        ua = page.evaluate("navigator.userAgent")
        print("UA:", ua)
        print("TITLE:", page.title())
        browser.close()
    print("SMOKE_OK")


if __name__ == "__main__":
    main()