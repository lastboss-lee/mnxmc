#!/bin/bash
# =============================================================================
# apply_sudoers.sh
# MNXMC sudoers NOPASSWD 설정 단독 적용 스크립트
#
# [용도] install_packages.sh 전체 실행 없이 sudoers만 빠르게 적용/재적용
# [사용법] sudo bash packages/apply_sudoers.sh
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SUDOERS_SRC="$SCRIPT_DIR/sudoers_mnxmc"
SUDOERS_DEST="/etc/sudoers.d/mnxmc"

# sudo 구현 판별. Ubuntu 26.04 는 update-alternatives 우선순위(sudo-rs 50 >
# sudo 40) 때문에 /usr/bin/sudo 가 sudo-rs 다. visudo 도 같은 alternatives
# 그룹의 slave 이므로 아래 검증은 실제 런타임 파서로 이루어진다.
SUDO_REAL="$(readlink -f /etc/alternatives/sudo 2>/dev/null)"
[ -n "$SUDO_REAL" ] || SUDO_REAL="$(command -v sudo 2>/dev/null)"
case "$SUDO_REAL" in
    */cargo/bin/sudo) SUDO_IMPL="sudo-rs" ;;
    "")               SUDO_IMPL="none" ;;
    *)                SUDO_IMPL="sudo (1.9)" ;;
esac

GREEN="\033[0;32m"; YELLOW="\033[1;33m"; RED="\033[0;31m"; NC="\033[0m"
ok()   { echo -e "  ${GREEN}[OK]${NC}    $*"; }
warn() { echo -e "  ${YELLOW}[WARN]${NC}  $*"; }
fail() { echo -e "  ${RED}[FAIL]${NC}  $*"; }

echo ""
echo "============================================================"
echo "  MNXMC sudoers 적용"
echo "  sudo: $SUDO_IMPL"
echo "  src : $SUDOERS_SRC"
echo "  dest: $SUDOERS_DEST"
echo "============================================================"
echo ""

if [ "$(id -u)" -ne 0 ]; then
    fail "root 권한이 필요합니다."
    echo "       실행 방법: sudo bash $0"
    exit 1
fi

if [ ! -f "$SUDOERS_SRC" ]; then
    fail "소스 파일 없음: $SUDOERS_SRC"
    exit 1
fi

# 반드시 "복사 전에" 소스를 검증한다.
# 먼저 덮어쓰고 나중에 검증하면, 파싱 실패 시 rm 으로 기존 정상 파일까지
# 날아가 sands 가 모든 NOPASSWD 권한을 잃는다 (SSH TUI 전체 마비).
# sudo-rs 는 인자 wildcard 와 미지원 Defaults(requiretty 등)를 거부한다.
if ! visudo -c -f "$SUDOERS_SRC" >/dev/null 2>&1; then
    fail "sudoers 문법 검증 실패 — 파서: $SUDO_IMPL"
    visudo -c -f "$SUDOERS_SRC" 2>&1 | sed 's/^/       /'
    echo "       기존 $SUDOERS_DEST 는 변경하지 않았습니다."
    exit 1
fi

if [ -f "$SUDOERS_DEST" ] && cmp -s "$SUDOERS_SRC" "$SUDOERS_DEST"; then
    ok "sudoers 이미 최신 상태 — 건너뜀 ($SUDO_IMPL 검증 통과)"
else
    install -m 440 -o root -g root "$SUDOERS_SRC" "$SUDOERS_DEST"
    ok "sudoers 적용 완료: $SUDOERS_DEST ($SUDO_IMPL 검증 통과)"
fi

echo ""
echo "[검증] sudo -n -u sands 테스트..."

# reboot/shutdown 권한 확인 (실제 실행 없이 -l로 목록 확인)
sudo -l -U sands 2>/dev/null | grep -E "reboot|shutdown|fio|install|tee" | while read -r line; do
    echo "  $line"
done

echo ""
ok "완료. SSH 재접속 없이 즉시 적용됩니다."
echo ""
