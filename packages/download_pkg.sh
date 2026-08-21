#!/bin/bash
# =============================================================================
# download_pkg.sh
# MNX 오프라인 패키지 다운로드 스크립트 (Ubuntu 22.04 / 26.04 분리)
#
# [용도] 온라인 환경에서 실행 → packages/ 디렉토리를 오프라인 대상 서버에 복사
# [설치] sudo bash packages/install_packages.sh   (설치 측에서 OS 자동 판별)
#
# [사용법]
#   bash download_pkg.sh                    # 현재 호스트 OS 만
#   bash download_pkg.sh --suite resolute   # 26.04 만
#   bash download_pkg.sh --suite all        # jammy + resolute 둘 다
#   bash download_pkg.sh --suite all --dest /tmp/pkg
#
# [디렉토리 구조 생성]
#   <출력>
#     ├── apt/jammy/    ← *.deb (Ubuntu 22.04)
#     ├── apt/resolute/ ← *.deb (Ubuntu 26.04)
#     ├── pip/          ← *.whl (python3.12 공용 — 두 OS 동일 런타임)
#     └── storcli/      ← 수동 배치 필요 (Broadcom 공식 배포만 가능)
#
# 대상 suite 의 apt 인덱스를 격리된 apt root 로 직접 받으므로, 실행 호스트의
# OS 와 무관하게 어느 suite 든 내려받을 수 있다 (22.04 에서 26.04 세트 생성 가능).
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

GREEN="\033[0;32m"; YELLOW="\033[1;33m"; RED="\033[0;31m"; NC="\033[0m"
ok()   { echo -e "  ${GREEN}[OK]${NC}    $*"; }
warn() { echo -e "  ${YELLOW}[WARN]${NC}  $*"; }
fail() { echo -e "  ${RED}[FAIL]${NC}  $*"; }

# ── 지원 suite 정의 ──────────────────────────────────────────────────────────
# MNXMC 는 두 OS 에서 동일하게 python3.12 를 런타임으로 쓴다.
#   - 22.04(jammy)    : 시스템 python3 은 3.10 → deadsnakes PPA 의 3.12
#   - 26.04(resolute) : 시스템 python3 은 3.14 → deadsnakes PPA 의 3.12
# 동일 런타임을 유지하면 pip/*.whl 세트와 /usr/bin/python3.12 경로를 공용화할 수 있다.
DEADSNAKES_URL="https://ppa.launchpadcontent.net/deadsnakes/ppa/ubuntu/"
DEADSNAKES_FPR="F23C5A6CF475977595C89F51BA6932366A755776"

# 두 OS 공통 패키지
COMMON_PKGS=(
    python3.12
    python3.12-venv
    libpython3.12-stdlib
    python3-pip
    python3-setuptools
    python3-wheel
    smartmontools
    unzip
    tcpreplay
    snmpd
    snmp
    libsnmp-dev
    snmp-mibs-downloader
    htop
    sysstat
    nmon
    iotop
    fio
    curl
    ethtool
    dmidecode
    nfs-common
    ipset
)

# suite 별 차이. resolute(26.04) 에서 ntp 패키지는 제거되었고 chrony 로 대체되었다.
suite_extra_pkgs() {
    case "$1" in
        jammy)    echo "ntp" ;;
        resolute) echo "chrony" ;;
    esac
}

suite_version_id() {
    case "$1" in
        jammy)    echo "22.04" ;;
        resolute) echo "26.04" ;;
    esac
}

# ── 인자 파싱 ────────────────────────────────────────────────────────────────
DEST="$SCRIPT_DIR"
SUITE_ARG=""

while [ $# -gt 0 ]; do
    case "$1" in
        --suite) SUITE_ARG="$2"; shift 2 ;;
        --dest)  DEST="$2";      shift 2 ;;
        -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
        *) fail "알 수 없는 인자: $1"; exit 1 ;;
    esac
done

if [ -z "$SUITE_ARG" ]; then
    # 인자 없으면 현재 호스트 OS 의 codename 을 사용
    SUITE_ARG="$(. /etc/os-release && echo "$VERSION_CODENAME")"
fi

case "$SUITE_ARG" in
    all)               SUITES=(jammy resolute) ;;
    jammy|resolute)    SUITES=("$SUITE_ARG") ;;
    *) fail "지원하지 않는 suite: $SUITE_ARG  (jammy | resolute | all)"; exit 1 ;;
esac

PIP_DIR="$DEST/pip"
STORCLI_DIR="$DEST/storcli"

echo ""
echo "============================================================"
echo "  MNX Package Downloader"
echo "  대상 suite : ${SUITES[*]}"
echo "  출력       : $DEST"
echo "============================================================"

command -v apt-get &>/dev/null || { fail "apt-get 없음"; exit 1; }

# ── suite 별 apt 다운로드 ────────────────────────────────────────────────────
# 격리된 apt root(빈 dpkg status)를 만들어 대상 suite 인덱스만으로 의존성을
# 해석한다. 호스트에 이미 깔린 패키지 상태가 결과에 섞이지 않게 하려는 것.
download_suite() {
    local suite="$1"
    local out_dir="$DEST/apt/$suite"
    local root="$(mktemp -d /tmp/mnx_apt_${suite}_XXXXXX)"

    echo ""
    echo "── [$suite / Ubuntu $(suite_version_id "$suite")] ────────────────────────"
    mkdir -p "$out_dir" \
             "$root/etc/apt/apt.conf.d" "$root/etc/apt/preferences.d" \
             "$root/etc/apt/trusted.gpg.d" \
             "$root/var/lib/apt/lists/partial" \
             "$root/var/cache/apt/archives/partial" \
             "$root/var/lib/dpkg"
    : > "$root/var/lib/dpkg/status"

    cat > "$root/etc/apt/sources.list" <<EOF
deb http://archive.ubuntu.com/ubuntu/ ${suite} main restricted universe multiverse
deb http://archive.ubuntu.com/ubuntu/ ${suite}-updates main restricted universe multiverse
deb http://security.ubuntu.com/ubuntu/ ${suite}-security main restricted universe multiverse
deb ${DEADSNAKES_URL} ${suite} main
EOF

    # 호스트의 Ubuntu 아카이브 키링 재사용 + deadsnakes 키는 keyserver 에서 확보
    for k in /usr/share/keyrings/ubuntu-archive-keyring.gpg /etc/apt/trusted.gpg.d/*.gpg; do
        [ -f "$k" ] && cp -f "$k" "$root/etc/apt/trusted.gpg.d/" 2>/dev/null
    done

    local unauth=()
    if curl -fsSL "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x${DEADSNAKES_FPR}" 2>/dev/null \
         | gpg --dearmor > "$root/etc/apt/trusted.gpg.d/deadsnakes.gpg" 2>/dev/null \
       && [ -s "$root/etc/apt/trusted.gpg.d/deadsnakes.gpg" ]; then
        ok "deadsnakes 서명키 확보 (${DEADSNAKES_FPR: -8})"
    else
        rm -f "$root/etc/apt/trusted.gpg.d/deadsnakes.gpg"
        warn "deadsnakes 서명키 확보 실패 — 서명 검증 없이 진행"
        unauth=( -o APT::Get::AllowUnauthenticated=true
                 -o Acquire::AllowInsecureRepositories=true )
    fi

    local aptopt=(
        -o Dir::Etc::SourceList="$root/etc/apt/sources.list"
        -o Dir::Etc::SourceParts="$root/etc/apt/sources.list.d"
        -o Dir::Etc::Preferences="$root/etc/apt/preferences"
        -o Dir::Etc::PreferencesParts="$root/etc/apt/preferences.d"
        -o Dir::Etc::Trusted="$root/etc/apt/trusted.gpg"
        -o Dir::Etc::TrustedParts="$root/etc/apt/trusted.gpg.d"
        -o Dir::State::Lists="$root/var/lib/apt/lists"
        -o Dir::Cache="$root/var/cache/apt"
        -o Dir::State::status="$root/var/lib/dpkg/status"
        -o APT::Architecture=amd64
        -o APT::Architectures=amd64
        -o Acquire::Languages=none
        "${unauth[@]}"
    )

    echo "  → apt 인덱스 수집 중..."
    if ! apt-get "${aptopt[@]}" update >/dev/null 2>&1; then
        fail "$suite: apt-get update 실패 — 네트워크/미러 확인"
        rm -rf "$root"; return 1
    fi

    local pkgs=( "${COMMON_PKGS[@]}" )
    local extra; extra="$(suite_extra_pkgs "$suite")"
    [ -n "$extra" ] && pkgs+=( $extra )

    # 요청 패키지가 해당 suite 에 실제로 존재하는지 먼저 확인 (조용한 누락 방지)
    local resolved=() missing=()
    for p in "${pkgs[@]}"; do
        if apt-cache "${aptopt[@]}" show "$p" >/dev/null 2>&1; then
            resolved+=( "$p" )
        else
            missing+=( "$p" )
        fi
    done
    if [ ${#missing[@]} -gt 0 ]; then
        warn "$suite 에 없는 패키지 (건너뜀): ${missing[*]}"
    fi
    if [ ${#resolved[@]} -eq 0 ]; then
        fail "$suite: 다운로드할 패키지가 없음"
        rm -rf "$root"; return 1
    fi

    echo "  → 의존성 트리 수집 중 (${#resolved[@]}개 요청)..."
    local all
    all=$(apt-cache "${aptopt[@]}" depends --recurse \
            --no-recommends --no-suggests \
            --no-conflicts --no-breaks --no-replaces --no-enhances \
            "${resolved[@]}" 2>/dev/null \
          | grep '^\w' | sed 's/:amd64$//' | sort -u)

    if [ -z "$all" ]; then
        fail "$suite: 의존성 트리 수집 실패"
        rm -rf "$root"; return 1
    fi

    local total; total=$(echo "$all" | wc -l)
    echo "  → 총 ${total}개 패키지 다운로드 중..."

    # apt-get download 는 cwd 에 파일을 떨어뜨린다 → 반드시 출력 디렉토리에서 실행
    local downloaded=0 skipped=0 failed=0 fail_list=()
    pushd "$out_dir" >/dev/null || { rm -rf "$root"; return 1; }
    while IFS= read -r pkg; do
        [ -n "$pkg" ] || continue
        if ! apt-cache "${aptopt[@]}" show "$pkg" >/dev/null 2>&1; then
            skipped=$((skipped + 1))   # virtual package — 정상
            continue
        fi
        if apt-get "${aptopt[@]}" download "$pkg" >/dev/null 2>&1; then
            downloaded=$((downloaded + 1))
        else
            failed=$((failed + 1)); fail_list+=( "$pkg" )
        fi
    done <<< "$all"
    popd >/dev/null

    local actual; actual=$(ls "$out_dir"/*.deb 2>/dev/null | wc -l)
    echo ""
    echo "  다운로드: ${downloaded}개 | virtual/건너뜀: ${skipped}개 | 실패: ${failed}개"
    ok "apt/$suite/ .deb 합계: ${actual}개  ($(du -sh "$out_dir" | cut -f1))"

    if [ "$failed" -gt 0 ]; then
        warn "실패 목록: ${fail_list[*]}"
        warn "오프라인 설치 시 의존성 오류 발생 가능"
    fi

    # python3.12 는 MNXMC 런타임이므로 누락되면 설치가 무의미하다 → 명시적으로 검증
    if ls "$out_dir"/python3.12_*.deb >/dev/null 2>&1; then
        ok "python3.12: $(basename "$(ls "$out_dir"/python3.12_*.deb | head -1)")"
    else
        fail "python3.12 .deb 누락 — deadsnakes PPA 접근 실패로 보임 ($suite)"
    fi

    rm -rf "$root"
}

RC=0
for s in "${SUITES[@]}"; do
    download_suite "$s" || RC=1
done

# ── pip 패키지 다운로드 (python3.12 공용) ────────────────────────────────────
echo ""
echo "── pip (python3.12 공용) ────────────────────────────────────"
mkdir -p "$PIP_DIR"

if ! command -v python3.12 &>/dev/null; then
    warn "python3.12 없음 — pip 다운로드 건너뜀"
    warn "python3.12 설치 후 재실행하거나 pip/*.whl 파일을 수동으로 배치하세요."
else
    # requirements.txt 의 핀을 그대로 쓴다 (whl 과 핀이 어긋나는 것을 방지).
    # cp312 전용 wheel 을 받도록 --only-binary + 플랫폼 태그를 명시하지 않고
    # 실행 중인 python3.12 인터프리터 기준으로 해석시킨다.
    REQ="$(dirname "$SCRIPT_DIR")/requirements.txt"
    if [ -f "$REQ" ]; then
        python3.12 -m pip download -r "$REQ" --dest "$PIP_DIR" --quiet 2>&1 \
            | grep -vi "already satisfied" || true
    else
        warn "requirements.txt 없음 — 패키지명으로 직접 다운로드"
        python3.12 -m pip download textual rich requests --dest "$PIP_DIR" --quiet 2>&1 || true
    fi

    WHL_COUNT=$(ls "$PIP_DIR"/*.whl 2>/dev/null | wc -l)
    if [ "$WHL_COUNT" -gt 0 ]; then
        ok "pip/ .whl 합계: ${WHL_COUNT}개"
    else
        fail "pip 패키지 다운로드 실패"
        RC=1
    fi
fi

# ── StorCLI 확인 ─────────────────────────────────────────────────────────────
echo ""
echo "── storcli (수동 배치) ──────────────────────────────────────"
STORCLI_COUNT=$(ls "$STORCLI_DIR"/*.deb 2>/dev/null | wc -l)
if [ "$STORCLI_COUNT" -gt 0 ]; then
    ok "storcli/ .deb 확인: ${STORCLI_COUNT}개"
else
    warn "storcli/ 폴더에 .deb 없음"
    echo "       Broadcom 공식 배포본을 수동으로 배치하세요:"
    echo "       https://docs.broadcom.com → MegaRAID Storage Software → StorCLI"
    echo "       배치 경로: $STORCLI_DIR/<storcli_xxx_all.deb>"
fi

# ── 최종 요약 ────────────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "  다운로드 요약"
for s in jammy resolute; do
    d="$DEST/apt/$s"
    [ -d "$d" ] && printf "  %-16s %s개 .deb  (%s)\n" "apt/$s/" \
        "$(ls "$d"/*.deb 2>/dev/null | wc -l)" "$(du -sh "$d" 2>/dev/null | cut -f1)"
done
printf "  %-16s %s개 .whl\n" "pip/"     "$(ls "$PIP_DIR"/*.whl 2>/dev/null | wc -l)"
printf "  %-16s %s개 .deb\n" "storcli/" "$(ls "$STORCLI_DIR"/*.deb 2>/dev/null | wc -l)"
echo "============================================================"
echo ""
echo "  [다음 단계]"
echo "  1. packages/ 디렉토리 전체를 오프라인 서버에 복사"
echo "  2. sudo bash packages/install_packages.sh   ← OS 자동 판별"
echo "============================================================"
echo ""

exit $RC
