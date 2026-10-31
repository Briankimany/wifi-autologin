# wifi-autologin

Automatic login and watchdog for a voucher-based public Wi-Fi captive portal.

It opens the portal in headless Chromium, submits your voucher code, checks
that the internet really works, and re-logs in whenever the session drops.
On Linux it can also rotate the Wi-Fi MAC address when the portal keeps
rejecting the device.

```
portal -> redirect -> voucher form -> submit -> verify internet -> repeat
```

## Quick start

### Windows

```powershell
# 1. Install (uses your installed Chrome; add -RegisterTask for auto-run)
powershell -ExecutionPolicy Bypass -File .\install_windows.ps1 -Channel chrome -RegisterTask

# 2. Put your voucher code in watchdog\code.txt
notepad watchdog\code.txt

# 3. Run one check now
run_watchdog.bat
```

### Linux

```bash
# 1. Install
python3 -m venv plenv
./plenv/bin/pip install -r requirements.txt
export PLAYWRIGHT_BROWSERS_PATH="$PWD/ms-playwright"
./plenv/bin/playwright install chromium

# 2. Put your voucher code in the config
cp watchdog/code.txt.example watchdog/code.txt
nano watchdog/code.txt

# 3. Try a login
./plenv/bin/python wifi_login.py --code YOUR_CODE
```

If you have the offline `browser/` and `wheels/` folders, you can run
`bash install_remote.sh` instead of the manual Linux install.

## What it does

- **Login** — fills the voucher field (`#username`) and submits the form
  (`#btn-submit`) through the portal redirects.
- **Verify** — confirms real internet access via
  `https://www.google.com/generate_204`.
- **Watchdog** — every few minutes it classifies the connection as:
  - `online` — internet works, nothing to do.
  - `login-needed` — captive portal is redirecting, so it logs in again.
  - `blocked` — the gateway is unreachable, so it waits and retries.
- **Notify** — optional Telegram messages when the state changes.
- **Rotate** — Linux only: changes the Wi-Fi MAC after repeated failures.

## Requirements

- Python 3.12+
- [Playwright](https://playwright.dev/python/) (installed from `requirements.txt`)
- A browser:
  - bundled Chromium (`playwright install chromium`), or
  - installed Chrome / Edge on Windows (`-Channel chrome` / `-Channel msedge`)
- Linux only, for MAC rotation: `curl`, `ip`, root, and `dhclient` or `nmcli`

## Install

### Windows

```powershell
powershell -ExecutionPolicy Bypass -File .\install_windows.ps1 -Channel chrome
```

Options:

| Option | Meaning |
|---|---|
| `-Channel chrome` | Use installed Google Chrome (no download) |
| `-Channel msedge` | Use installed Microsoft Edge |
| *(no channel)* | Download Playwright Chromium into `.\ms-playwright` |
| `-RegisterTask` | Run the watchdog every 3 minutes via Task Scheduler |
| `-IntervalMinutes 5` | Change the Task Scheduler interval |

The installer creates `.venv`, installs dependencies, creates
`watchdog\code.txt` and `watchdog\telegram.conf` from their templates, and runs
a smoke test.

### Linux

```bash
python3 -m venv plenv
./plenv/bin/pip install -r requirements.txt
export PLAYWRIGHT_BROWSERS_PATH="$PWD/ms-playwright"
./plenv/bin/playwright install chromium
```

Or, with the offline bundles present:

```bash
bash install_remote.sh
```

`browser/`, `wheels/`, and `ms-playwright/` are not committed to git because
they are large.

## Configure

### Voucher code

```bash
cp watchdog/code.txt.example watchdog/code.txt
```

Put one voucher code per line. The watchdog always uses the first non-empty
line and reuses it until the portal rejects it. Replace the file content when
you get a new code; the next pass picks it up automatically.

`watchdog/code.txt` is git-ignored, so real codes are never committed.

### Telegram alerts (optional)

```bash
cp watchdog/telegram.conf.example watchdog/telegram.conf
```

Fill in `TOKEN=` (from [@BotFather](https://t.me/BotFather)) and `CHAT=`
(your numeric chat id). Test it:

```bash
./plenv/bin/python watchdog/watchdog.py --test-telegram
```

`watchdog/telegram.conf` is git-ignored.

### Browser choice

If Chromium cannot be downloaded, point the tool at an installed browser:

```bash
./plenv/bin/python wifi_login.py --code CODE --channel chrome
```

On Windows, `install_windows.ps1 -Channel chrome` saves `WIFI_CHANNEL` for your
user so the watchdog uses it automatically. Accepted values include `chrome`
and `msedge`.

### Paths

`watchdog.py` finds the project root from its own location, so the repo can
live anywhere. Override if needed:

```bash
export WIFI_WATCHDOG_HOME=/path/to/wifi-autologin
export WIFI_WATCHDOG_PYTHON=/path/to/plenv/bin/python
```

## Usage

### Log in, check, log out

```bash
./plenv/bin/python wifi_login.py --code A4B2C1
WIFI_CODE=A4B2C1 ./plenv/bin/python wifi_login.py
./plenv/bin/python wifi_login.py --status
./plenv/bin/python wifi_login.py --logout
```

Windows:

```powershell
.\.venv\Scripts\python.exe wifi_login.py --code A4B2C1
.\.venv\Scripts\python.exe wifi_login.py --status
.\.venv\Scripts\python.exe wifi_login.py --logout
```

Exit code `0` means success. On failure, HTML snapshots are written to
`snapshots/` for debugging.

### Watchdog commands

```bash
./plenv/bin/python watchdog/watchdog.py --run          # one full pass
./plenv/bin/python watchdog/watchdog.py --probe        # is the internet up?
./plenv/bin/python watchdog/watchdog.py --status       # classify portal state
./plenv/bin/python watchdog/watchdog.py --login-test   # try the stored code
./plenv/bin/python watchdog/watchdog.py --dry-rotate   # show rotation plan
```

On Windows, `run_watchdog.bat` runs one full pass.

## Run it automatically

### Linux (systemd)

The unit file assumes the project is at `/opt/wifi-autologin`. Edit the paths
in the unit files if you installed elsewhere.

```bash
sudo cp watchdog/wifi-watchdog.service /etc/systemd/system/
sudo cp watchdog/wifi-watchdog.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now wifi-watchdog.timer
```

Check it:

```bash
systemctl list-timers wifi-watchdog.timer
journalctl -u wifi-watchdog.service -n 50 --no-pager
tail -f watchdog/watchdog.log
```

### Windows (Task Scheduler)

```powershell
powershell -ExecutionPolicy Bypass -File .\install_windows.ps1 -Channel chrome -RegisterTask
Get-ScheduledTask -TaskName WifiWatchdog
```

Remove it with:

```powershell
Unregister-ScheduledTask -TaskName WifiWatchdog -Confirm:$false
```

Keep the laptop awake and disable power saving on the Wi-Fi adapter
(Device Manager → Wi-Fi adapter → Power Management). Logs go to
`watchdog\watchdog.log`.

## Files

| Path | Purpose |
|---|---|
| `wifi_login.py` | Login / status / logout CLI |
| `watchdog/watchdog.py` | Probe, classify, re-login, rotate |
| `watchdog/wifi-watchdog.service` | systemd oneshot unit |
| `watchdog/wifi-watchdog.timer` | systemd timer (every ~3 min) |
| `watchdog/code.txt.example` | Voucher-code template |
| `watchdog/telegram.conf.example` | Telegram template |
| `install_remote.sh` | Offline/online Linux installer |
| `install_windows.ps1` | Windows installer + Scheduled Task |
| `run_watchdog.bat` | One watchdog pass on Windows |
| `bounce_wifi.sh` | Reconnect a NetworkManager Wi-Fi profile |
| `inspect_portal.sh` | Debug helper for the portal page |
| `smoke_test.py` | Verify the browser launches |
| `requirements.txt` | Python dependencies |

## Troubleshooting

**Chromium download fails or times out**

Use an installed browser:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_windows.ps1 -Channel chrome
```

or per run: `wifi_login.py --code CODE --channel chrome` (`msedge` also works).

**`Executable doesn't exist ... chrome-headless-shell`**

Playwright and its browser build are out of sync:

```bash
./plenv/bin/playwright install chromium
```

**The watchdog cannot find Python or playwright**

It uses `<repo>/plenv/bin/python` on Linux and
`<repo>/.venv/Scripts/python.exe` on Windows. Create that venv or set
`WIFI_WATCHDOG_PYTHON`.

**Portal is reachable but login never succeeds**

Run with `--headed` (or `xvfb-run` on a headless Linux box) to watch the flow,
then inspect the `snapshots/` folder.

**MAC rotation does nothing**

It only runs on Linux, only on a Wi-Fi default interface, requires root, and
needs `ip` plus `dhclient` or `nmcli`. On Windows, use the built-in
per-network "Random hardware addresses" setting instead.

## Security

- Never commit `watchdog/code.txt`, `watchdog/telegram.conf`, or `.env`.
  They are listed in `.gitignore`.
- MAC rotation changes your device identity. Use it only on networks you are
  allowed to access.

## License

No license has been added yet. Ask the author before redistributing.
