#!/bin/bash
# =============================================================================
# install_packages.sh
# MNX Package Installer — apt + pip + storcli + perccli 원스톱 설치
#
# [용도] 오프라인 환경 설치 (네트워크 불필요)
# [사용법] sudo bash install_packages.sh
#
# [디렉토리 구조 (이 스크립트 기준)]
#   packages/
#     ├── install_packages.sh       ← 이 파일
#     ├── apt/    *.deb             ← python3.12, smartmontools 등 + 의존성
#     ├── pip/    *.whl             ← textual, rich 등
#     ├── storcli/ *.deb           ← storcli 패키지 (MegaRAID/LSI 계열)
#     └── perccli/ perccli perccli64  ← Dell PERC 바이너리
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APT_DIR="$SCRIPT_DIR/apt"
PIP_DIR="$SCRIPT_DIR/pip"
STORCLI_DIR="$SCRIPT_DIR/storcli"
PERCCLI_DIR="$SCRIPT_DIR/perccli"
PYTHON="python3.12"
STORCLI_BIN="/opt/MegaRAID/storcli/storcli64"
STORCLI_LINK="/usr/local/bin/storcli64"
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

echo ""
echo "============================================================"
echo "  MNX Package Installer (Offline)"
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
        # dpkg는 의존성 순서를 맞추지 않으므로 최대 3회 반복
        for attempt in 1 2 3; do
            dpkg -i "${INSTALL_LIST[@]}" 2>/dev/null && break
            echo "  → [${attempt}/3] 재시도 중 (의존성 순서 해결)..."
        done

        # dpkg 상태 정리 (언팩 상태인 패키지 설정 완료)
        dpkg --configure -a 2>/dev/null || true

        # 오프라인 모드로 깨진 의존성 복구 (네트워크 사용 안 함)
        apt-get install -f -y \
            -o Dir::Etc::SourceList=/dev/null \
            -o Dir::Etc::SourceParts=/dev/null \
            --no-install-recommends 2>/dev/null || true

        ok "${INSTALL_COUNT}개 설치 완료 (${SKIP_COUNT}개 skip)"
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

    # --break-system-packages: Ubuntu 23.04+ PEP 668 환경 대응
    # 실패 시 옵션 없이 재시도 (Ubuntu 22.04 이하)
    "$PYTHON" -m pip install \
        --no-index \
        --find-links="$PIP_DIR" \
        --quiet \
        textual rich requests \
        --break-system-packages 2>/dev/null \
    || "$PYTHON" -m pip install \
        --no-index \
        --find-links="$PIP_DIR" \
        --quiet \
        textual rich requests

    ok "${WHL_COUNT}개 .whl 설치 완료"
fi

echo ""

# ── [3/4] StorCLI 설치 ───────────────────────────────────────────────────────
echo "[3/4] StorCLI 설치..."

STORCLI_DEB=$(ls "$STORCLI_DIR"/*.deb 2>/dev/null | head -1)

if [ -z "$STORCLI_DEB" ]; then
    warn "storcli/ 폴더에 .deb 파일 없음 — 건너뜀"
else
    echo "  → $(basename "$STORCLI_DEB") 설치 중..."
    dpkg -i "$STORCLI_DEB" 2>/dev/null \
        || dpkg --force-depends -i "$STORCLI_DEB" 2>/dev/null || true
    dpkg --configure -a 2>/dev/null || true

    if [ -f "$STORCLI_BIN" ]; then
        ln -sf "$STORCLI_BIN" "$STORCLI_LINK"
        chmod +x "$STORCLI_LINK"
        ok "storcli64 설치 완료"
        ok "심볼릭 링크: $STORCLI_LINK → $STORCLI_BIN"
    else
        warn "바이너리 없음: $STORCLI_BIN (설치 확인 필요)"
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

# storcli/perccli probe: "/call show" 출력에 "Status = Success" 포함 확인
_probe_cli() {
    local cli="$1"
    [ -f "$cli" ] || return 1
    "$cli" /call show 2>/dev/null | grep -q "Status = Success"
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

else
    warn "어느 CLI도 컨트롤러 응답 없음 — raid.cfg 미생성 (RAID 미탑재 또는 CLI 미설치)"
fi

echo ""

# ── [5/5] sudoers NOPASSWD 설정 (sands 사용자 SSH 접속 시 하드웨어 명령어 허용) ──
echo "[5/5] sudoers 설정..."

SUDOERS_SRC="$SCRIPT_DIR/sudoers_mnxmc"
SUDOERS_DEST="/etc/sudoers.d/mnxmc"

if [ -f "$SUDOERS_SRC" ]; then
    # 기존 파일과 내용이 다르거나 없으면 재설치
    if [ -f "$SUDOERS_DEST" ] && cmp -s "$SUDOERS_SRC" "$SUDOERS_DEST"; then
        ok "sudoers 이미 최신 상태 — 건너뜀"
    else
        cp "$SUDOERS_SRC" "$SUDOERS_DEST"
        chmod 440 "$SUDOERS_DEST"
        # 문법 검증
        if visudo -c -f "$SUDOERS_DEST" 2>/dev/null; then
            ok "sudoers 설치 완료: $SUDOERS_DEST"
        else
            warn "sudoers 문법 오류 — 삭제 후 수동 설치 필요"
            rm -f "$SUDOERS_DEST"
        fi
    fi
else
    warn "sudoers_mnxmc 파일 없음 — 건너뜀"
fi


# ── 검증 ─────────────────────────────────────────────────────────────────────
echo ""
echo "[검증]"

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
