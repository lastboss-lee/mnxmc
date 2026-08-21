#!/bin/bash
# =============================================================================
# test_os_split.sh — 22.04/26.04 패키지 분리 + sudo-rs 호환성 자체 점검
#
# 실행: bash packages/test_os_split.sh      (root 불필요)
#
# 여기서 잡는 것은 "조용히 26.04 를 깨뜨리는" 회귀들이다:
#   - sudoers 에 인자 wildcard 나 미지원 Defaults 가 다시 들어오는 것
#     (sudo-rs 파싱 에러 → 파일 전체 거부 → sands 권한 전무)
#   - suite 디렉토리에 python3.12 나 시각동기화 데몬이 빠지는 것
#   - install_packages.sh 의 OS 분기가 사라지는 것
# =============================================================================
cd "$(dirname "$0")" || exit 1

PASS=0; FAIL=0
ok()   { echo "  [PASS] $*"; PASS=$((PASS+1)); }
bad()  { echo "  [FAIL] $*"; FAIL=$((FAIL+1)); }

echo "=== sudoers (sudo 1.9 + sudo-rs 양쪽 파싱 가능해야 함) ==="

SUDOERS=sudoers_mnxmc
if [ ! -f "$SUDOERS" ]; then
    bad "$SUDOERS 없음"
else
    # 규칙 라인만 추출 (주석/빈줄 제외)
    RULES=$(grep -vE '^[[:space:]]*(#|$)' "$SUDOERS")

    # 1) 인자 위치 wildcard 금지 — sudo-rs 는 파싱 에러로 처리한다
    if echo "$RULES" | grep -q '\*'; then
        bad "인자 wildcard 발견 (sudo-rs 파싱 에러):"
        echo "$RULES" | grep '\*' | sed 's/^/         /'
    else
        ok "인자 wildcard 없음"
    fi

    # 2) Defaults 는 sudo-rs 지원 파라미터만 (requiretty 등 금지)
    DEF=$(echo "$RULES" | grep '^Defaults')
    if [ -n "$DEF" ]; then
        SUPPORTED='noexec|noninteractive_auth|env_editor|pwfeedback|rootpw|setenv|targetpw|umask_override|use_pty|passwd_tries|timestamp_timeout|umask|editor|apparmor_profile|secure_path|env_check|env_keep'
        BADDEF=$(echo "$DEF" | grep -vE "!?($SUPPORTED)")
        if [ -n "$BADDEF" ]; then
            bad "sudo-rs 미지원 Defaults 파라미터:"
            echo "$BADDEF" | sed 's/^/         /'
        else
            ok "Defaults 파라미터 모두 sudo-rs 지원 목록 내"
        fi
    else
        ok "Defaults 라인 없음 (가장 안전)"
    fi

    # 3) 현재 시스템 파서로 문법 검증
    if command -v visudo >/dev/null 2>&1; then
        if visudo -c -f "$SUDOERS" >/dev/null 2>&1; then
            ok "visudo -c 통과"
        else
            bad "visudo -c 실패: $(visudo -c -f "$SUDOERS" 2>&1 | head -1)"
        fi
    else
        echo "  [SKIP] visudo 없음"
    fi

    # 4) 코드가 실제로 쓰는 경로가 규칙에 있는지 (netplan chmod 회귀 방지)
    for path in /etc/netplan/70-netplan-set.yaml /etc/netplan/50-cloud-init.yaml; do
        if echo "$RULES" | grep -q "chmod 600 $path"; then
            ok "chmod 규칙 존재: $path"
        else
            bad "chmod 600 $path 규칙 없음 (netplan 쓰기 후 권한 설정 실패)"
        fi
    done
fi

echo ""
echo "=== apt suite 디렉토리 ==="

# suite → 그 suite 에만 있어야 하는 시각동기화 데몬
check_suite() {
    local suite="$1" want="$2" notwant="$3"
    local dir="apt/$suite"

    if [ ! -d "$dir" ]; then
        bad "$dir 없음 — bash download_pkg.sh --suite $suite 필요"
        return
    fi

    local n; n=$(ls "$dir"/*.deb 2>/dev/null | wc -l)
    if [ "$n" -gt 0 ]; then ok "$dir: ${n}개 .deb"; else bad "$dir 비어 있음"; fi

    if ls "$dir"/python3.12_*.deb >/dev/null 2>&1; then
        ok "$dir: python3.12 포함 ($(basename "$(ls "$dir"/python3.12_*.deb | head -1)"))"
    else
        bad "$dir: python3.12 .deb 없음 — MNXMC 런타임 누락"
    fi

    if ls "$dir"/${want}_*.deb >/dev/null 2>&1; then
        ok "$dir: 시각동기화 $want 포함"
    else
        bad "$dir: 시각동기화 $want 없음"
    fi

    if ls "$dir"/${notwant}_*.deb >/dev/null 2>&1; then
        bad "$dir: $notwant 가 있음 — 이 suite 에는 없어야 함"
    else
        ok "$dir: $notwant 없음 (정상)"
    fi
}

check_suite jammy    ntp    chrony
check_suite resolute chrony ntp

echo ""
echo "=== install_packages.sh OS 분기 ==="

for tok in 'jammy)' 'resolute)' 'TIME_DAEMON' 'apt/$OS_CODENAME' 'SUDO_IMPL'; do
    if grep -qF -- "$tok" install_packages.sh; then
        ok "분기 토큰 존재: $tok"
    else
        bad "분기 토큰 없음: $tok"
    fi
done

# 미지원 OS 는 조용히 넘어가지 말고 종료해야 한다
if grep -q "지원하지 않는 OS" install_packages.sh && grep -q "exit 1" install_packages.sh; then
    ok "미지원 OS 는 exit 1 (조용한 오설치 방지)"
else
    bad "미지원 OS 처리 없음 — 잘못된 OS 에 설치될 수 있음"
fi

echo ""
echo "=== promisc@ 템플릿 유닛 ==="

if [ -f config/promisc@.service ]; then
    ok "config/promisc@.service 존재"
    grep -q '%i' config/promisc@.service \
        && ok "인스턴스 치환자 %i 사용" \
        || bad "%i 없음 — 템플릿 유닛이 아님"
else
    bad "config/promisc@.service 없음"
fi

# 코드가 템플릿 유닛을 쓰는지 (구 tee 방식 회귀 방지)
NC=../network_management/network_config.py
if grep -q 'promisc@' "$NC"; then
    ok "network_config.py: promisc@ 템플릿 사용"
else
    bad "network_config.py: promisc@ 미사용"
fi
if grep -q "tee.*promisc-" "$NC"; then
    bad "network_config.py: 구 tee 방식 잔존 (sudo-rs 에서 깨짐)"
else
    ok "network_config.py: 구 tee 방식 없음"
fi

echo ""
echo "============================================================"
echo "  PASS: $PASS   FAIL: $FAIL"
echo "============================================================"
[ "$FAIL" -eq 0 ]
