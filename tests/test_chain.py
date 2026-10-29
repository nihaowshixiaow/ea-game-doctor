"""启动链路分析测试：纯文本解析 + 关键判定。"""

from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import chain, eaapp  # noqa: E402

STEAM_LOG = """
[2026-10-29 00:38:26] AppID 1238820 adding PID 11424 as a tracked process "EASteamLauncher.exe" "steam2ea://launchgame/1238820?platform=steam&offerId=DR%3a224766400"
[2026-10-29 00:38:32] AppID 1238820 adding PID 15856 as a tracked process "bf3.exe -webMode SP -AuthCode xxx"
[2026-10-29 00:39:25] AppID 1238820 no longer tracking PID 15856, exit code 0
[2026-10-29 00:39:41] AppID 1238820 adding PID 21948 as a tracked process "steam2ea://launchgame/1238820?platform=steam&theme=bf3"
[2026-10-29 00:39:48] AppID 1238820 no longer tracking PID 21948, exit code 0
[2026-10-29 00:41:06] AppID 1238820 no longer tracking PID 11424, exit code 1
[2026-10-29 00:39:40] AppID 1182480 adding PID 28052 as a tracked process "EASteamAuthHelper.exe"
"""

EA_CORE_LOG = """
CLIENT  [16:38:33:204] [26952]Launching separate server F:\\Battlefield 3\\Core\\EACoreServer.exe
CLIENT  [16:38:53:441] [26952]Message (guid 0) timed out: 20000 ms   Request: eadcommand:?cmd=cmd_portal_command&cmdid=148&command=CommandProxy&guid=3&keytype=1&keyvalue=xxx
CLIENT  [16:38:53:444] [26952]Command not processed. Max 20000  Msg: eadcommand:?cmd=cmd_portal_command
SERVER  [16:40:21:709] [18448]CreateProcessW(F:\\STEAMLIBRARY\\STEAMAPPS\\COMMON\\BATTLEFIELD 3\\CORE\\activation.exe, "F:\\...\\activation.exe" /locale=en_US /gameName="Battlefield 3?")
SERVER  [16:38:56:500] [18448]ShutdownLocalServer() - Removing server directory entry.
"""


def test_parse_steam_events() -> None:
    events = chain.parse_steam_events(STEAM_LOG, 1238820)
    starts = [event for event in events if event.kind == "start"]
    stops = [event for event in events if event.kind == "stop"]
    assert len(starts) == 3, events
    assert len(stops) == 3, events
    assert starts[0].pid == 11424
    assert starts[0].when is not None and starts[0].when.hour == 0
    assert all("1182480" not in event.detail for event in events)


def test_parse_ea_core() -> None:
    activations, timeouts = chain.parse_ea_core(EA_CORE_LOG)
    assert timeouts == 1
    assert len(activations) == 1
    event = activations[0]
    assert event.exe.endswith("activation.exe")
    assert event.time_text == "00:40:21"  # UTC 16:40 -> 本地 00:40（本机为中国时区）
    assert event.game_dir and event.game_dir.endswith("BATTLEFIELD 3")


def test_analyze_steam_not_launched() -> None:
    analysis = chain.analyze_texts(
        appid=1238820,
        game_name="Battlefield 3",
        steam_text="",
        ea_core_text=EA_CORE_LOG,
        license_after=0,
    )
    assert analysis.cause == "steam_not_launched"
    assert analysis.notes


def test_analyze_portal_timeout_without_license() -> None:
    analysis = chain.analyze_texts(
        appid=1238820,
        game_name="Battlefield 3",
        steam_text=STEAM_LOG,
        ea_core_text=EA_CORE_LOG,
        license_after=0,
        ea_mode="silent",
    )
    assert analysis.cause == "ea_portal_timeout_no_license", analysis
    assert analysis.last_start is not None
    assert analysis.last_activation is not None
    assert analysis.portal_timeouts == 1
    assert any("授权" in note for note in analysis.notes)
    lines = "\n".join(analysis.lines)
    assert "Steam 启动记录" in lines and "激活" in lines and "授权缓存" in lines


def test_analyze_stale_bf3_license() -> None:
    analysis = chain.analyze_texts(
        appid=1238820,
        game_name="Battlefield 3",
        steam_text=STEAM_LOG,
        ea_core_text=EA_CORE_LOG,
        license_after=0,
        stale_legacy_license=True,
        legacy_license_age_days=470.0,
    )
    assert analysis.cause == "bf3_license_stale", analysis
    lines = "\n".join(analysis.lines)
    assert "授权缓存年龄" in lines
    assert any("71067" in note or "授权缓存" in note for note in analysis.notes)


def test_analyze_license_stale() -> None:
    analysis = chain.analyze_texts(
        appid=1238820,
        game_name="Battlefield 3",
        steam_text=STEAM_LOG,
        ea_core_text=EA_CORE_LOG,
        license_after=3,
    )
    assert analysis.cause == "license_cache_stale", analysis


def _make_token(payload: dict) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256"}).encode()).decode().rstrip("=")
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{header}.{body}.signature"


def test_decode_token() -> None:
    token = _make_token(
        {
            "iss": "accounts.ea.com",
            "nexus": {
                "pty": "STEAM",
                "pid": "1017606948436",
                "uif": {"cty": "CN"},
                "psif": [
                    {"id": 1008026348436, "ns": "steam", "nic": "DemoUser", "extref": "76561198000000000"},
                    {"id": 1005765548436, "ns": "cem_ea_id", "dis": "DemoEAID", "nic": "DemoNick"},
                ],
            },
        }
    )
    payload = eaapp.decode_token(token)
    assert payload is not None
    assert payload["platform"] == "STEAM"
    assert payload["ea_id"] == "DemoEAID"
    assert payload["ea_nick"] == "DemoNick"
    assert payload["steam_nick"] == "DemoUser"
    assert payload["steam_id"] == "76561198000000000"
    assert payload["country"] == "CN"
    assert eaapp.decode_token("not-a-token") is None


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"chain: {len(tests)} tests passed")
