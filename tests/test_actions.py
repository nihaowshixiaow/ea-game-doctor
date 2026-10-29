"""修复动作链测试：方案顺序、备份还原、dry-run 全流程。"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import actions, detect, discovery  # noqa: E402
from app.config import EventLog, Settings  # noqa: E402

GAME_DIR = r"C:\Games\Battlefield 3"


def make_game() -> discovery.InstalledGame:
    return discovery.InstalledGame(
        key="bf3",
        name="Battlefield 3",
        name_cn="战地 3",
        aliases=["Battlefield 3"],
        install_dir=GAME_DIR,
        exe=GAME_DIR + r"\bf3.exe",
        steam_appid=1238820,
        platform="steam",
        installed=True,
        accent=("#F0B34A", "#E5603A"),
    )


def make_issue() -> detect.Issue:
    return detect.Issue(
        kind=detect.KIND_ACTIVATION,
        game_key="bf3",
        game_name="Battlefield 3",
        confidence=0.98,
        evidence=["EA 激活程序 activation.exe 正在运行"],
        hwnd=0x1234,
        pid=9999,
        proc_name="activation.exe",
        title="Battlefield 3",
    )


def test_plan_order() -> None:
    quick = [step.id for step in actions.build_plan("quick")]
    assert quick[0] == "snapshot" and quick[-1] == "conclude"
    assert "launch" in quick and "verify" in quick
    deep = [step.id for step in actions.build_plan("deep")]
    assert deep[0] == "snapshot" and deep[-1] == "conclude"
    assert "clear_license" in deep and "stop_ea" in deep
    assert actions.plan_payload("deep")[0]["risk_label"]


def test_backup_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "backups"
        source = Path(tmp) / "license"
        source.mkdir()
        files = []
        for index in range(3):
            path = source / f"{index}.dlf"
            path.write_text(f"license-{index}", encoding="utf-8")
            files.append(path)
        store = actions.BackupStore(root=root, label="unit-test")
        moved, failed = store.move_files(files, subdir="license")
        assert not failed, failed
        assert len(moved) == 3
        assert not any(path.exists() for path in files)
        assert store.manifest_path().is_file()
        restored, errors = actions.restore_backup(store.dir)
        assert not errors, errors
        assert restored == 3
        for index, path in enumerate(files):
            assert path.read_text(encoding="utf-8") == f"license-{index}"


def test_license_cleanup_targets_bf3() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name in ("71067.dlf", "70619.dlf", "999999.dlf"):
            (root / name).write_text("x", encoding="utf-8")
        game = make_game()
        files, cache_items = actions.license_cleanup_targets(game, root)
        names = sorted(path.name for path in files)
        assert names == ["70619.dlf", "71067.dlf"], names
        assert isinstance(cache_items, list)
        other = discovery.InstalledGame(
            key="other", name="Other", name_cn="", aliases=[], install_dir=None, exe=None,
            steam_appid=None, platform="ea", installed=True, accent=("#000", "#111"),
        )
        files_all, _ = actions.license_cleanup_targets(other, root)
        assert len(files_all) == 3


def test_dry_run_chain() -> None:
    ctx = actions.RepairContext(
        settings=Settings(),
        log=EventLog(),
        game=make_game(),
        issue=make_issue(),
        dry_run=True,
        profile="quick",
        verify_timeout=30,
    )
    with tempfile.TemporaryDirectory() as tmp:
        ctx.backup = actions.BackupStore(root=Path(tmp) / "backups", label="unit-test")
        started: list[str] = []
        callbacks = actions.RunnerCallbacks(
            on_start=lambda step: started.append(step.id),
        )
        runner = actions.RepairRunner(ctx, "quick", callbacks)
        runner.run()  # 同步执行，避免线程带来的不确定性

        expected = [step.id for step in actions.build_plan("quick")]
        assert started == expected, (started, expected)
        assert set(ctx.results) == set(expected), ctx.results
        for step_id, result in ctx.results.items():
            assert result.status in ("ok", "warn", "fail", "skip", "simulated"), (step_id, result)
        assert ctx.concluded, "conclude 步骤必须生成结论"
        assert ctx.concluded.get("report")
        assert ctx.concluded.get("analysis")
        # dry-run 不允许真正改动系统：关闭弹窗 / 启动 / 缓存清理都应是 simulated
        for simulated_step in ("close_dialog", "launch", "verify"):
            assert ctx.results[simulated_step].status == "simulated", ctx.results[simulated_step]


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"actions: {len(tests)} tests passed")
