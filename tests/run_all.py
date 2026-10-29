"""运行全部测试：python tests/run_all.py"""

from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MODULES = (
    "test_config",
    "test_detector",
    "test_discovery",
    "test_actions",
    "test_chain",
    "test_integration_window",
)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    passed = 0
    failed: list[tuple[str, str]] = []
    for name in MODULES:
        try:
            module = importlib.import_module(name)
        except Exception:
            failed.append((name, traceback.format_exc()))
            print(f"[FAIL] {name} 导入失败")
            continue
        tests = [value for attr, value in sorted(vars(module).items()) if attr.startswith("test_") and callable(value)]
        print(f"[{name}] {len(tests)} 项")
        for test in tests:
            try:
                test()
            except Exception:
                failed.append((f"{name}.{test.__name__}", traceback.format_exc()))
                print(f"  FAIL {test.__name__}")
            else:
                passed += 1
                print(f"  ok   {test.__name__}")
    print()
    if failed:
        print(f"失败 {len(failed)} 项：")
        for name, detail in failed:
            print(f"- {name}\n{detail}")
        return 1
    print(f"全部通过：{passed} 项测试")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
