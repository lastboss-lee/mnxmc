#!/usr/bin/env python3.12
"""RAID CLI probe 판정 자체 점검.

실행: python3.12 packages/test_raid_probe.py

여기서 잡는 것은 실제로 발생했던 오탐이다:
storcli2 는 지원 대상이 아닌 컨트롤러에도 "Status = Success" 를 리턴하고
"Description = No Controller found" 를 덧붙인다. Status 만 보고 판정하면
컨트롤러가 없는 CLI 를 채택해 Disk Info 가 빈 화면이 된다.
"""
import subprocess
import sys
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, "/mnxmc")
from app.screens.system import SystemScreen  # noqa: E402

# (설명, CLI stdout, 기대 판정)
CASES = [
    (
        "컨트롤러 있음 (storcli 007.x, MegaRAID 9560-8i 실측)",
        "CLI Version = 007.2203.0000.0000\nController = 0\nStatus = Success\n"
        "Description = None\n\nProduct Name = MegaRAID 9560-8i 4GB\n",
        True,
    ),
    (
        "컨트롤러 없음 (storcli2 008.x 실측) — 오탐 방지 대상",
        "CLI Version = 008.0016.0000.0011\nStatus = Success\n"
        "Description = No Controller found\n",
        False,
    ),
    (
        "대소문자 변형",
        "Status = Success\nDescription = no controller found\n",
        False,
    ),
    (
        "CLI 실패",
        "Status = Failure\nDescription = something went wrong\n",
        False,
    ),
    (
        "빈 출력",
        "",
        False,
    ),
]

def run():
    failed = 0
    for desc, stdout, expected in CASES:
        with mock.patch.object(
            subprocess, "run",
            return_value=SimpleNamespace(returncode=0, stdout=stdout, stderr=""),
        ):
            got = SystemScreen._probe_cli("megaraid", "/usr/local/bin/storcli64")
        mark = "PASS" if got == expected else "FAIL"
        if got != expected:
            failed += 1
        print(f"  [{mark}] {desc}: 기대={expected} 실제={got}")

    # graid 는 종료코드로 판정한다
    for rc, expected in ((0, True), (1, False)):
        with mock.patch.object(
            subprocess, "run",
            return_value=SimpleNamespace(returncode=rc, stdout="", stderr=""),
        ):
            got = SystemScreen._probe_cli("graid", "/usr/bin/graidctl")
        mark = "PASS" if got == expected else "FAIL"
        if got != expected:
            failed += 1
        print(f"  [{mark}] graid rc={rc}: 기대={expected} 실제={got}")

    print(f"\n  실패 {failed}건")
    return failed

if __name__ == "__main__":
    print("=== RAID CLI probe 판정 ===")
    sys.exit(1 if run() else 0)
