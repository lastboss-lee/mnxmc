#!/usr/bin/env python3.12
"""ServiceScreen 인증 경로 자체 점검.

실행: python3.12 packages/test_auth_fallback.py

배경: 비root 에서 spwd.getspnam() 이 던지는 예외가 OS 마다 다르다.
  22.04 (nsswitch `shadow: files`)         → PermissionError
  26.04 (nsswitch `shadow: files systemd`) → KeyError
예전 코드는 KeyError 를 "User not found" 로 즉시 반환해 26.04 의 비root(SSH)
세션에서 su PAM fallback 에 도달하지 못했다 → Service Manager 인증 진입 불가.

여기서 지키려는 불변식:
  1. 비root 는 예외 종류와 무관하게 su fallback 으로 간다
  2. root 는 shadow 로만 판정하고, shadow 를 못 읽으면 "거부" 한다 (우회 금지)
  3. root 는 절대 su fallback 을 쓰지 않는다 (root 는 암호 없이 su 통과)
"""
import sys
from unittest import mock

sys.path.insert(0, "/mnxmc")
import app.screens.service as svc  # noqa: E402

HASH = "$6$salt$storedhashvalue"
results = []

def check(desc, got, expected):
    ok = got == expected
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {desc}\n         기대={expected} 실제={got}")

def run(euid, getspnam=None, su_ret=(True, None), user_exists=True):
    """authenticate() 를 지정한 조건에서 실행."""
    am = svc.AuthenticationManager()
    pw_ok = mock.DEFAULT if user_exists else KeyError("no user")
    with mock.patch.object(svc.os, "geteuid", return_value=euid), \
         mock.patch.object(svc.pwd, "getpwnam",
                           side_effect=None if user_exists else KeyError("x")), \
         mock.patch.object(svc.AuthenticationManager, "_verify_with_su",
                           return_value=su_ret) as su:
        if getspnam is not None:
            with mock.patch.object(svc.spwd, "getspnam", **getspnam), \
                 mock.patch.object(svc.crypt, "crypt",
                                   side_effect=lambda p, h: HASH if p == "good" else "$6$nope"):
                out = am.authenticate("sands", "good")
        else:
            out = am.authenticate("sands", "good")
        return out, su.called

print(__doc__.split("여기서")[0].strip()[:0] or "=== 인증 경로 ===")

# 1) 비root: PermissionError (22.04 형) → su fallback
out, su_called = run(1000, {"side_effect": PermissionError(13, "denied")})
check("비root + PermissionError → su fallback 사용", (out, su_called), ((True, None), True))

# 2) 비root: KeyError (26.04 형) → su fallback  ← 이번 회귀의 핵심
out, su_called = run(1000, {"side_effect": KeyError("getspnam(): name not found")})
check("비root + KeyError(26.04) → su fallback 사용", (out, su_called), ((True, None), True))

# 3) 비root: su 가 거부하면 거부
out, su_called = run(1000, {"side_effect": KeyError("x")}, su_ret=(False, "Invalid password"))
check("비root + su 거부 → 거부", (out, su_called), ((False, "Invalid password"), True))

# 4) root + 올바른 암호 → shadow 로 통과, su 미사용
out, su_called = run(0, {"return_value": mock.Mock(sp_pwdp=HASH)})
check("root + 정상 암호 → 통과, su 미사용", (out, su_called), ((True, None), False))

# 5) root + shadow 읽기 실패 → 거부 (우회 금지)
out, su_called = run(0, {"side_effect": PermissionError(13, "denied")})
check("root + shadow 실패 → 거부, su 미사용", (out, su_called),
      ((False, "Authentication failed"), False))

# 6) root + 잠긴 계정 → 거부
out, su_called = run(0, {"return_value": mock.Mock(sp_pwdp="!")})
check("root + 잠긴 계정 → 거부", (out, su_called),
      ((False, "Account locked or no password"), False))

# 7) 존재하지 않는 계정 → passwd 단계에서 거부
out, su_called = run(1000, user_exists=False)
check("없는 계정 → User not found, su 미사용", (out, su_called),
      ((False, "User not found"), False))

failed = results.count(False)
print(f"\n  실패 {failed}건 / 전체 {len(results)}건")
sys.exit(1 if failed else 0)
