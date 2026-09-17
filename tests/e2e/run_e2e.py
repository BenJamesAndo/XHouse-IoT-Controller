"""End-to-end test of the XHouse API client against the live cloud.

Runs the integration's own ``XHouseApi`` (no Home Assistant needed) and checks
the behaviours that have bitten us in the field: login, device listing, and
recovery from a displaced session. Optional emulator steps report on the
XHouse Android app via adb.

Credentials come from the Windows Credential Manager entry named ``xhouse``
(generic credential: user = account email, password), or from the
``XHOUSE_EMAIL`` / ``XHOUSE_PASSWORD`` environment variables. They are never
printed.

WARNING: every login on this account logs out whatever else is signed in -
the phone app and any running Home Assistant instance included. Run this
against a test account, or expect to re-login afterwards.

Usage:
    python tests/e2e/run_e2e.py                 # API steps only
    python tests/e2e/run_e2e.py --emulator      # + report on the app
    python tests/e2e/run_e2e.py --emulator --cycle-app
        # ...bringing the app to the foreground first
    python tests/e2e/run_e2e.py --emulator --wait-app-login 300
        # ...and pause up to 300s for a human to log the app in, then verify
        # the client recovers from the displacement that causes.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import types
from pathlib import Path

import aiohttp

REPO = Path(__file__).resolve().parents[2]
PKG = REPO / "custom_components" / "xhouse"
APP = "com.giigle.xhouse.iot"
ADB: str | None = None


def load_api():
    """Import custom_components/xhouse/{const,api}.py without homeassistant."""
    pkg = types.ModuleType("xhouse")
    pkg.__path__ = [str(PKG)]
    sys.modules["xhouse"] = pkg
    for name in ("const", "api"):
        spec = importlib.util.spec_from_file_location(f"xhouse.{name}", PKG / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"xhouse.{name}"] = mod
        spec.loader.exec_module(mod)
    return sys.modules["xhouse.api"]


def credentials() -> tuple[str, str]:
    email, pw = os.environ.get("XHOUSE_EMAIL"), os.environ.get("XHOUSE_PASSWORD")
    if email and pw:
        return email, pw
    if sys.platform != "win32":
        sys.exit("Set XHOUSE_EMAIL and XHOUSE_PASSWORD")
    import ctypes
    import ctypes.wintypes as wt

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", wt.DWORD), ("Type", wt.DWORD), ("TargetName", wt.LPWSTR),
            ("Comment", wt.LPWSTR), ("LastWritten", wt.FILETIME),
            ("CredentialBlobSize", wt.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
            ("Persist", wt.DWORD), ("AttributeCount", wt.DWORD),
            ("Attributes", ctypes.c_void_p), ("TargetAlias", wt.LPWSTR),
            ("UserName", wt.LPWSTR),
        ]

    adv = ctypes.windll.advapi32
    p = ctypes.POINTER(CREDENTIAL)()
    if not adv.CredReadW("xhouse", 1, 0, ctypes.byref(p)):
        sys.exit("No 'xhouse' generic credential in Credential Manager and no env vars set")
    c = p.contents
    pw = ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize).decode("utf-16-le")
    email = c.UserName
    adv.CredFree(p)
    return email, pw


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def add(self, name: str, ok: bool | None, detail: str = "") -> None:
        status = "PASS" if ok else ("SKIP" if ok is None else "FAIL")
        self.rows.append((name, status, detail))
        print(f"  [{status}] {name}{'  - ' + detail if detail else ''}", flush=True)

    @property
    def failed(self) -> bool:
        return any(s == "FAIL" for _, s, _ in self.rows)


async def raw_post(api_mod, api, endpoint: str, body: dict):
    """Bypass the client's parsing to observe the server's raw answer."""
    headers = api._build_headers()
    data = json.dumps(body, separators=(",", ":"))
    headers["content-length"] = str(len(data.encode()))
    async with api._session.post(
        f"{api_mod.API_BASE_URL}/{endpoint}", headers=headers, data=data,
        timeout=aiohttp.ClientTimeout(total=10),
    ) as r:
        text = await r.text()
        try:
            j = json.loads(text)
        except json.JSONDecodeError:
            j = None
        return r.status, r.headers.get("content-type", ""), j


# ---------------------------------------------------------------- adb helpers
def adb_path() -> str | None:
    for c in (
        shutil.which("adb"),
        os.path.join(os.environ.get("ANDROID_HOME", ""), "platform-tools", "adb.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk", "platform-tools", "adb.exe"),
        r"D:\Android\Sdk\platform-tools\adb.exe",
    ):
        if c and os.path.exists(c):
            return c
    return None


def adb(*args: str) -> str:
    return subprocess.run([ADB, *args], capture_output=True, text=True, timeout=30).stdout.strip()


def app_top_activity() -> str:
    out = adb("shell", "dumpsys activity activities | grep topResumedActivity | head -1")
    if APP not in out:
        return f"(not {APP})"
    return out.split("/")[-1].split(" ")[0].strip("}")


def app_launch() -> None:
    adb("shell", "input", "keyevent", "KEYCODE_HOME")
    time.sleep(1)
    adb("shell", "am", "start", "-n", f"{APP}/.ui.activity.SplashActivity")


# ---------------------------------------------------------------------- steps
async def main(args: argparse.Namespace) -> int:
    api_mod = load_api()
    XHouseApi = api_mod.XHouseApi
    email, pw = credentials()
    rep = Report()
    print(f"XHouse e2e - account {email}\n")

    async with aiohttp.ClientSession() as s:
        # 1. Login and device listing through the real client.
        primary = XHouseApi(s)
        try:
            await primary.login(email, pw)
            devices = await primary.get_devices()
            rep.add("login + queryGroupDevices", bool(devices), f"{len(devices)} device(s)")
        except Exception as e:  # noqa: BLE001
            rep.add("login + queryGroupDevices", False, f"{type(e).__name__}: {e}")
            return 1
        first = devices[0]
        summary = f"{first.get('alias')} [{first.get('deviceType')}] id={first.get('id')}"

        # 2. Live properties for the first device (the poll the coordinator does).
        try:
            props = await primary.get_device_properties(int(first["id"]))
            rep.add("getWifiProperties", isinstance(props, list), f"{summary}: {len(props)} properties")
        except Exception as e:  # noqa: BLE001
            rep.add("getWifiProperties", False, f"{type(e).__name__}: {e}")

        # 3. Server contract: a displaced token answers 200 text/json + session-invalid code.
        intruder = XHouseApi(s)
        await intruder.login(email, pw)
        await asyncio.sleep(2)
        status, ctype, j = await raw_post(
            api_mod, primary, "group/queryGroupDevices",
            {"userId": int(primary.user_id), "groupId": 0},
        )
        code = (j or {}).get("code")
        rep.add(
            "displaced token -> text/json + session-invalid code",
            status == 200 and "text/json" in ctype and str(code) in api_mod.SESSION_INVALID_CODES,
            f"http={status} ct={ctype} code={code} msg={(j or {}).get('msg')!r}",
        )

        # 4. The client must recover transparently on its next authed call.
        old_token = primary.token
        try:
            devices2 = await primary.get_devices()
            rep.add(
                "client re-authenticates after displacement",
                bool(devices2) and primary.token != old_token,
                "new token issued, poll succeeded",
            )
        except Exception as e:  # noqa: BLE001
            rep.add("client re-authenticates after displacement", False, f"{type(e).__name__}: {e}")

        # 5. ...which in turn displaced the intruder (single-session confirmed).
        await asyncio.sleep(2)
        _, _, j2 = await raw_post(
            api_mod, intruder, "group/queryGroupDevices",
            {"userId": int(intruder.user_id), "groupId": 0},
        )
        rep.add(
            "account is single-session (last login wins)",
            str((j2 or {}).get("code")) in api_mod.SESSION_INVALID_CODES,
            f"intruder now code={(j2 or {}).get('code')}",
        )

        # 6. Optional emulator observations.
        if args.emulator:
            devs = adb("devices") if ADB else ""
            if not ADB or "\tdevice" not in devs:
                rep.add("emulator reachable", None, "no adb device")
            else:
                rep.add("emulator reachable", True, devs.splitlines()[-1])
                if args.cycle_app:
                    app_launch()
                    time.sleep(8)
                rep.add("app top activity", True, app_top_activity())
                if args.wait_app_login:
                    print(
                        f"\n  >> Log the XHouse app in on the emulator now "
                        f"(waiting up to {args.wait_app_login}s)...",
                        flush=True,
                    )
                    deadline = time.time() + args.wait_app_login
                    while time.time() < deadline and "MainActivity" not in app_top_activity():
                        time.sleep(3)
                    logged_in = "MainActivity" in app_top_activity()
                    rep.add("human logged the app in", logged_in, app_top_activity())
                    if logged_in:
                        await asyncio.sleep(3)
                        tok = primary.token
                        try:
                            await primary.get_devices()
                            recovered = primary.token != tok
                            rep.add(
                                "client recovers after app login displaced it",
                                recovered,
                                "re-login happened" if recovered else "token was not displaced?",
                            )
                            await asyncio.sleep(3)
                            app_launch()
                            time.sleep(8)
                            top = app_top_activity()
                            rep.add("app kicked to LoginActivity by our re-login", "LoginActivity" in top, top)
                        except Exception as e:  # noqa: BLE001
                            rep.add("client recovers after app login displaced it", False, f"{type(e).__name__}: {e}")

    print("\n" + ("FAILED" if rep.failed else "ALL PASSED"))
    return 1 if rep.failed else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--emulator", action="store_true", help="also report on the XHouse app via adb")
    ap.add_argument("--cycle-app", action="store_true", help="with --emulator: bring the app to the foreground first")
    ap.add_argument("--wait-app-login", type=int, metavar="SECS",
                    help="with --emulator: pause for a human to log the app in, then verify recovery")
    a = ap.parse_args()
    ADB = adb_path()
    sys.exit(asyncio.run(main(a)))
