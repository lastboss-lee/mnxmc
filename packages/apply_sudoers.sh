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

GREEN="\033[0;32m"; YELLOW="\033[1;33m"; RED="\033[0;31m"; NC="\033[0m"
ok()   { echo -e "  ${GREEN}[OK]${NC}    $*"; }
warn() { echo -e "  ${YELLOW}[WARN]${NC}  $*"; }
fail() { echo -e "  ${RED}[FAIL]${NC}  $*"; }

echo ""
echo "============================================================"
echo "  MNXMC sudoers 적용"
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

cp "$SUDOERS_SRC" "$SUDOERS_DEST"
chmod 440 "$SUDOERS_DEST"

if visudo -c -f "$SUDOERS_DEST" 2>/dev/null; then
    ok "sudoers 적용 완료: $SUDOERS_DEST"
else
    fail "sudoers 문법 오류 — 원본 확인 필요"
    rm -f "$SUDOERS_DEST"
    exit 1
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
