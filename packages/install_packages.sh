#!/bin/bash
# =============================================================================
# install_packages.sh
# MNX Package Installer — apt + pip + storcli + perccli 원스톱 설치
#
# [용도] 오프라인 환경 설치 (네트워크 불필요)
# [사용법] sudo bash install_packages.sh      ← OS 자동 판별
#
# [지원 OS] Ubuntu 22.04 (jammy) / Ubuntu 26.04 (resolute)
#   apt 패키지 세트는 OS 별로 분리되어 있고 /etc/os-release 의 VERSION_CODENAME
#   으로 자동 선택한다. python3.12 런타임과 pip/*.whl 은 두 OS 공용이다.
#
# [디렉토리 구조 (이 스크립트 기준)]
#   packages/
#     ├── install_packages.sh       ← 이 파일
#     ├── apt/jammy/    *.deb       ← Ubuntu 22.04 용 (python3.12 + 의존성)
#     ├── apt/resolute/ *.deb       ← Ubuntu 26.04 용 (python3.12 + 의존성)
#     ├── pip/    *.whl             ← textual, rich 등 (공용)
#     ├── config/ *.conf, *.service ← getty override, promisc@ 템플릿 유닛
#     ├── storcli/ *.deb           ← storcli 패키지 (MegaRAID/LSI 계열)
#     └── perccli/ perccli perccli64  ← Dell PERC 바이너리
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PIP_DIR="$SCRIPT_DIR/pip"
STORCLI_DIR="$SCRIPT_DIR/storcli"
PERCCLI_DIR="$SCRIPT_DIR/perccli"
PYTHON="python3.12"
STORCLI_BIN="/opt/MegaRAID/storcli/storcli64"
STORCLI_LINK="/usr/local/bin/storcli64"
STORCLI2_BIN="/opt/MegaRAID/storcli2/storcli2"
STORCLI2_LINK="/usr/local/bin/storcli2"
PERCCLI_DEST="/opt/MegaRAID/perccli"
PERCCLI_BIN="$PERCCLI_DEST/perccli"
PERCCLI64_BIN="$PERCCLI_DEST/perccli64"
PERCCLI_LINK="/usr/local/bin/perccli"
PERCCLI64_LINK="/usr/local/bin/perccli64"
GRAIDCTL_BIN="/usr/bin/graidctl"

GREEN="\033[0;32m"; YELLOW="\033[1;33m"; RED="\033[0;31m"; NC="\033[0m"
ok()   { echo -e "  ${GREEN}[OK]${NC}    $*"; }
warn() { echo -e "  ${YELLOW}[WARN]${NC}  $*"; }
fail() { echo -e "  ${RED}[FAIL]${NC}  $*"; }

# ── OS 판별 (22.04 / 26.04 apt 패키지 세트 분리) ─────────────────────────────
. /etc/os-release 2>/dev/null
OS_CODENAME="${VERSION_CODENAME:-unknown}"
OS_VERSION="${VERSION_ID:-unknown}"
OS_PRETTY="${PRETTY_NAME:-$OS_CODENAME}"

case "$OS_CODENAME" in
    jammy)    TIME_DAEMON="ntp" ;;      # 22.04
    resolute) TIME_DAEMON="chrony" ;;   # 26.04 — ntp 패키지 제거됨
    *)
        fail "지원하지 않는 OS: $OS_PRETTY ($OS_VERSION / $OS_CODENAME)"
        echo "       지원 OS: Ubuntu 22.04 (jammy), Ubuntu 26.04 (resolute)"
        echo "       패키지 세트를 먼저 준비하세요:"
        echo "         bash packages/download_pkg.sh --suite <codename>"
        exit 1
        ;;
esac

# ── sudo 구현 판별 ──────────────────────────────────────────────────────────
# Ubuntu 26.04 는 sudo(1.9) 와 sudo-rs 를 모두 설치하고, update-alternatives
# 우선순위가 sudo-rs 50 > sudo 40 이므로 /usr/bin/sudo 는 sudo-rs 가 된다.
# sudo-rs 는 sudoers 인자 wildcard 를 파싱 에러로 처리하고 requiretty 등
# 일부 Defaults 파라미터를 지원하지 않는다 → sudoers_mnxmc 검증이 필수.
SUDO_REAL="$(readlink -f /etc/alternatives/sudo 2>/dev/null)"
[ -n "$SUDO_REAL" ] || SUDO_REAL="$(command -v sudo 2>/dev/null)"
case "$SUDO_REAL" in
    */cargo/bin/sudo) SUDO_IMPL="sudo-rs" ;;
    "")               SUDO_IMPL="none" ;;
    *)                SUDO_IMPL="sudo (1.9)" ;;
esac

APT_DIR="$SCRIPT_DIR/apt/$OS_CODENAME"
if [ ! -d "$APT_DIR" ]; then
    # 구 레이아웃(apt/ 평면 구조) 호환 — 2.3.x 이전 배포본
    if ls "$SCRIPT_DIR/apt"/*.deb >/dev/null 2>&1; then
        APT_DIR="$SCRIPT_DIR/apt"
    else
        fail "apt 패키지 디렉토리 없음: $SCRIPT_DIR/apt/$OS_CODENAME"
        echo "       bash packages/download_pkg.sh --suite $OS_CODENAME 로 준비하세요."
        exit 1
    fi
fi

echo ""
echo "============================================================"
echo "  MNX Package Installer (Offline)"
echo "  OS      : $OS_PRETTY  ($OS_CODENAME)"
echo "  sudo    : $SUDO_IMPL"
echo "  apt     : $APT_DIR"
echo "  pip     : $PIP_DIR"
echo "  storcli : $STORCLI_DIR"
echo "  perccli : $PERCCLI_DIR"
echo "============================================================"
echo ""

# ── root 확인 ────────────────────────────────────────────────────────────────
if [ "$(id -u)" -ne 0 ]; then
    fail "root 권한이 필요합니다."
    echo "       실행 방법: sudo bash $0"
    exit 1
fi

# ── 기존 tty(getty@tty1) 재시작 ──────────────────────────────────────────────
# 설치 본작업 전에 현재 콘솔에서 돌고 있는 기존 TUI 세션을 먼저 정리한다.
# (새 override.conf 적용/재시작은 [6/8] 단계에서 별도 수행)
echo "[0/0] 기존 getty@tty1 재시작..."
systemctl restart getty@tty1 2>/dev/null || true
ok "getty@tty1 재시작 요청 완료"

# ── [0/0] Timezone 설정 (KST, UTC+9) ────────────────────────────────────────
echo "[0/0] Timezone 설정..."

CURRENT_TZ=$(timedatectl show --property=Timezone --value 2>/dev/null)
if [ "$CURRENT_TZ" = "Asia/Seoul" ]; then
    ok "Timezone 이미 Asia/Seoul (KST) — 건너뜀"
else
    timedatectl set-timezone Asia/Seoul
    if [ $? -eq 0 ]; then
        ok "Timezone 설정 완료: Asia/Seoul (KST, UTC+9)"
    else
        warn "timedatectl 실패 — /etc/localtime 직접 설정 시도"
        ln -sf /usr/share/zoneinfo/Asia/Seoul /etc/localtime
        echo "Asia/Seoul" > /etc/timezone
        ok "Timezone 설정 완료 (fallback): Asia/Seoul (KST, UTC+9)"
    fi
fi

echo ""

# ── [0/0] 콘솔 커널 메시지 억제 (영구) ───────────────────────────────────────
# tty1 은 MNXMC TUI 전용 콘솔이다. 커널/드라이버 메시지(특히 10G 미러 NIC 의
# link up-down, ethtool)가 KERN_WARNING 으로 찍히면 TUI 화면을 덮어버린다.
# console_loglevel 을 1(KERN_ALERT 이상만)로 영구 고정한다.
# 커널 메시지는 dmesg / journalctl -k 로 확인한다.
echo "[0/0] 콘솔 커널 메시지 억제 설정..."
cat > /etc/sysctl.d/99-mnxmc-console.conf <<'SYSCTL'
# MNXMC: tty1 은 TUI 전용 콘솔이므로 커널 메시지를 콘솔에 출력하지 않는다.
# 형식: console_loglevel default_message_loglevel minimum_console_loglevel default_console_loglevel
kernel.printk = 1 4 1 7
SYSCTL
if sysctl -q -p /etc/sysctl.d/99-mnxmc-console.conf 2>/dev/null; then
    ok "kernel.printk = 1 4 1 7 적용 (현재: $(cut -f1 /proc/sys/kernel/printk))"
else
    warn "sysctl 적용 실패 — 재부팅 후 적용됨"
fi

echo ""

# ── [1/3] apt .deb 설치 ──────────────────────────────────────────────────────
echo "[1/3] apt 패키지 설치..."

DEB_COUNT=$(ls "$APT_DIR"/*.deb 2>/dev/null | wc -l)

if [ "$DEB_COUNT" -eq 0 ]; then
    warn "apt/ 폴더에 .deb 파일 없음 — 건너뜀"
else
    # 이미 동일 버전 이상이 설치된 패키지는 skip
    INSTALL_LIST=()
    SKIP_COUNT=0
    for deb in "$APT_DIR"/*.deb; do
        pkg=$(dpkg-deb -f "$deb" Package 2>/dev/null)
        ver=$(dpkg-deb -f "$deb" Version 2>/dev/null)
        cur=$(dpkg-query -W -f='${Version}' "$pkg" 2>/dev/null)
        if [ -n "$cur" ] && dpkg --compare-versions "$cur" ge "$ver" 2>/dev/null; then
            SKIP_COUNT=$((SKIP_COUNT + 1))
        else
            INSTALL_LIST+=("$deb")
        fi
    done

    INSTALL_COUNT=${#INSTALL_LIST[@]}
    echo "  → 전체 ${DEB_COUNT}개 중 이미 설치됨 ${SKIP_COUNT}개 skip, ${INSTALL_COUNT}개 설치 진행"

    if [ "$INSTALL_COUNT" -eq 0 ]; then
        ok "모든 패키지 이미 설치됨 — 건너뜀"
    else
        # dpkg 는 의존성 순서를 맞추지 않으므로 최대 3회 반복.
        #
        # --auto-deconfigure : Breaks 기반 전환(t64 전환 등)을 통과시킨다.
        #   예) libsnmp40t64 는 libsnmp40 (<< 5.9.4) 를 Breaks 한다. 구 패키지가
        #   깔려 있으면 dpkg 가 "deconfiguration is not permitted
        #   (--auto-deconfigure might help)" 로 거부한다. 이 플래그는 해당
        #   패키지를 "제거"하지 않고 일시 deconfigure 만 하며, 뒤따르는
        #   `dpkg --configure -a` 가 마무리한다. 제거보다 훨씬 좁은 조치다.
        #
        # dpkg stderr 를 버리지 않는다. 기존에는 2>/dev/null 로 삼켜서
        # 어떤 패키지가 왜 실패했는지 알 수 없었고, 실패해도 성공처럼 보였다.
        DPKG_LOG=$(mktemp)
        for attempt in 1 2 3; do
            if dpkg -i --auto-deconfigure "${INSTALL_LIST[@]}" >"$DPKG_LOG" 2>&1; then
                rm -f "$DPKG_LOG"; DPKG_LOG=""
                break
            fi
            echo "  → [${attempt}/3] 재시도 중 (의존성 순서 해결)..."
        done
        if [ -n "$DPKG_LOG" ]; then
            warn "dpkg -i 가 3회 시도 후에도 오류를 보고했습니다:"
            grep -E "^dpkg: (error|warning)|would break|not permitted" "$DPKG_LOG" \
                | sort -u | head -10 | sed 's/^/       /'
            echo "       전체 로그: $DPKG_LOG"
        fi

        # dpkg 상태 정리 (언팩 상태인 패키지 설정 완료)
        dpkg --configure -a 2>/dev/null || true

        # 오프라인 모드로 깨진 의존성 복구 (네트워크 사용 안 함)
        #
        # --no-remove 는 필수 가드다. apt source 가 비활성이라 apt 가 깨진
        # 의존성을 "고치는" 유일한 수단이 패키지 제거이고, -y 가 그걸 무조건
        # 승인한다. OS 가 어긋난 .deb 세트를 깔면 여기서 ubuntu-minimal,
        # iproute2, netplan.io, perl, curl 까지 줄줄이 제거된다.
        # (실측: 2026-08-21 26.04 장비에 22.04 세트를 넣었다가 80개 제거됨)
        # --no-remove 를 주면 apt 는 제거 대신 실패하고, 아래 경고로 드러난다.
        if ! apt-get install -f -y \
            -o Dir::Etc::SourceList=/dev/null \
            -o Dir::Etc::SourceParts=/dev/null \
            --no-install-recommends \
            --no-remove 2>/dev/null; then
            warn "의존성 자동 복구 실패 — 패키지를 제거하지 않고 중단했습니다"
            warn "apt/$OS_CODENAME 세트가 이 OS와 맞는지 확인하세요 (제거 방지 가드 동작)"
        fi

        # dpkg 상태를 반드시 확인한다.
        # --no-remove 가드가 apt 의 "제거로 해결" 을 막으면 일부 패키지가
        # iU(unpacked, 미설정) 로 남는다. 그 패키지는 파일만 풀린 상태라
        # 실제로 동작하지 않으므로 성공으로 보고하면 안 된다.
        # 대표 원인: 세트에 없는 기존 설치 패키지가 공유 라이브러리 업그레이드로
        # 깨지는 경우(예: 구 libpmemblk1 vs 새 libpmem1).
        BROKEN=$(dpkg -l 2>/dev/null | awk 'NR>5 && $1 !~ /^(ii|rc|un)$/ {print $2}')
        if [ -n "$BROKEN" ]; then
            fail "설정되지 않은(iU) 패키지가 남았습니다 — 해당 기능은 동작하지 않습니다:"
            echo "$BROKEN" | sed 's/^/       /'
            apt-get check 2>&1 | grep -E "^ [a-z0-9]" | sed 's/^/       /' | head -10
            echo "       온라인 장비 복구 : sudo apt-get install -f"
            echo "       오프라인 장비    : 위 미충족 의존 .deb 를 apt/$OS_CODENAME 에 추가 후 재실행"
        else
            ok "${INSTALL_COUNT}개 설치 완료 (${SKIP_COUNT}개 skip, dpkg 상태 정상)"
        fi
    fi
fi

echo ""

# ── [2/3] pip .whl 설치 ──────────────────────────────────────────────────────
echo "[2/3] pip 패키지 설치..."

WHL_COUNT=$(ls "$PIP_DIR"/*.whl 2>/dev/null | wc -l)

if [ "$WHL_COUNT" -eq 0 ]; then
    warn "pip/ 폴더에 .whl 파일 없음 — 건너뜀"
else
    if ! command -v "$PYTHON" &>/dev/null; then
        fail "$PYTHON 없음 — [1/3] apt 설치가 정상 완료되었는지 확인하세요."
        exit 1
    fi

    # pip 없는 경우 ensurepip으로 부트스트랩
    if ! "$PYTHON" -m pip --version &>/dev/null; then
        echo "  → pip 없음 — ensurepip 실행 중..."
        "$PYTHON" -m ensurepip --upgrade 2>/dev/null || true
    fi

    echo "  → ${WHL_COUNT}개 .whl 설치 중 ($PYTHON)..."

    # --break-system-packages : PEP 668 대응 (Ubuntu 23.04+)
    # --ignore-installed      : 26.04 에서 필수다.
    #   netplan.io 가 python3-rich 를 의존으로 끌고 오고, 그게
    #   /usr/lib/python3/dist-packages 에 있어 python3.12 에서도 보인다.
    #   pip 은 dpkg 가 관리하는 패키지를 제거할 수 없어(RECORD 파일 없음)
    #   "Cannot uninstall rich" 로 설치 전체가 중단되고 textual 까지 안 깔린다.
    #   --ignore-installed 로 우리 핀을 /usr/local/lib/python3.12/dist-packages
    #   에 설치한다. sys.path 에서 /usr/local 이 앞이라 우리 버전이 이긴다.
    #   (22.04 의 netplan 0.104 는 python3-rich 의존이 없어 발생하지 않았다)
    PIP_ARGS=( --no-index --find-links="$PIP_DIR" --quiet --ignore-installed )
    "$PYTHON" -m pip install "${PIP_ARGS[@]}" --break-system-packages \
        textual rich requests 2>/dev/null \
    || "$PYTHON" -m pip install "${PIP_ARGS[@]}" textual rich requests

    # 설치 결과를 import 로 확인한다.
    # 기존 코드는 pip 종료코드를 무시하고 무조건 성공을 출력했고, 그래서
    # 26.04 에서 textual 이 없어 TUI 가 기동 불가한 상태가 조용히 지나갔다.
    if "$PYTHON" -c "import textual, rich, requests" 2>/dev/null; then
        ok "${WHL_COUNT}개 .whl 설치 완료 (textual/rich/requests import 확인)"
    else
        fail "pip 설치 실패 — TUI 가 기동하지 않습니다"
        "$PYTHON" -c "import textual, rich, requests" 2>&1 | tail -3 | sed 's/^/       /'
        echo "       확인: $PYTHON -m pip install --no-index --find-links=$PIP_DIR --ignore-installed textual"
    fi
fi

echo ""

# ── [3/4] StorCLI 설치 ───────────────────────────────────────────────────────
echo "[3/4] StorCLI 설치..."

# storcli/ 에는 지원 컨트롤러가 다른 두 패키지가 섞여 있다:
#   storcli  (007.x) → /opt/MegaRAID/storcli/storcli64
#                      MegaRAID 12G SAS (SAS39xx/93xx/94xx/95xx, 예: 9560-8i)
#   storcli2 (008.x) → /opt/MegaRAID/storcli2/storcli2
#                      MegaRAID 9600 계열 (SAS4116)
# 둘은 서로를 대체하지 않으므로 모두 설치해야 한다.
#
# 기존 코드는 `ls "$STORCLI_DIR"/*.deb | head -1` 로 하나만 골랐고,
# 알파벳순에서 'storcli2_' 가 'storcli_' 보다 앞서므로('2'=0x32 < '_'=0x5F)
# 항상 storcli2 만 설치되고 storcli 는 설치되지 않았다.
# 실측(MegaRAID 9560-8i): storcli2 → "Number of Controllers = 0",
#                         storcli 007.2203 → "Product Name = MegaRAID 9560-8i 4GB".
# 즉 이 버그 때문에 SAS39xx 카드가 Disk Info 에서 인식되지 않았다.
if ! ls "$STORCLI_DIR"/*.deb >/dev/null 2>&1; then
    warn "storcli/ 폴더에 .deb 파일 없음 — 건너뜀"
else
    # 같은 패키지명이 여러 버전 있으면(storcli 007.1912 / 007.2203) 최고 버전만
    declare -A SC_DEB=() SC_VER=()
    for deb in "$STORCLI_DIR"/*.deb; do
        pkg=$(dpkg-deb -f "$deb" Package 2>/dev/null) || continue
        ver=$(dpkg-deb -f "$deb" Version 2>/dev/null)
        [ -n "$pkg" ] || continue
        if [ -z "${SC_VER[$pkg]:-}" ] \
           || dpkg --compare-versions "$ver" gt "${SC_VER[$pkg]}" 2>/dev/null; then
            SC_VER["$pkg"]="$ver"; SC_DEB["$pkg"]="$deb"
        fi
    done

    for pkg in "${!SC_DEB[@]}"; do
        deb="${SC_DEB[$pkg]}"
        echo "  → $pkg ${SC_VER[$pkg]} 설치 중 ($(basename "$deb"))..."
        dpkg -i "$deb" >/dev/null 2>&1 \
            || dpkg --force-depends -i "$deb" >/dev/null 2>&1 || true
    done
    dpkg --configure -a >/dev/null 2>&1 || true

    if [ -f "$STORCLI_BIN" ]; then
        ln -sf "$STORCLI_BIN" "$STORCLI_LINK"
        chmod +x "$STORCLI_LINK"
        ok "storcli64 : $STORCLI_LINK → $STORCLI_BIN"
    else
        warn "storcli64 바이너리 없음: $STORCLI_BIN"
    fi

    if [ -f "$STORCLI2_BIN" ]; then
        ln -sf "$STORCLI2_BIN" "$STORCLI2_LINK"
        chmod +x "$STORCLI2_LINK"
        ok "storcli2  : $STORCLI2_LINK → $STORCLI2_BIN"
    else
        warn "storcli2 바이너리 없음: $STORCLI2_BIN"
    fi
fi

# ── [4/4] PercCLI 설치 (Dell PERC H3xx/H7xx 계열) ───────────────────────────
echo "[4/4] PercCLI 설치..."

PERCCLI_FOUND=0

if [ -f "$PERCCLI_DIR/perccli64" ] || [ -f "$PERCCLI_DIR/perccli" ]; then
    mkdir -p "$PERCCLI_DEST"

    if [ -f "$PERCCLI_DIR/perccli64" ]; then
        cp "$PERCCLI_DIR/perccli64" "$PERCCLI64_BIN"
        chmod +x "$PERCCLI64_BIN"
        ln -sf "$PERCCLI64_BIN" "$PERCCLI64_LINK"
        ok "perccli64 설치 완료"
        ok "심볼릭 링크: $PERCCLI64_LINK → $PERCCLI64_BIN"
        PERCCLI_FOUND=1
    fi

    if [ -f "$PERCCLI_DIR/perccli" ]; then
        cp "$PERCCLI_DIR/perccli" "$PERCCLI_BIN"
        chmod +x "$PERCCLI_BIN"
        ln -sf "$PERCCLI_BIN" "$PERCCLI_LINK"
        ok "perccli 설치 완료"
        ok "심볼릭 링크: $PERCCLI_LINK → $PERCCLI_BIN"
        PERCCLI_FOUND=1
    fi
else
    warn "perccli/ 폴더에 바이너리 없음 — 건너뜀 (비 PERC 시스템)"
fi

# ── /mnxmc/raid.cfg 자동 생성 ────────────────────────────────────────────────
echo ""
echo "[raid.cfg] CLI 실행 응답 기반 RAID 컨트롤러 감지 중..."

RAID_CFG="/mnxmc/raid.cfg"
mkdir -p /mnxmc

# storcli/perccli probe: "/call show" 가 실제 컨트롤러를 보고하는지 확인.
#
# "Status = Success" 만 보면 오탐한다. 실측: 지원 대상이 아닌 컨트롤러에 대해
#   $ storcli2 /call show
#   Status = Success
#   Description = No Controller found
# 처럼 성공을 리턴하므로, 컨트롤러 부재 문구를 함께 배제해야 한다.
_probe_cli() {
    local cli="$1" out
    [ -f "$cli" ] || return 1
    out="$("$cli" /call show 2>/dev/null)" || return 1
    echo "$out" | grep -q "Status = Success"        || return 1
    echo "$out" | grep -qi "No Controller found"    && return 1
    return 0
}

# graidctl probe: `version` 명령 정상 종료 확인 (드라이버/서비스 로드 필요)
_probe_graidctl() {
    [ -f "$GRAIDCTL_BIN" ] || return 1
    "$GRAIDCTL_BIN" version >/dev/null 2>&1
}

if _probe_cli "$PERCCLI64_LINK"; then
    cat > "$RAID_CFG" <<EOF
# Auto-generated by install_packages.sh
RAID_TYPE=dell_perc
RAID_CLI=$PERCCLI64_LINK
EOF
    ok "raid.cfg 생성: Dell PERC 응답 확인 → $PERCCLI64_LINK"

elif _probe_cli "$STORCLI_LINK"; then
    cat > "$RAID_CFG" <<EOF
# Auto-generated by install_packages.sh
RAID_TYPE=megaraid
RAID_CLI=$STORCLI_LINK
EOF
    ok "raid.cfg 생성: MegaRAID 응답 확인 → $STORCLI_LINK"

elif _probe_graidctl; then
    cat > "$RAID_CFG" <<EOF
# Auto-generated by install_packages.sh
RAID_TYPE=graid
RAID_CLI=$GRAIDCTL_BIN
EOF
    ok "raid.cfg 생성: GRAID SupremeRAID 응답 확인 → $GRAIDCTL_BIN"

elif _probe_cli "$STORCLI2_LINK"; then
    # MegaRAID 9600(SAS4116) 계열. storcli2 는 CLI 문법과 출력 형식이
    # storcli 007.x 와 달라서 Disk Info 파싱을 그대로 쓸 수 없다.
    # 잘못된 RAID_TYPE 으로 raid.cfg 를 쓰면 화면에 에러만 뜨므로 쓰지 않고
    # 운영자에게 알린다 (CLI 자체는 심볼릭 링크로 사용 가능).
    # ponytail: 9600 계열 Disk Info 미지원 — 천장은 해당 카드 장비 도입.
    #   upgrade: app/screens/system.py 에 raid_type "megaraid_gen5" 추가 +
    #            storcli2 문법(/c0/vall show 등) 파서 작성. 실물 카드 필요.
    warn "MegaRAID 9600 계열 감지 ($STORCLI2_LINK) — Disk Info 파싱 미지원"
    echo "       CLI 직접 사용: storcli2 /c0 show"
    echo "       raid.cfg 는 생성하지 않았습니다."

else
    warn "어느 CLI도 컨트롤러 응답 없음 — raid.cfg 미생성 (RAID 미탑재 또는 CLI 미설치)"
fi

echo ""

# ── [5/5] sudoers NOPASSWD 설정 (sands 사용자 SSH 접속 시 하드웨어 명령어 허용) ──
echo "[5/5] sudoers 설정..."

SUDOERS_SRC="$SCRIPT_DIR/sudoers_mnxmc"
SUDOERS_DEST="/etc/sudoers.d/mnxmc"

# sudoers 설치는 apply_sudoers.sh 에 단일 구현으로 둔다 (검증-후-복사 로직 중복 방지).
if [ -f "$SCRIPT_DIR/apply_sudoers.sh" ]; then
    bash "$SCRIPT_DIR/apply_sudoers.sh" || warn "sudoers 적용 실패 — 위 메시지 확인"
elif [ -f "$SUDOERS_SRC" ]; then
    warn "apply_sudoers.sh 없음 — sudoers 미적용 ($SUDOERS_SRC 수동 설치 필요)"
else
    warn "sudoers_mnxmc 파일 없음 — 건너뜀"
fi

# ── promisc@ 템플릿 유닛 설치 ────────────────────────────────────────────────
# mirror 포트 promisc 영속화. 인터페이스마다 유닛 파일을 sudo tee 로 만들던
# 구 방식은 sudoers 에 인자 wildcard 규칙을 요구해 sudo-rs 에서 깨진다.
echo ""
echo "[promisc] promisc@ 템플릿 유닛 설치..."

PROMISC_SRC="$SCRIPT_DIR/config/promisc@.service"
PROMISC_DEST="/etc/systemd/system/promisc@.service"

if [ -f "$PROMISC_SRC" ]; then
    install -m 644 -o root -g root "$PROMISC_SRC" "$PROMISC_DEST"
    systemctl daemon-reload 2>/dev/null || true
    ok "설치 완료: $PROMISC_DEST"

    # 구 방식(promisc-<iface>.service) 이 남아 있으면 템플릿으로 이관
    MIGRATED=0
    for old_unit in /etc/systemd/system/promisc-*.service; do
        [ -e "$old_unit" ] || continue
        old_name="$(basename "$old_unit")"
        iface="${old_name#promisc-}"; iface="${iface%.service}"
        [ -n "$iface" ] || continue
        systemctl disable "$old_name" 2>/dev/null || true
        rm -f "$old_unit"
        systemctl daemon-reload 2>/dev/null || true
        systemctl enable --now "promisc@${iface}.service" 2>/dev/null || true
        ok "  이관: $old_name → promisc@${iface}.service"
        MIGRATED=$((MIGRATED + 1))
    done
    [ "$MIGRATED" -eq 0 ] && ok "  이관 대상 구 유닛 없음"
else
    warn "config/promisc@.service 없음 — promisc 영속화 사용 불가"
fi


# ── 검증 ─────────────────────────────────────────────────────────────────────
echo ""
echo "[검증]"

# OS / sudo 구현
ok "OS       : $OS_PRETTY ($OS_CODENAME) — apt 세트: $(basename "$APT_DIR")"
if [ "$SUDO_IMPL" = "none" ]; then
    fail "sudo     : 없음 — sands SSH 세션의 권한 상승이 전부 실패합니다"
else
    ok "sudo     : $SUDO_IMPL  ($SUDO_REAL)"
fi

# 시각 동기화 데몬 (22.04=ntp / 26.04=chrony)
if systemctl is-active --quiet "$TIME_DAEMON" 2>/dev/null; then
    ok "timesync : $TIME_DAEMON active"
elif systemctl is-active --quiet systemd-timesyncd 2>/dev/null; then
    warn "timesync : $TIME_DAEMON 비활성 — systemd-timesyncd 가 대신 동작 중"
else
    warn "timesync : $TIME_DAEMON 및 systemd-timesyncd 모두 비활성"
fi

# timezone
TZ_CHECK=$(timedatectl show --property=Timezone --value 2>/dev/null)
if [ "$TZ_CHECK" = "Asia/Seoul" ]; then
    ok "timezone : Asia/Seoul (KST)"
else
    warn "timezone : $TZ_CHECK (Asia/Seoul 아님)"
fi

# python3.12
if command -v "$PYTHON" &>/dev/null; then
    ok "$PYTHON : $($PYTHON --version 2>&1)"
else
    fail "$PYTHON 없음"
fi

# pip
if "$PYTHON" -m pip --version &>/dev/null; then
    ok "pip : $($PYTHON -m pip --version 2>&1 | awk '{print $1, $2}')"
else
    warn "pip 없음"
fi

# textual, rich, requests
if "$PYTHON" -c "import textual, rich" 2>/dev/null; then
    TEXTUAL_VER=$("$PYTHON" -c "import textual; print(textual.__version__)" 2>/dev/null)
    RICH_VER=$("$PYTHON" -c "import rich; print(rich.__version__)" 2>/dev/null)
    ok "textual ${TEXTUAL_VER}, rich ${RICH_VER} import 성공"
else
    fail "textual, rich import 실패"
fi

if "$PYTHON" -c "import requests" 2>/dev/null; then
    REQ_VER=$("$PYTHON" -c "import requests; print(requests.__version__)" 2>/dev/null)
    ok "requests ${REQ_VER} import 성공"
else
    warn "requests import 실패 (ES 모니터링 비활성화됨)"
fi

# 네트워크 CLI — MNXMC 네트워크 화면이 절대경로로 하드 의존한다.
# 이 두 개가 없으면 TUI 는 뜨지만 인터페이스 통계/IP설정/promisc 가 전부 죽는다.
for netbin in /usr/sbin/ip /usr/sbin/netplan; do
    if [ -x "$netbin" ]; then
        ok "$(basename "$netbin") : $netbin"
    else
        fail "$(basename "$netbin") 없음: $netbin — Network 화면 동작 불가"
        echo "       복구: apt-get install --reinstall iproute2 netplan.io"
    fi
done

# curl, ethtool, dmidecode
command -v curl &>/dev/null  && ok "curl : $(curl --version 2>&1 | head -1)" || warn "curl 없음"
command -v ethtool &>/dev/null && ok "ethtool 설치됨" || warn "ethtool 없음"
command -v dmidecode &>/dev/null && ok "dmidecode 설치됨" || warn "dmidecode 없음"

# smartmontools
if command -v smartctl &>/dev/null; then
    ok "smartctl : $(smartctl --version 2>&1 | head -1)"
else
    warn "smartctl 없음"
fi

# storcli64
if [ -L "$STORCLI_LINK" ] && [ -f "$STORCLI_LINK" ]; then
    ok "storcli64 : $STORCLI_LINK → $(readlink "$STORCLI_LINK")"
else
    warn "storcli64 링크 없음: $STORCLI_LINK"
fi

# storcli2 (MegaRAID 9600 계열)
if [ -L "$STORCLI2_LINK" ] && [ -f "$STORCLI2_LINK" ]; then
    ok "storcli2  : $STORCLI2_LINK → $(readlink "$STORCLI2_LINK")"
else
    warn "storcli2 링크 없음: $STORCLI2_LINK (9600 계열 비탑재면 정상)"
fi

# perccli64
if [ -L "$PERCCLI64_LINK" ] && [ -f "$PERCCLI64_LINK" ]; then
    ok "perccli64 : $PERCCLI64_LINK → $(readlink "$PERCCLI64_LINK")"
else
    warn "perccli64 링크 없음: $PERCCLI64_LINK (PERC 비탑재 시스템이면 정상)"
fi

# perccli
if [ -L "$PERCCLI_LINK" ] && [ -f "$PERCCLI_LINK" ]; then
    ok "perccli   : $PERCCLI_LINK → $(readlink "$PERCCLI_LINK")"
else
    warn "perccli 링크 없음: $PERCCLI_LINK"
fi

# graidctl
if [ -f "$GRAIDCTL_BIN" ]; then
    ok "graidctl  : $GRAIDCTL_BIN ($("$GRAIDCTL_BIN" version 2>/dev/null | head -1))"
else
    warn "graidctl 없음: $GRAIDCTL_BIN (GRAID 비탑재 시스템이면 정상)"
fi

# raid.cfg
if [ -f "$RAID_CFG" ]; then
    RCFG_TYPE=$(grep "^RAID_TYPE=" "$RAID_CFG" | cut -d= -f2)
    RCFG_CLI=$(grep "^RAID_CLI=" "$RAID_CFG" | cut -d= -f2)
    ok "raid.cfg  : RAID_TYPE=${RCFG_TYPE}, RAID_CLI=${RCFG_CLI}"
else
    warn "raid.cfg 없음: $RAID_CFG (수동 생성 또는 컨트롤러 미감지)"
fi

# sudoers
if [ -f "$SUDOERS_DEST" ]; then
    if visudo -c -f "$SUDOERS_DEST" >/dev/null 2>&1; then
        ok "sudoers  : $SUDOERS_DEST ($(grep -c '^sands' "$SUDOERS_DEST")개 규칙, $SUDO_IMPL 통과)"
    else
        fail "sudoers  : $SUDOERS_DEST 파싱 실패 ($SUDO_IMPL) — sands 권한 전체 무효"
    fi
else
    warn "sudoers  : $SUDOERS_DEST 없음 — sands SSH 세션 기능 제한"
fi

# promisc@ 템플릿 유닛
if [ -f "$PROMISC_DEST" ]; then
    ACTIVE_PROMISC=$(systemctl list-units --all --no-legend 'promisc@*' 2>/dev/null | wc -l)
    ok "promisc  : $PROMISC_DEST (활성 인스턴스 ${ACTIVE_PROMISC}개)"
else
    warn "promisc  : $PROMISC_DEST 없음 — mirror 포트 promisc 영속화 불가"
fi

# ── getty@tty1 오버라이드 설정 ────────────────────────────────────────────────
echo "[6/8] getty@tty1 서비스 설정..."

GETTY_DIR="/etc/systemd/system/getty@tty1.service.d"
GETTY_CONF="$GETTY_DIR/override.conf"

mkdir -p "$GETTY_DIR"

cat > "$GETTY_CONF" << 'EOF'
[Unit]
After=multi-user.target

[Service]
ExecStart=
ExecStartPre=/bin/clear
ExecStart=/usr/bin/python3.12 /mnxmc/main-login.py
StandardInput=tty
StandardOutput=tty
TTYPath=/dev/tty1
TTYReset=yes
TTYVHangup=yes
TTYVTDisallocate=no
User=root
Restart=on-failure
RestartSec=1
EOF

systemctl daemon-reload 2>/dev/null || true
systemctl enable getty@tty1.service 2>/dev/null || true
if systemctl is-active --quiet getty@tty1.service 2>/dev/null; then
    systemctl restart getty@tty1.service 2>/dev/null || true
    ok "getty@tty1 재시작 완료"
else
    ok "getty@tty1 활성화 완료"
fi

# ── /etc/bash.bashrc SSH → MNXMC 진입 설정 ───────────────────────────────────
echo "[7/8] bash.bashrc SSH 진입 제어 설정..."

BASHRC="/etc/bash.bashrc"
MARKER="# MNX Management Console"

if grep -q "$MARKER" "$BASHRC" 2>/dev/null; then
    ok "bash.bashrc 이미 설정됨 — 건너뜀"
else
    cat >> "$BASHRC" << 'BASHRC_BLOCK'

# MNX Management Console - Direct access only for Interactive SSH sessions
if [ -n "$SSH_CONNECTION" ] \
   && [ -z "$MNXMC_DONE" ] \
   && [[ "$-" == *i* ]] \
   && [ -n "$SSH_TTY" ]; then

    export MNXMC_DONE=1

    if [ -f /mnxmc/main.py ]; then
        cd /mnxmc
        exec /usr/bin/python3.12 /mnxmc/main.py
    fi
fi
BASHRC_BLOCK
    ok "bash.bashrc SSH 진입 제어 추가 완료"
fi

# ── 심볼릭 링크 생성 (/data/tools → /usr/local/bin) ──────────────────────────
echo "[8/8] 심볼릭 링크 생성..."

ln -sf /data/tools/check_index.sh            /usr/local/bin/mnx_check_index
ln -sf /data/tools/check_kafka.sh            /usr/local/bin/mnx_check_kafka
ln -sf /data/tools/check_slowlog.sh          /usr/local/bin/mnx_check_slowlog
ln -sf /data/tools/MNX_all_start_service.sh  /usr/local/bin/mnx_all_start_service
ln -sf /data/tools/MNX_all_stop_service.sh   /usr/local/bin/mnx_all_stop_service
ln -sf /data/tools/MNX_status_check.sh       /usr/local/bin/mnx_status_check

# ── [9/11] /root/.bashrc 설정 ────────────────────────────────────────────────
echo "[9/11] /root/.bashrc 설정..."

tee /root/.bashrc >/dev/null << 'EOF'
# ===== SANDS LAB 전역 설정 =====
export LS_COLORS="\
rs=0:\
di=1;36:\
ln=1;35:\
so=1;35:\
pi=1;33:\
ex=1;31:\
bd=1;33:\
cd=1;33:\
*.tar=0;31:*.tgz=0;31:*.zip=0;31:*.gz=0;31:*.bz2=0;31:*.xz=0;31:\
*.jpg=0;35:*.jpeg=0;35:*.png=0;35:*.gif=0;35:*.mp4=0;35:*.mp3=0;35:*.aac=0;35:*.mkv=0;35:\
"
alias ls='ls --color=auto'
export HISTTIMEFORMAT="%Y-%m-%d %H:%M:%S "
alias mnxmon='watch -n 1 '"'"'curl -s http://localhost:9200/arkime_stats/_doc/$(hostname) | jq "._source | {totalPackets, packetQueue, closeQueue, totalDropped}"'"'"''
EOF
ok "/root/.bashrc 설정 완료"

# ── [10/11] /home/sands/.bashrc 설정 ─────────────────────────────────────────
echo "[10/11] /home/sands/.bashrc 설정..."

if [ -d /home/sands ]; then
    tee /home/sands/.bashrc >/dev/null << 'EOF'
# ===== SANDS LAB 전역 설정 =====
export LS_COLORS="\
rs=0:\
di=1;36:\
ln=1;35:\
so=1;35:\
pi=1;33:\
ex=1;31:\
bd=1;33:\
cd=1;33:\
*.tar=0;31:*.tgz=0;31:*.zip=0;31:*.gz=0;31:*.bz2=0;31:*.xz=0;31:\
*.jpg=0;35:*.jpeg=0;35:*.png=0;35:*.gif=0;35:*.mp4=0;35:*.mp3=0;35:*.aac=0;35:*.mkv=0;35:\
"
alias ls='ls --color=auto'
export HISTTIMEFORMAT="%Y-%m-%d %H:%M:%S "
alias mnxmon='watch -n 1 '"'"'curl -s http://localhost:9200/arkime_stats/_doc/$(hostname) | jq "._source | {totalPackets, packetQueue, closeQueue, totalDropped}"'"'"''
EOF
    chown sands:sands /home/sands/.bashrc 2>/dev/null || true
    ok "/home/sands/.bashrc 설정 완료"
else
    warn "/home/sands 없음 — 건너뜀"
fi

# ── [11/11] systemd-networkd-wait-online 비활성화 (부팅 지연 방지) ────────────
echo "[11/11] systemd-networkd-wait-online 비활성화..."

systemctl disable systemd-networkd-wait-online.service 2>/dev/null || true
systemctl mask    systemd-networkd-wait-online.service 2>/dev/null || true
ok "systemd-networkd-wait-online 비활성화 완료"

# ── [12/13] cloud-init 네트워크 관리 비활성화 ─────────────────────────────────
echo "[12/13] cloud-init 네트워크 설정 비활성화..."

if [ -d /etc/cloud/cloud.cfg.d ]; then
    echo "network: {config: disabled}" > /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg
    ok "cloud-init 네트워크 비활성화 완료: /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg"
else
    warn "/etc/cloud/cloud.cfg.d 없음 — cloud-init 미설치, skip"
fi

# ── [13/13] 로그인 경고 배너 설정 (/etc/issue.net + SSH Banner) ───────────────
echo "[13/13] 로그인 경고 배너 설정..."

cat <<'EOF' > /etc/issue.net
************************************************************************
*                      SANDS LAB Inc. NDR SYSTEM                       *
************************************************************************
* This system is for authorized use only.                              *
* Unauthorized access is strictly prohibited.                          *
* All activities on this system are monitored and recorded.            *
* By accessing this system, you consent to such monitoring.            *
************************************************************************
EOF

# /etc/issue (로컬 콘솔 로그인 배너)에도 동일 적용
cp /etc/issue.net /etc/issue

# SSH Banner 설정 (없으면 추가, 있으면 갱신)
SSHD_CONF="/etc/ssh/sshd_config"
if grep -q "^Banner" "$SSHD_CONF" 2>/dev/null; then
    sed -i 's|^Banner.*|Banner /etc/issue.net|' "$SSHD_CONF"
else
    echo "Banner /etc/issue.net" >> "$SSHD_CONF"
fi

systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || true
ok "로그인 경고 배너 설정 완료 (/etc/issue.net, /etc/issue, SSH Banner)"

echo ""
echo "============================================================"
echo "  설치 완료"
echo "============================================================"
echo ""
echo "  storcli64 사용 예 (MegaRAID/LSI):"
echo "    storcli64 show"
echo "    storcli64 /c0 /vall show         ← VD 목록"
echo "    storcli64 /c0 /eall /sall show   ← PD 목록"
echo ""
echo "  perccli64 사용 예 (Dell PERC):"
echo "    perccli64 show"
echo "    perccli64 /c0 /vall show         ← VD 목록"
echo "    perccli64 /c0 /eall /sall show   ← PD 목록"
echo ""
echo "  graidctl 사용 예 (GRAID SupremeRAID):"
echo "    graidctl version"
echo "    graidctl list virtual_drive       ← VD 목록"
echo "    graidctl list physical_drive      ← PD 목록"
echo "============================================================"
echo ""
