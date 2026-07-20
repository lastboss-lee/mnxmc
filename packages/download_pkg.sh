#!/bin/bash
# =============================================================================
# download_pkg.sh
# MNX 오프라인 패키지 다운로드 스크립트
#
# [용도] 온라인 환경에서 실행 → packages/ 디렉토리를 오프라인 대상 서버에 복사
# [설치] sudo bash packages/install_packages.sh
#
# [사용법]
#   bash download_pkg.sh            # 이 스크립트 위치에 저장
#   bash download_pkg.sh /tmp/pkg   # 지정 디렉토리에 저장
#
# [디렉토리 구조 생성]
#   <출력>
#     ├── apt/      ← *.deb (python3.12, smartmontools 등 + 전체 의존성)
#     ├── pip/      ← *.whl (textual, rich 등)
#     └── storcli/  ← 수동 배치 필요 (Broadcom 공식 배포만 가능)
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PKG_DIR="${1:-$SCRIPT_DIR}"

APT_DIR="$PKG_DIR/apt"
PIP_DIR="$PKG_DIR/pip"
STORCLI_DIR="$PKG_DIR/storcli"

GREEN="\033[0;32m"; YELLOW="\033[1;33m"; RED="\033[0;31m"; NC="\033[0m"
ok()   { echo -e "  ${GREEN}[OK]${NC}    $*"; }
warn() { echo -e "  ${YELLOW}[WARN]${NC}  $*"; }
fail() { echo -e "  ${RED}[FAIL]${NC}  $*"; }

echo ""
echo "============================================================"
echo "  MNX Package Downloader"
echo "  apt  → $APT_DIR"
echo "  pip  → $PIP_DIR"
echo "============================================================"
echo ""

mkdir -p "$APT_DIR" "$PIP_DIR"

# ── [1/3] apt 패키지 + 전체 의존성 다운로드 ─────────────────────────────────
echo "[1/3] apt 패키지 다운로드 (의존성 포함)..."

TARGET_PKGS=(
    python3.12
    python3.12-venv
    python3-pip
    python3-setuptools
    python3-wheel
    libpython3.12-stdlib
    smartmontools
    unzip
    tcpreplay
    snmpd
    snmp
    libsnmp-dev
    snmp-mibs-downloader
    ntp
    htop
    sysstat
    nmon
    iotop
    fio
    curl
    ethtool
    dmidecode
    nfs-common
    iotop
    ipset
)

echo "  → 의존성 트리 수집 중..."
ALL_PKGS=$(apt-cache depends --recurse \
    --no-recommends --no-suggests \
    --no-conflicts --no-breaks --no-replaces --no-enhances \
    "${TARGET_PKGS[@]}" 2>/dev/null \
    | grep "^\w" | sort -u)

if [ -z "$ALL_PKGS" ]; then
    fail "apt-cache 에서 패키지 정보를 가져오지 못했습니다."
    echo "     apt-get update 후 재시도하세요."
    exit 1
fi

PKG_COUNT=$(echo "$ALL_PKGS" | wc -w)
echo "  → 총 ${PKG_COUNT}개 패키지 다운로드 중 (이미 있는 파일은 건너뜀)..."

cd "$APT_DIR"

FAILED=0
SKIPPED=0
DOWNLOADED=0

for pkg in $ALL_PKGS; do
    result=$(apt-get download "$pkg" 2>&1)
    exit_code=$?
    if [ $exit_code -eq 0 ]; then
        DOWNLOADED=$((DOWNLOADED + 1))
    elif echo "$result" | grep -qi "is already the newest\|already downloaded\|already installed"; then
        SKIPPED=$((SKIPPED + 1))
    else
        # virtual package 또는 다운로드 불가 패키지는 경고만 출력
        if apt-cache show "$pkg" &>/dev/null; then
            warn "다운로드 실패: $pkg"
            FAILED=$((FAILED + 1))
        else
            # virtual package — 건너뜀 (정상)
            SKIPPED=$((SKIPPED + 1))
        fi
    fi
done

ACTUAL=$(ls "$APT_DIR"/*.deb 2>/dev/null | wc -l)
echo ""
echo "  다운로드: ${DOWNLOADED}개 | 기존파일: ${SKIPPED}개 | 실패: ${FAILED}개"
ok "apt/ .deb 합계: ${ACTUAL}개"

if [ "$FAILED" -gt 0 ]; then
    warn "일부 패키지 다운로드 실패 — 오프라인 설치 시 의존성 오류 발생 가능"
fi

echo ""

# ── [2/3] pip 패키지 다운로드 ────────────────────────────────────────────────
echo "[2/3] pip 패키지 다운로드..."

if ! command -v python3.12 &>/dev/null; then
    warn "python3.12 없음 — pip 다운로드 건너뜀"
    warn "python3.12 설치 후 재실행하거나 pip/*.whl 파일을 수동으로 배치하세요."
else
    python3.12 -m pip download \
        textual \
        rich \
        requests \
        --dest "$PIP_DIR" \
        --quiet 2>&1

    WHL_COUNT=$(ls "$PIP_DIR"/*.whl 2>/dev/null | wc -l)
    if [ "$WHL_COUNT" -gt 0 ]; then
        ok "pip/ .whl 합계: ${WHL_COUNT}개"
    else
        fail "pip 패키지 다운로드 실패"
    fi
fi

echo ""

# ── [3/3] StorCLI 확인 ───────────────────────────────────────────────────────
echo "[3/3] StorCLI 확인..."

STORCLI_COUNT=$(ls "$STORCLI_DIR"/*.deb 2>/dev/null | wc -l)
if [ "$STORCLI_COUNT" -gt 0 ]; then
    ok "storcli/ .deb 확인: ${STORCLI_COUNT}개"
    ls "$STORCLI_DIR"/*.deb | while read f; do echo "       $(basename "$f")"; done
else
    warn "storcli/ 폴더에 .deb 없음"
    echo "       Broadcom 공식 배포본을 수동으로 배치하세요:"
    echo "       https://docs.broadcom.com → MegaRAID Storage Software → StorCLI"
    echo "       배치 경로: $STORCLI_DIR/<storcli_xxx_all.deb>"
fi

# ── 최종 요약 ─────────────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "  다운로드 요약"
printf "  %-10s %s\n" "apt/"    "$(ls "$APT_DIR"/*.deb 2>/dev/null | wc -l)개 .deb"
printf "  %-10s %s\n" "pip/"    "$(ls "$PIP_DIR"/*.whl 2>/dev/null | wc -l)개 .whl"
printf "  %-10s %s\n" "storcli/" "$(ls "$STORCLI_DIR"/*.deb 2>/dev/null | wc -l)개 .deb"
echo "============================================================"
echo ""
echo "  [다음 단계]"
echo "  1. packages/ 디렉토리 전체를 오프라인 서버에 복사"
echo "  2. sudo bash packages/install_packages.sh"
echo "============================================================"
echo ""
