#!/bin/bash
# ==============================================================================
# 주요정보통신기반시설 기술적 취약점 분석·평가 조치 스크립트 (Ubuntu 22.04)
# 기준: 2026년판 KISA 상세가이드
# 버전: 3.0.0 (2026-03-26)
#
# 처리 분류:
#   AUTO   - 서비스 영향 없이 바로 적용 가능
#   SEMI   - 운영 영향 있음, 승인 후 적용
#   MANUAL - 운영 정책 판단 필요, 안내만 제공
#   SKIP   - 양호 또는 N/A (미조치)
#
# 사용법:
#   sudo bash infra_remediate.sh [보고서파일]            # 대화형 모드
#   sudo bash infra_remediate.sh [보고서파일] --dry-run  # 미리보기 (변경 없음)
#   sudo bash infra_remediate.sh [보고서파일] --auto     # AUTO 항목 자동 적용
# ==============================================================================

if [ "$EUID" -ne 0 ]; then
    echo "[오류] root 권한으로 실행해야 합니다. sudo bash $0"
    exit 1
fi

# ------------------------------------------------------------------------------
# 인자 처리
# ------------------------------------------------------------------------------
REPORT_FILE=""
DRY_RUN=false
AUTO_MODE=false

for ARG in "$@"; do
    case "$ARG" in
        --dry-run) DRY_RUN=true ;;
        --auto)    AUTO_MODE=true ;;
        *)         REPORT_FILE="$ARG" ;;
    esac
done

# 보고서 파일 자동 탐색 (인자 없을 때 스크립트 위치 기준 최신 파일 사용)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -z "$REPORT_FILE" ]; then
    REPORT_FILE=$(ls -t "${SCRIPT_DIR}"/infra_audit_report_*.txt 2>/dev/null | head -1)
    if [ -z "$REPORT_FILE" ]; then
        REPORT_FILE=$(ls -t infra_audit_report_*.txt 2>/dev/null | head -1)
    fi
    if [ -z "$REPORT_FILE" ]; then
        echo "[오류] 보고서 파일을 찾을 수 없습니다. infra_audit.sh를 먼저 실행하세요."
        exit 1
    fi
    echo "[정보] 보고서 자동 선택: $REPORT_FILE"
fi

if [ ! -f "$REPORT_FILE" ]; then
    echo "[오류] 보고서 파일 없음: $REPORT_FILE"
    exit 1
fi

# ------------------------------------------------------------------------------
# 변수 및 로그 설정
# ------------------------------------------------------------------------------
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
REMEDIATE_LOG="${SCRIPT_DIR}/infra_remediate_${TIMESTAMP}.log"
BACKUP_DIR="${SCRIPT_DIR}/backup_${TIMESTAMP}"

CNT_APPLIED=0
CNT_SKIP=0
CNT_SKIPPED=0
CNT_MANUAL_VULN=0
FILTER_MANUAL_SELECTED=false   # true: SELECTED_MAP 항목만 출력, false: 전체 출력(report용)
FINAL_EMITTED=false            # final 리포트 생성 여부 (중복 방지)

log() {
    local LEVEL="$1"; shift
    local MSG="$*"
    local TS; TS=$(date "+%Y-%m-%d %H:%M:%S")
    echo "[$TS][$LEVEL] $MSG" | tee -a "$REMEDIATE_LOG"
}

log_action() {
    echo "  -> $*" | tee -a "$REMEDIATE_LOG"
}

# 취약 여부 확인 (보고서에서 ID 블록 파싱)
get_status() {
    local ID="$1"
    awk "/^[[:space:]]*[┌].*\[${ID}\]/,/^[[:space:]]*[└]/" "$REPORT_FILE" 2>/dev/null \
        | grep "진단결과" | grep -oE "\[양호\]|\[취약\]|\[N/A\]" | head -1
}

# 설정 파일 백업
backup_file() {
    local FILE="$1"
    if [ -f "$FILE" ]; then
        mkdir -p "$BACKUP_DIR"
        local DEST="${BACKUP_DIR}/$(echo "$FILE" | tr '/' '_').bak"
        cp -p "$FILE" "$DEST" 2>/dev/null
        log "BACKUP" "$FILE -> $DEST"
    fi
}

# 실제 실행 또는 dry-run 출력
run_cmd() {
    if $DRY_RUN; then
        echo "    [DRY-RUN] $*" | tee -a "$REMEDIATE_LOG"
    else
        eval "$@" 2>&1 | tee -a "$REMEDIATE_LOG"
    fi
}

# /etc/profile 무결성 검증 함수
# 반환: 0=정상, 1=손상
verify_profile_integrity() {
    local FILE="${1:-/etc/profile}"
    if ! grep -qE '^\s*\.\s+/etc/bash\.bashrc' "$FILE" 2>/dev/null; then
        log "PROTECT" "[CRITICAL] $FILE 손상 감지: '. /etc/bash.bashrc' 라인 누락"
        return 1
    fi
    if ! grep -qE '^\s*\.\s+\$i' "$FILE" 2>/dev/null; then
        log "PROTECT" "[CRITICAL] $FILE 손상 감지: '. \$i' 라인 누락"
        return 1
    fi
    return 0
}

# /etc/profile 안전 추가 함수 (append-only, dot라인 보호)
safe_append_profile() {
    local LINE="$1"
    local FILE="${2:-/etc/profile}"

    # 무결성 사전 검증
    if ! verify_profile_integrity "$FILE"; then
        log "PROTECT" "[ERROR] $FILE 손상 상태 - 수정 중단 (복구 필요)"
        return 1
    fi

    # 이미 동일 라인 존재하면 skip
    if grep -qF "$LINE" "$FILE" 2>/dev/null; then
        log "PROTECT" "$FILE: 이미 존재하므로 추가 생략 - $LINE"
        return 0
    fi

    echo "$LINE" >> "$FILE"

    # 수정 후 무결성 재검증
    if ! verify_profile_integrity "$FILE"; then
        log "PROTECT" "[CRITICAL] $FILE 수정 후 무결성 실패 - 즉시 복구 필요"
        return 1
    fi

    log "PROTECT" "$FILE: 안전하게 추가 완료 - $LINE"
    return 0
}

# SEMI 항목 승인 요청
ask_confirm() {
    local MSG="$1"
    if $AUTO_MODE; then
        return 1  # --auto 모드에서 SEMI는 건너뜀
    fi
    echo ""
    echo "  +----------------------------------------------------------"
    echo "  |  [SEMI-AUTO] $MSG"
    echo "  |  서비스 영향이 있을 수 있습니다. 적용하시겠습니까?"
    echo "  +----------------------------------------------------------"
    read -r -p "  적용 [y/N]: " ANSWER
    [[ "$ANSWER" =~ ^[Yy]$ ]]
}

# 항목 헤더 출력
print_item() {
    local ID="$1"
    local TYPE="$2"
    local DESC="$3"
    local STATUS="$4"
    echo ""
    echo "===================================================================="
    printf "  [%-6s] %-5s | %-10s | %s\n" "$TYPE" "$ID" "[$STATUS]" "$DESC"
    echo "===================================================================="
}

# MANUAL 항목 출력 함수
# AUTO/SEMI 항목별 평가 기준 + 현재 설정값 출력 (report 용)
get_item_detail() {
    local ID="$1"
    case "$ID" in
    "U-01")
        echo "  [평가 기준] PermitRootLogin no 설정 시 양호"
        echo "  [현재 설정]"
        grep -E "^[[:space:]]*PermitRootLogin" /etc/ssh/sshd_config 2>/dev/null \
            | sed 's/^/    /' || echo "    설정 없음 (기본값 yes 적용 가능)"
        ;;
    "U-02")
        echo "  [평가 기준] minlen≥8, dcredit≤-1, ucredit≤-1, lcredit≤-1, ocredit≤-1, retry≤5"
        echo "  [현재 설정] /etc/security/pwquality.conf"
        grep -E "^[[:space:]]*(minlen|dcredit|ucredit|lcredit|ocredit|retry)" \
            /etc/security/pwquality.conf 2>/dev/null | sed 's/^/    /' \
            || echo "    (설정 없음 - 기본값 사용)"
        ;;
    "U-03")
        echo "  [평가 기준] deny≤5, unlock_time 설정, pam_faillock.so 활성화"
        echo "  [현재 설정] /etc/security/faillock.conf"
        grep -E "^[[:space:]]*(deny|unlock_time|fail_interval|even_deny_root)" \
            /etc/security/faillock.conf 2>/dev/null | grep -v "^#" | sed 's/^/    /' \
            || echo "    (기본값 사용: deny=3, unlock_time=600)"
        echo "  [PAM 설정] /etc/pam.d/common-auth pam_faillock 라인"
        grep "pam_faillock" /etc/pam.d/common-auth 2>/dev/null | sed 's/^/    /' \
            || echo "    pam_faillock 미설정"
        ;;
    "U-06")
        echo "  [평가 기준] pam_wheel.so 설정 또는 su 접근 제한"
        echo "  [현재 설정] /etc/pam.d/su"
        grep -E "pam_wheel|wheel" /etc/pam.d/su 2>/dev/null | grep -v "^#" | sed 's/^/    /' \
            || echo "    pam_wheel 미설정 (su 무제한 허용)"
        echo "  [wheel 그룹 구성원]"
        getent group wheel 2>/dev/null | cut -d: -f4 | sed 's/^/    /' \
            || echo "    wheel 그룹 없음"
        ;;
    "U-07")
        echo "  [평가 기준] 불필요 계정(games/news/uucp/lp/irc/gnats)이 없거나 shell=nologin"
        echo "  [현재 설정]"
        for ACCT in games news uucp lp irc gnats pcap; do
            if getent passwd "$ACCT" > /dev/null 2>&1; then
                SH=$(getent passwd "$ACCT" | cut -d: -f7)
                printf "    %-12s shell=%s\n" "$ACCT" "$SH"
            else
                printf "    %-12s 계정 없음\n" "$ACCT"
            fi
        done
        ;;
    "U-12")
        echo "  [평가 기준] TMOUT ≤ 600 (10분) 설정"
        echo "  [현재 설정]"
        grep -rh "TMOUT" /etc/profile /etc/profile.d/ /etc/environment 2>/dev/null \
            | grep -v "^#" | sed 's/^/    /' || echo "    TMOUT 미설정"
        echo "    현재 세션 TMOUT=${TMOUT:-미설정}"
        ;;
    "U-14")
        echo "  [평가 기준] PATH에 '.' 또는 빈 요소 미포함"
        ROOT_PATH_NOW=$(timeout 5 su -l root -s /bin/bash -c 'echo $PATH' 2>/dev/null \
            || grep -oP '(?<=^PATH=")[^"]+' /etc/environment 2>/dev/null \
            || echo "${PATH}")
        echo "  [현재 설정] PATH=$ROOT_PATH_NOW"
        ;;
    "U-24")
        echo "  [평가 기준] 환경파일(profile/bashrc 등) other-write 없음"
        echo "  [현재 설정]"
        for F in /etc/profile /etc/bash.bashrc /etc/environment \
                 /root/.bashrc /root/.profile /root/.bash_profile; do
            [ -f "$F" ] || continue
            PERM=$(stat -c "%a" "$F")
            OWNER=$(stat -c "%U" "$F")
            printf "    %-35s perm=%s owner=%s\n" "$F" "$PERM" "$OWNER"
        done
        for F in /etc/profile.d/*.sh; do
            [ -f "$F" ] || continue
            PERM=$(stat -c "%a" "$F")
            printf "    %-35s perm=%s\n" "$F" "$PERM"
        done
        ;;
    "U-25")
        echo "  [평가 기준] world-writable 파일 없음 (/tmp, /var/tmp 제외)"
        echo "  [현재 설정]"
        WW=$(find / -xdev -perm -0002 -not -type l \
            -not -path "/proc/*" -not -path "/sys/*" -not -path "/dev/*" \
            -not -path "/run/*" -not -path "/tmp/*" -not -path "/var/tmp/*" \
            -not -path "/var/lib/docker/*" -not -path "/var/lib/containerd/*" \
            2>/dev/null | head -10)
        echo "${WW:-    world-writable 파일 없음}" | sed 's/^/    /'
        echo "  [조치 방법]"
        echo "    # scanengine 메타 파일은 644 정렬"
        echo "    chmod 644 /opt/scanengine/Update1/versions.*"
        echo "    chmod 644 /opt/scanengine/Update2/versions.*"
        echo "    # 그 외 world-writable 파일은 other-write 비트만 제거"
        echo "    find / -xdev -perm -0002 -not -type l ... -exec chmod o-w {} \\;"
        ;;
    "U-33")
        echo "  [평가 기준] 편집기 스왑 파일(.swp/.swo) 없음"
        echo "  [현재 설정]"
        SWP=$(find /etc /usr /var /root /home -name "*.swp" -o -name "*.swo" 2>/dev/null | head -10)
        echo "${SWP:-    스왑 파일 없음}" | sed 's/^/    /'
        ;;
    "U-62")
        echo "  [평가 기준] SSH Banner 설정 및 경고 메시지 존재"
        echo "  [현재 설정] sshd_config Banner"
        grep -E "^[[:space:]]*Banner" /etc/ssh/sshd_config 2>/dev/null | sed 's/^/    /' \
            || echo "    Banner 미설정"
        BANNER_FILE=$(grep -E "^[[:space:]]*Banner" /etc/ssh/sshd_config 2>/dev/null \
            | awk '{print $2}')
        if [ -n "$BANNER_FILE" ] && [ -f "$BANNER_FILE" ]; then
            echo "  [배너 내용] $BANNER_FILE"
            sed 's/^/    /' "$BANNER_FILE"
        fi
        ;;
    "U-64")
        echo "  [평가 기준] 보안 업데이트 없음"
        echo "  [현재 설정] apt 업그레이드 가능 패키지"
        apt list --upgradable 2>/dev/null | grep -v "^Listing" | head -10 \
            | sed 's/^/    /' || echo "    확인 불가"
        ;;
    "U-67")
        echo "  [평가 기준] /var/log 소유자=root, 권한 755 이하"
        echo "  [현재 설정]"
        stat -c "    /var/log: owner=%U group=%G perm=%a" /var/log 2>/dev/null
        find /var/log -maxdepth 1 -type f -name "*.log" 2>/dev/null | head -5 | while read -r F; do
            stat -c "    %n: owner=%U perm=%a" "$F"
        done
        ;;
    esac
}

print_manual() {
    local ID="$1"
    local DESC="$2"
    local GUIDE="$3"

    # 조치 실행 모드에서는 SELECTED_MAP에 있는 항목만 처리
    if $FILTER_MANUAL_SELECTED; then
        if [ -z "${SELECTED_MAP[$ID]+_}" ]; then
            return
        fi
    fi

    local STATUS
    STATUS=$(get_status "$ID")
    print_item "$ID" "MANUAL" "$DESC" "${STATUS:-N/A}"

    if [ "$STATUS" = "[취약]" ]; then
        CNT_MANUAL_VULN=$((CNT_MANUAL_VULN+1))
        log "MANUAL" "$ID [$DESC]: 수동 조치 필요"
        echo ""
        echo "  [수동 조치 가이드]"
        echo "$GUIDE" | while IFS= read -r LINE; do
            echo "    $LINE"
        done
    else
        log "MANUAL" "$ID: SKIP ($STATUS)"
    fi
}

# 전체 항목 현황 리포트 출력 (각 항목 헤더 + 현재 상태/근거 + MANUAL 조치 가이드)
print_full_report() {
    local SAVE_FILE="${1:-}"
    local TS; TS=$(date "+%Y-%m-%d %H:%M:%S")

    _report_body() {
        local CNT_GOOD=0 CNT_VULN=0 CNT_NA=0
        local CNT_AUTO_VULN=0 CNT_SEMI_VULN=0 CNT_MANUAL_VULN_R=0

        echo ""
        echo "================================================================================"
        echo "  KISA 2026 취약점 점검 현황 리포트 (전체 항목 상세)"
        echo "  생성: ${TS}"
        echo "  기준 보고서: ${REPORT_FILE}"
        echo "================================================================================"

        for i in "${!ITEM_IDS[@]}"; do
            local ID="${ITEM_IDS[$i]}"
            local TYPE="${ITEM_TYPES[$i]}"
            local DESC="${ITEM_DESCS[$i]}"
            local STATUS; STATUS=$(get_status "$ID")
            STATUS="${STATUS:-[N/A]}"

            case "$STATUS" in
                "[양호]") CNT_GOOD=$((CNT_GOOD+1)) ;;
                "[취약]") CNT_VULN=$((CNT_VULN+1))
                    case "$TYPE" in
                        AUTO)   CNT_AUTO_VULN=$((CNT_AUTO_VULN+1)) ;;
                        SEMI)   CNT_SEMI_VULN=$((CNT_SEMI_VULN+1)) ;;
                        MANUAL) CNT_MANUAL_VULN_R=$((CNT_MANUAL_VULN_R+1)) ;;
                    esac ;;
                *) CNT_NA=$((CNT_NA+1)) ;;
            esac

            # 항목 헤더
            echo ""
            echo "===================================================================="
            printf "  [%-6s] %-5s  |  %-10s  |  %s\n" "$TYPE" "$ID" "$STATUS" "$DESC"
            echo "===================================================================="

            # 보고서에서 현재 상태 / 점검 근거 블록 파싱 출력
            echo "  [현재 상태 / 점검 근거]"
            local BLOCK
            BLOCK=$(awk "/^[[:space:]]*[┌].*\[${ID}\]/,/^[[:space:]]*[└]/" "$REPORT_FILE" 2>/dev/null)
            if [ -n "$BLOCK" ]; then
                echo "$BLOCK" | sed 's/^/    /'
            else
                echo "    (보고서에서 데이터 없음 — infra_audit.sh 재실행 필요)"
            fi

            # AUTO/SEMI 항목: 평가 기준 + 현재 설정값 실시간 출력
            if [ "$TYPE" = "AUTO" ] || [ "$TYPE" = "SEMI" ]; then
                get_item_detail "$ID"
            fi
        done

        # MANUAL 취약 항목 조치 가이드 (run_manual_items() 재활용)
        echo ""
        echo "===================================================================="
        echo "  MANUAL 항목 수동 조치 가이드 (취약 항목만)"
        echo "===================================================================="
        run_manual_items

        # 최종 요약
        echo ""
        echo "================================================================================"
        printf "  [최종 요약]  전체: %d개  |  양호: %d개  |  취약: %d개  |  N/A: %d개\n" \
            "${#ITEM_IDS[@]}" "$CNT_GOOD" "$CNT_VULN" "$CNT_NA"
        printf "               AUTO 취약: %d개  |  SEMI 취약: %d개  |  MANUAL 취약: %d개\n" \
            "$CNT_AUTO_VULN" "$CNT_SEMI_VULN" "$CNT_MANUAL_VULN_R"
        echo "================================================================================"
    }

    if [ -n "$SAVE_FILE" ]; then
        _report_body | tee "$SAVE_FILE"
        echo ""
        echo "  [저장] 리포트 파일: $SAVE_FILE"
    else
        _report_body
    fi
}

# ==============================================================================
# 리포트 요약 파서 / 취약 ID 추출 / 조기 종료 시 단일 스냅샷 final 리포트 생성
# ==============================================================================
parse_summary() {
    # $1: 리포트 파일 경로 → "GOOD VULN NA" 출력
    local F="$1"
    local G V N
    G=$(grep -E "^[[:space:]]*양[[:space:]]*호[[:space:]]*:" "$F" 2>/dev/null | head -1 | grep -oE '[0-9]+' | head -1)
    V=$(grep -E "^[[:space:]]*취[[:space:]]*약[[:space:]]*:" "$F" 2>/dev/null | head -1 | grep -oE '[0-9]+' | head -1)
    N=$(grep -E "^[[:space:]]*N/A[[:space:]]*\(해당없음\)" "$F" 2>/dev/null | head -1 | grep -oE '[0-9]+' | head -1)
    echo "${G:-0} ${V:-0} ${N:-0}"
}

extract_vuln_ids() {
    # 보고서에서 [취약] 진단된 ID 목록 추출
    awk '/^┌─ \[U-[0-9]+\]/{
        match($0, /U-[0-9]+/); id=substr($0, RSTART, RLENGTH)
    }
    /진단결과:[[:space:]]*\[취약\]/{print id}' "$1" 2>/dev/null | sort -u
}

# 사용자가 조기 종료한 경우 (q / n / 취소 등) Before=After 단일 스냅샷 final 리포트 생성.
# DRY-RUN 이거나 이미 정상 흐름에서 final이 생성된 경우 no-op.
emit_snapshot_final() {
    if ${DRY_RUN:-false}; then return 0; fi
    if $FINAL_EMITTED; then return 0; fi
    [ -z "${REPORT_FILE:-}" ] && return 0
    [ ! -f "$REPORT_FILE" ] && return 0
    FINAL_EMITTED=true

    local BEFORE_FILE="$REPORT_FILE"
    local AFTER_FILE="$REPORT_FILE"
    local BEFORE_STATS AFTER_STATS BEFORE_VULNS AFTER_VULNS
    BEFORE_STATS=$(parse_summary "$BEFORE_FILE")
    AFTER_STATS="$BEFORE_STATS"
    BEFORE_VULNS=$(extract_vuln_ids "$BEFORE_FILE")
    AFTER_VULNS="$BEFORE_VULNS"

    local BG BV BN AG AV AN
    read -r BG BV BN <<< "$BEFORE_STATS"
    read -r AG AV AN <<< "$AFTER_STATS"

    local RESOLVED="" REMAIN="$BEFORE_VULNS" NEW=""
    REMAIN=$(echo "$REMAIN" | tr '\n' ' ')

    local FINAL_REPORT="${SCRIPT_DIR}/infra_remediate_final_${TIMESTAMP}.txt"
    {
        echo "================================================================================"
        echo "         조치 적용 최종 리포트 (단일 스냅샷 — 조기 종료/조치 미적용)"
        echo "         생성: $(date "+%Y-%m-%d %H:%M:%S")"
        echo "================================================================================"
        echo ""
        echo " [입력 리포트]"
        echo "   Before : $BEFORE_FILE"
        echo "   After  : $AFTER_FILE"
        echo "   (※ 자동 조치 미적용 — Before=After 단일 스냅샷)"
        echo ""
        echo " [조치 단계 요약]"
        printf "   적용 완료 (AUTO/SEMI) : %d 개\n" "$CNT_APPLIED"
        printf "   SKIP (양호/N/A)       : %d 개\n" "$CNT_SKIP"
        printf "   SKIP (미승인)         : %d 개\n" "$CNT_SKIPPED"
        printf "   MANUAL 취약 항목      : %d 개\n" "$CNT_MANUAL_VULN"
        echo ""
        echo " [재점검 결과 비교]"
        printf "   %-15s %8s %8s %8s\n" "구분" "Before" "After" "변화"
        printf "   ---------------------------------------------\n"
        printf "   %-15s %8d %8d %+8d\n" "양호" "$BG" "$AG" "$((AG-BG))"
        printf "   %-15s %8d %8d %+8d\n" "취약" "$BV" "$AV" "$((AV-BV))"
        printf "   %-15s %8d %8d %+8d\n" "N/A" "$BN" "$AN" "$((AN-BN))"
        echo ""
        echo " [항목별 상태 변화]"
        echo "   해결된 항목 (취약 → 양호/N/A) : (없음)"
        echo "   잔존 취약 항목               : ${REMAIN:-(없음)}"
        echo "   신규 발견 취약 항목 (regression) : (없음)"
        echo ""
        echo " [백업 / 로그]"
        [ -d "$BACKUP_DIR" ] && echo "   설정 백업 : $BACKUP_DIR/"
        echo "   조치 로그 : $REMEDIATE_LOG"
        echo ""
        echo "================================================================================"
        if [ "$AV" -eq 0 ]; then
            echo "   [최종 판정] 취약 항목 없음 — 양호"
        else
            echo "   [최종 판정] 자동 조치 미적용 — 현재 취약 ${AV}건 (MANUAL 가이드 참조)"
        fi
        echo "================================================================================"
    } | tee "$FINAL_REPORT"

    log "POST" "최종 리포트(스냅샷): $FINAL_REPORT (취약 ${AV}건)"
}
# ==============================================================================
# MANUAL 항목 가이드 정의 (각 항목별 상세 가이드)
# ==============================================================================

run_manual_items() {

print_manual "U-04" "비밀번호 파일 보호" \
"/etc/passwd에 평문 비밀번호 저장 계정이 있는 경우:
  shadow 패키지 설치 및 pwconv 실행:
    apt-get install -y passwd
    pwconv
  확인: awk -F: '\$2 != \"x\" {print \$1}' /etc/passwd"

print_manual "U-05" "root 이외 UID=0 금지" \
"UID=0인 root 외 계정 발견 시 UID 변경 또는 계정 삭제:
  UID=0 계정 확인: awk -F: '\$3==0 && \$1!=\"root\" {print \$1}' /etc/passwd
  UID 변경: usermod -u <새UID> <계정명>
  계정 삭제: userdel -r <계정명>
  [주의] 삭제 전 해당 계정 소유 파일 확인 필요: find / -uid 0 -not -user root"

print_manual "U-08" "관리자 그룹 최소 계정 관리" \
"sudo/wheel 그룹에 최소한의 계정만 포함되어야 합니다.
  sudo 그룹 확인: getent group sudo
  불필요 계정 sudo 그룹 제거: gpasswd -d <계정명> sudo
  현재 sudo 그룹 구성원 목록: grep '^sudo' /etc/group"

print_manual "U-09" "계정이 존재하지 않는 GID 금지" \
"orphan GID(그룹 미존재) 계정을 수정합니다:
  확인: awk -F: '{print \$1, \$4}' /etc/passwd | while read U G; do getent group \$G >/dev/null 2>&1 || echo \"orphan: \$U GID=\$G\"; done
  조치: usermod -g <유효한GID> <계정명> 또는 groupadd로 그룹 생성"

print_manual "U-10" "동일한 UID 금지" \
"중복 UID 계정을 확인하고 수정합니다:
  확인: awk -F: '{print \$3}' /etc/passwd | sort | uniq -d
  조치: usermod -u <새UID> <계정명>
  [주의] UID 변경 시 해당 계정 소유 파일 소유자도 변경됨: find / -uid <구UID> -exec chown <계정명> {} \;"

print_manual "U-11" "사용자 Shell 점검" \
"로그인 불필요 시스템 계정(UID<1000)에 nologin 설정:
  확인: awk -F: '\$3<1000 && \$1!=\"root\" && \$7!~/nologin|false|sync/ {print \$1, \$7}' /etc/passwd
  조치: usermod -s /usr/sbin/nologin <계정명>
  또는 일괄 처리 (root/sync 제외):
    awk -F: '\$3>0 && \$3<1000 && \$7!~/nologin|false/ {print \$1}' /etc/passwd | xargs -I{} usermod -s /usr/sbin/nologin {}"

print_manual "U-13" "안전한 비밀번호 암호화 알고리즘" \
"MD5 또는 약한 알고리즘 사용 시 SHA-512(yescrypt)로 변경:
  /etc/login.defs 설정:
    ENCRYPT_METHOD  SHA512
  /etc/pam.d/common-password 설정:
    password [success=1 default=ignore] pam_unix.so obscure use_authtok try_first_pass yescrypt
  [주의] 변경 후 기존 사용자는 다음 비밀번호 변경 시부터 새 알고리즘 적용"

print_manual "U-15" "소유자 없는 파일 점검" \
"소유자 없는 파일 목록 (운영자가 직접 판단, 컨테이너/마운트 레이어 제외):
$(find / -xdev \( -nouser -o -nogroup \) \
    -not -path '/proc/*' -not -path '/sys/*' \
    -not -path '/dev/*' -not -path '/run/*' \
    -not -path '/tmp/*' -not -path '/var/tmp/*' \
    -not -path '/data/*' -not -path '/logs/*' \
    -not -path '/application/*' -not -path '/opt/mnx/*' \
    -not -path '/mnt/*' -not -path '/media/*' \
    -not -path '/var/lib/docker/*' -not -path '/var/lib/containerd/*' \
    2>/dev/null | head -30 | sed 's/^/  /')

  검사 제외 경로 (호스트 점검 범위 밖):
    /proc /sys /dev /run /tmp /var/tmp /data /logs /application /opt/mnx
    /mnt /media /var/lib/docker /var/lib/containerd

  조치 방법:
    chown root:root <파일>   # root에 귀속
    rm -f <파일>             # 불필요 파일 삭제 (운영자 판단 필요)

  전체 목록 (예외 적용):
    find / -xdev \( -nouser -o -nogroup \) -not -path '/var/lib/containerd/*' \\
      -not -path '/var/lib/docker/*' -not -path '/proc/*' -not -path '/sys/*' \\
      -not -path '/data/*' -not -path '/logs/*' 2>/dev/null"

print_manual "U-16" "/etc/passwd 소유자 및 권한" \
"/etc/passwd 권한 조치:
  chown root:root /etc/passwd
  chmod 644 /etc/passwd
  현재 상태: $(stat -c 'owner=%U, group=%G, perm=%a' /etc/passwd 2>/dev/null)"

print_manual "U-17" "시스템 시작 스크립트 권한" \
"/etc/init.d 스크립트 other-write 권한 제거:
  확인: find /etc/init.d -perm -o+w -o ! -user root 2>/dev/null
  조치:
    chmod o-w <파일>
    chown root:root <파일>
  주의: 실행 권한(x)은 유지해야 서비스 정상 동작"

print_manual "U-18" "/etc/shadow 소유자 및 권한" \
"/etc/shadow 권한 조치 (Ubuntu 기본: root:shadow 640):
  chown root:shadow /etc/shadow
  chmod 640 /etc/shadow
  현재 상태: $(stat -c 'owner=%U, group=%G, perm=%a' /etc/shadow 2>/dev/null)"

print_manual "U-19" "/etc/hosts 소유자 및 권한" \
"/etc/hosts 권한 조치:
  chown root:root /etc/hosts
  chmod 644 /etc/hosts
  현재 상태: $(stat -c 'owner=%U, group=%G, perm=%a' /etc/hosts 2>/dev/null)"

print_manual "U-20" "/etc/(x)inetd.conf 소유자 및 권한" \
"inetd/xinetd 설정 파일 권한 조치:
  chown root:root /etc/inetd.conf /etc/xinetd.conf
  chmod 600 /etc/inetd.conf /etc/xinetd.conf
  현재 상태:
$(for F in /etc/inetd.conf /etc/xinetd.conf; do [ -f \"\$F\" ] && stat -c \"  $F: owner=%U, perm=%a\" \"$F\"; done 2>/dev/null || echo '  inetd/xinetd 미설치')"

print_manual "U-21" "/etc/(r)syslog.conf 소유자 및 권한" \
"/etc/rsyslog.conf 권한 조치 (KISA 기준: root 소유, 640 이하):
  chown root:root /etc/rsyslog.conf
  chmod 640 /etc/rsyslog.conf
  find /etc/rsyslog.d -type f -exec chown root:root {} \;
  find /etc/rsyslog.d -type f -exec chmod 640 {} \;
  [주의] 644는 other-read 허용 → KISA 기준(640 이하) 위반
  현재 상태: $(stat -c 'owner=%U, perm=%a' /etc/rsyslog.conf 2>/dev/null || echo '파일 없음')"

print_manual "U-22" "/etc/services 소유자 및 권한" \
"/etc/services 권한 조치:
  chown root:root /etc/services
  chmod 644 /etc/services
  현재 상태: $(stat -c 'owner=%U, perm=%a' /etc/services 2>/dev/null || echo '파일 없음')"

print_manual "U-23" "SUID/SGID 설정 파일 점검" \
"허용 목록 외 SUID/SGID 파일 권한 제거:
  [현재 발견된 허용 목록 외 파일 - 보고서 기준]
$(awk '/┌─ \[U-23\]/,/└──/' "$REPORT_FILE" 2>/dev/null | grep '의심스러운' | sed 's/.*: /  /; s/ \//\n  \//g' | grep '/')
  [조치 방법]
  1. 위 파일 확인 후 불필요하면 SUID/SGID 제거:
       chmod -s <파일경로>
  2. 허용 목록에 추가할 정상 파일이라면 스크립트의 ALLOWED_SUID 배열에 추가
  [허용 기준 (Ubuntu 22.04 정상 SUID/SGID)]
    /usr/bin/sudo, /usr/bin/passwd, /usr/bin/su, /usr/bin/mount, /usr/bin/crontab
    /usr/bin/ssh-agent, /usr/libexec/polkit-agent-helper-1 등
  [절대 제거 금지] passwd, sudo, su, mount, ping, ssh-keysign"

print_manual "U-26" "/dev 불법 device 파일 점검" \
"/dev 내 일반 파일(fake device) 점검:
  확인: find /dev -not \( -type b -o -type c -o -type d -o -type l -o -type p -o -type s \) -type f 2>/dev/null
  조치: 불필요한 일반 파일 삭제 (운영자 판단 필요)
    rm -f <파일>"

print_manual "U-27" ".rhosts, hosts.equiv 사용 금지" \
"r 계열 서비스 접근 제어 파일 조치:
  /etc/hosts.equiv 내 '+' 설정 제거 또는 파일 삭제:
    rm -f /etc/hosts.equiv
    또는 sed -i '/^+/d' /etc/hosts.equiv && chmod 600 /etc/hosts.equiv
  /root/.rhosts 조치:
    rm -f /root/.rhosts
    또는 chmod 600 /root/.rhosts && sed -i '/^+/d' /root/.rhosts"

print_manual "U-28" "접속 IP 및 포트 제한 (방화벽)" \
"[절대 자동 실행 금지 - SSH 끊김 위험]

UFW 설정 예시 (반드시 수동으로 설정):
  1. SSH 허용 규칙을 먼저 설정:
     ufw allow from <관리자IP> to any port 22 proto tcp

  2. 기본 정책 설정:
     ufw default deny incoming
     ufw default allow outgoing

  3. 업무 포트 허용:
     ufw allow <업무포트>/tcp

  4. 활성화:
     ufw enable

  현재 상태: $(ufw status 2>/dev/null | head -3 || echo 'UFW 미설치')

[주의] ufw enable 전 반드시 SSH 허용 규칙 확인 필수"

print_manual "U-29" "hosts.lpd 파일 소유자 및 권한" \
"/etc/hosts.lpd 파일 권한 조치:
  chown root:root /etc/hosts.lpd
  chmod 600 /etc/hosts.lpd
  LPD 미사용 시 파일 삭제 가능: rm -f /etc/hosts.lpd
  현재 상태: $(stat -c 'owner=%U, perm=%a' /etc/hosts.lpd 2>/dev/null || echo '파일 없음 (N/A)')"

print_manual "U-30" "UMASK 설정 관리" \
"UMASK 022 이상 설정:
  /etc/profile 또는 /etc/bash.bashrc에 추가:
    umask 027
  /etc/login.defs 설정:
    UMASK  027
  현재 설정 확인:
$(grep -h "umask\|UMASK" /etc/profile /etc/bash.bashrc /etc/login.defs 2>/dev/null | grep -v "^#" || echo '  미설정')"

print_manual "U-31" "홈 디렉토리 소유자 및 권한" \
"홈 디렉토리 other-write 권한 제거:
  확인: ls -la /home/ /root
  조치:
    chmod o-w /home/<계정명>
    chmod 700 /root
  일괄 처리 (사용 주의):
    find /home -maxdepth 1 -type d -not -name 'home' | xargs chmod o-w"

print_manual "U-32" "홈 디렉토리 존재 여부" \
"홈 디렉토리 미존재 계정 확인 및 생성:
  확인: awk -F: '\$3>=1000 && \$7!~/nologin|false/ {print \$1, \$6}' /etc/passwd | while read U H; do [ -d \"\$H\" ] || echo \"missing: \$U \$H\"; done
  조치: mkhomedir_helper <계정명> 또는 mkdir -p <홈디렉토리> && chown <계정명>:<계정명> <홈디렉토리>"

print_manual "U-34" "Finger 서비스 비활성화" \
"Finger 서비스 비활성화 및 제거:
  현재 상태: $(dpkg -l finger 2>/dev/null | grep '^ii' | head -1 || echo 'finger 미설치')
  제거: apt-get remove -y finger fingerd
  서비스 비활성화:
    systemctl stop finger.service 2>/dev/null
    systemctl disable finger.service 2>/dev/null"

print_manual "U-35" "공유 서비스 익명 접근 제한" \
"Samba 익명 접근 제한:
  현재 상태: $(systemctl is-active smbd 2>/dev/null || echo '비활성')
  /etc/samba/smb.conf 설정:
    [global]
      guest ok = no
      map to guest = Never
  NFS 익명 접근 제한:
    /etc/exports에서 no_root_squash 제거하고 root_squash 사용
  Samba 재시작: systemctl restart smbd"

print_manual "U-36" "r 계열 서비스 비활성화" \
"rsh, rlogin, rexec 서비스 비활성화:
  현재 상태: $(for S in rsh rlogin rexec; do systemctl is-active $S 2>/dev/null | grep -q active && echo \"$S: active\"; done || echo '비활성')
  패키지 제거: apt-get remove -y rsh-client rsh-redone-client
  서비스 비활성화:
    for SVC in rsh rlogin rexec; do
      systemctl stop \$SVC 2>/dev/null; systemctl disable \$SVC 2>/dev/null
    done"

print_manual "U-37" "crontab 설정파일 권한" \
"/etc/crontab 권한 조치 (KISA 기준: root 소유, 640 이하):
  chmod 640 /etc/crontab
  chown root:root /etc/crontab
  cron 디렉터리 (cron 데몬 접근 필요 - 755 유지):
    chmod 755 /etc/cron.d /etc/cron.daily /etc/cron.hourly /etc/cron.weekly /etc/cron.monthly
  현재 상태:
$(stat -c '    /etc/crontab: owner=%U, perm=%a' /etc/crontab 2>/dev/null || echo '    /etc/crontab: 파일 없음')
$(stat -c '    /etc/cron.d: owner=%U, perm=%a' /etc/cron.d 2>/dev/null || echo '    /etc/cron.d: 없음')"

print_manual "U-38" "DoS 취약 서비스 비활성화" \
"echo, discard, daytime, chargen 서비스 비활성화:
  현재 상태: $(for S in echo.socket discard.socket daytime.socket chargen.socket; do systemctl is-active $S 2>/dev/null | grep -q active && echo \"$S: active\"; done || echo '관련 서비스 비활성')
  비활성화:
    for SVC in echo discard daytime chargen time; do
      systemctl stop \${SVC}.socket 2>/dev/null
      systemctl disable \${SVC}.socket 2>/dev/null
    done
  inetd 기반: /etc/inetd.conf에서 해당 서비스 주석 처리 후 inetd 재시작"

print_manual "U-39" "불필요한 NFS 서비스 비활성화" \
"NFS 서비스 비활성화:
  현재 상태: $(systemctl is-active nfs-server 2>/dev/null || echo '비활성')
  미사용 시 비활성화:
    systemctl stop nfs-server nfs-kernel-server rpcbind 2>/dev/null
    systemctl disable nfs-server nfs-kernel-server rpcbind 2>/dev/null
  필요 시 /etc/exports에서 접근 IP 제한 설정"

print_manual "U-40" "NFS 접근 통제" \
"NFS 사용 중인 경우 /etc/exports 접근 통제:
  와일드카드(*) 대신 특정 IP/네트워크 지정:
    /data  192.168.1.0/24(ro,sync,no_subtree_check,root_squash)
  권한 설정:
    chown root:root /etc/exports
    chmod 644 /etc/exports
  exportfs -ra 로 설정 반영"

print_manual "U-41" "불필요한 automountd 제거" \
"autofs 서비스 비활성화:
  현재 상태: $(systemctl is-active autofs 2>/dev/null || echo '비활성')
  비활성화:
    systemctl stop autofs
    systemctl disable autofs
  필요 시 특정 마운트만 /etc/fstab에 정적으로 설정"

print_manual "U-42" "불필요한 RPC 서비스 비활성화" \
"RPC 서비스 비활성화 (NFS 미사용 시):
  현재 상태: $(for S in rpcbind rpcd rpc-statd; do systemctl is-active $S 2>/dev/null | grep -q active && echo \"$S: active\"; done || echo '비활성')
  비활성화:
    systemctl stop rpcbind rpcbind.socket 2>/dev/null
    systemctl disable rpcbind rpcbind.socket 2>/dev/null
  [주의] NFS 사용 중이면 rpcbind 필요"

print_manual "U-43" "NIS/NIS+ 서비스 점검" \
"NIS 서비스 비활성화 및 제거:
  현재 상태: $(systemctl is-active ypbind 2>/dev/null || echo '비활성')
  비활성화:
    systemctl stop ypbind ypserv 2>/dev/null
    systemctl disable ypbind ypserv 2>/dev/null
  패키지 제거: apt-get remove -y nis
  /etc/nsswitch.conf에서 nis 항목 제거"

print_manual "U-44" "tftp, talk 서비스 비활성화" \
"tftp, talk 서비스 비활성화:
  현재 상태: $(for S in tftpd tftpd-hpa talkd; do dpkg -l $S 2>/dev/null | grep -q '^ii' && echo \"$S: installed\"; done || echo '미설치')
  패키지 제거:
    apt-get remove -y tftpd tftpd-hpa talkd
  서비스 비활성화:
    systemctl stop tftpd talkd 2>/dev/null
    systemctl disable tftpd talkd 2>/dev/null"

print_manual "U-45" "메일 서비스 버전 점검" \
"메일 서비스 최신 버전 유지:
  현재 버전: $(postconf -d mail_version 2>/dev/null || dpkg -l postfix 2>/dev/null | grep '^ii' | awk '{print $3}' || echo '미설치')
  보안 업데이트: apt-get update && apt-get install -y --only-upgrade postfix
  최신 버전 확인: https://www.postfix.org/announcements.html"

print_manual "U-46" "일반 사용자의 메일 서비스 실행 방지" \
"메일 서비스 실행 계정 확인:
  현재 프로세스: $(ps aux | grep -E 'postfix|sendmail|exim' | grep -v grep | awk '{print $1, $11}' || echo '메일 서비스 미실행')
  postfix는 root 또는 postfix 계정으로 실행되어야 합니다:
    postconf -e 'mail_owner = postfix'
    postconf -e 'setgid_group = postdrop'"

print_manual "U-47" "스팸 메일 릴레이 제한" \
"postfix 릴레이 제한 설정:
  현재 설정: $(postconf -n smtpd_recipient_restrictions 2>/dev/null || echo 'postfix 비활성')
  /etc/postfix/main.cf 설정:
    smtpd_recipient_restrictions = permit_mynetworks, permit_sasl_authenticated, reject_unauth_destination
    mynetworks = 127.0.0.0/8 [::ffff:127.0.0.0]/104 [::1]/128
  재시작: systemctl restart postfix"

print_manual "U-48" "SMTP expn, vrfy 명령어 제한" \
"postfix vrfy 명령어 비활성화:
  현재 설정: $(postconf -n disable_vrfy_command 2>/dev/null || echo 'postfix 비활성')
  /etc/postfix/main.cf 설정:
    disable_vrfy_command = yes
  재시작: systemctl restart postfix"

print_manual "U-49" "DNS 보안 버전 패치" \
"BIND9 보안 패치 적용:
  현재 버전: $(named -v 2>/dev/null || echo 'BIND9 미설치/비활성')
  보안 업데이트: apt-get update && apt-get install -y --only-upgrade bind9
  최신 버전 확인: https://www.isc.org/bind/"

print_manual "U-50" "DNS Zone Transfer 설정" \
"Zone Transfer 접근 제한:
  /etc/bind/named.conf.options 또는 named.conf 설정:
    options {
      allow-transfer { none; };  # 기본 전체 차단
    };
  zone 별 허용:
    zone \"example.com\" {
      allow-transfer { 192.168.1.10; };  # secondary DNS만 허용
    };
  재시작: systemctl restart bind9"

print_manual "U-51" "DNS 동적 업데이트 설정 금지" \
"BIND9 동적 업데이트 비활성화:
  현재 설정: $(grep -r 'allow-update' /etc/bind/ 2>/dev/null || echo '설정 없음')
  /etc/bind/named.conf.options:
    options {
      allow-update { none; };
    };
  재시작: systemctl restart bind9"

print_manual "U-52" "Telnet 서비스 비활성화" \
"Telnet 서비스 비활성화 및 제거:
  현재 상태: $(systemctl is-active telnetd 2>/dev/null || echo '비활성')
  패키지 제거: apt-get remove -y telnetd telnet-server
  포트 확인: ss -tlnp | grep ':23 '
  대안: SSH 사용 (OpenSSH)"

print_manual "U-53" "FTP 서비스 정보 노출 제한" \
"FTP 배너 정보 최소화:
  vsftpd /etc/vsftpd.conf 설정:
    ftpd_banner=Welcome to FTP service.
  재시작: systemctl restart vsftpd"

print_manual "U-54" "암호화되지 않은 FTP 비활성화" \
"평문 FTP 비활성화, SFTP/FTPS 전환:
  현재 상태: $(systemctl is-active vsftpd 2>/dev/null || echo '비활성')
  FTP 비활성화: systemctl stop vsftpd && systemctl disable vsftpd
  SFTP(OpenSSH 내장) 사용 권고:
    /etc/ssh/sshd_config에 Subsystem sftp /usr/lib/openssh/sftp-server 확인"

print_manual "U-55" "FTP 계정 Shell 제한" \
"ftp 계정 shell nologin 설정:
  현재 설정: $(getent passwd ftp 2>/dev/null || echo 'ftp 계정 없음')
  조치: usermod -s /usr/sbin/nologin ftp"

print_manual "U-56" "FTP 서비스 접근 제어 설정" \
"vsftpd 접근 제어 설정:
  /etc/vsftpd.conf:
    userlist_enable=YES
    userlist_deny=NO
    userlist_file=/etc/vsftpd.user_list
  TCP Wrapper:
    /etc/hosts.allow: vsftpd: 192.168.1.0/24
    /etc/hosts.deny: vsftpd: ALL
  재시작: systemctl restart vsftpd"

print_manual "U-57" "Ftpusers 파일 설정 (FTP root 차단)" \
"FTP root 계정 접속 차단:
  /etc/ftpusers 또는 /etc/vsftpd.ftpusers에 root 등록:
    echo 'root' >> /etc/ftpusers
  vsftpd.conf에 ftpusers 설정:
    userlist_file=/etc/vsftpd.ftpusers
    userlist_deny=YES"

print_manual "U-58" "불필요한 SNMP 서비스 점검" \
"SNMP 서비스 비활성화:
  현재 상태: $(systemctl is-active snmpd 2>/dev/null || echo '비활성')
  SNMP 미사용 시:
    systemctl stop snmpd
    systemctl disable snmpd
  필요 시 SNMPv3 사용 및 접근 IP 제한 설정"

print_manual "U-59" "안전한 SNMP 버전 사용" \
"SNMPv3 설정 (v1/v2c 비활성화):
  /etc/snmp/snmpd.conf:
    # v1/v2c community 주석 처리:
    # rocommunity public default
    # 대신 v3 사용자 설정:
    createUser authUser SHA \"authpassphrase\" AES \"privpassphrase\"
    rouser authUser
  재시작: systemctl restart snmpd"

print_manual "U-60" "SNMP Community String 복잡성" \
"public/private 기본 Community String 변경:
  /etc/snmp/snmpd.conf:
    # public 제거:
    # rocommunity public default
    # 복잡한 문자열 사용 (8자 이상, 영숫특 조합):
    rocommunity <복잡한문자열> 192.168.1.0/24
  재시작: systemctl restart snmpd"

print_manual "U-61" "SNMP Access Control 설정" \
"SNMP 접근 IP 제한:
  /etc/snmp/snmpd.conf:
    com2sec readonly  192.168.1.100  <community>
    com2sec readonly  default        \"\"
  agentAddress 제한:
    agentAddress udp:192.168.1.10:161
  재시작: systemctl restart snmpd"

print_manual "U-63" "sudo 명령어 접근 관리" \
"/etc/sudoers 권한 조치:
  현재 상태: $(stat -c 'owner=%U, perm=%a' /etc/sudoers 2>/dev/null)
  권한 조치:
    chown root:root /etc/sudoers
    chmod 440 /etc/sudoers
  NOPASSWD 규칙 검토:
$(grep -i NOPASSWD /etc/sudoers /etc/sudoers.d/* 2>/dev/null | grep -v '^#' || echo '    NOPASSWD 설정 없음')
  visudo 명령어로 안전하게 편집: visudo"

print_manual "U-65" "NTP 및 시각 동기화 설정" \
"NTP 동기화 설정:
  현재 상태: $(timedatectl status 2>/dev/null | grep -E 'NTP|synchronized' || echo '확인 불가')
  systemd-timesyncd 사용 (기본):
    timedatectl set-ntp true
    /etc/systemd/timesyncd.conf:
      [Time]
      NTP=time.kriss.re.kr ntp.kornet.net
      FallbackNTP=pool.ntp.org
    systemctl restart systemd-timesyncd
  chrony 사용 시:
    apt-get install -y chrony
    /etc/chrony.conf: server time.kriss.re.kr iburst
    systemctl restart chrony"

print_manual "U-66" "정책에 따른 시스템 로깅 설정" \
"rsyslog 설정 확인 및 강화:
  현재 상태: $(systemctl is-active rsyslog 2>/dev/null || echo '비활성')
  rsyslog 활성화:
    systemctl start rsyslog && systemctl enable rsyslog
  /etc/rsyslog.conf 주요 로그 설정:
    auth,authpriv.*   /var/log/auth.log
    kern.*            /var/log/kern.log
    mail.*            /var/log/mail.log
    *.warn            /var/log/syslog
  로그 로테이션 확인: cat /etc/logrotate.d/rsyslog
  원격 로그 서버 설정:
    *.* @@<로그서버IP>:514"

}


# ==============================================================================
# 배너 출력
# ==============================================================================
echo ""
echo "================================================================================"
echo "  주요정보통신기반시설 취약점 조치 스크립트 v3.0.0"
echo "  기준: 2026년판 KISA 상세가이드  |  대상: Ubuntu 22.04"
echo "================================================================================"
echo "  보고서: $REPORT_FILE"
echo "  모드  : $(${DRY_RUN} && echo 'DRY-RUN (변경 없음)' || (${AUTO_MODE} && echo 'AUTO (무인 실행)' || echo '대화형'))"
echo "  로그  : $REMEDIATE_LOG"
echo "  백업  : $BACKUP_DIR/"
echo "================================================================================"
echo ""

log "START" "조치 시작 - 보고서: $REPORT_FILE | 모드: $(${DRY_RUN} && echo DRY-RUN || (${AUTO_MODE} && echo AUTO || echo INTERACTIVE))"

# ==============================================================================
# 항목 정의 (ID / 분류 / 설명)
# ==============================================================================
# 배열 인덱스: 0=ID, 1=TYPE, 2=DESC
declare -a ITEM_IDS=()
declare -a ITEM_TYPES=()
declare -a ITEM_DESCS=()

add_item() {
    ITEM_IDS+=("$1")
    ITEM_TYPES+=("$2")
    ITEM_DESCS+=("$3")
}

# AUTO
add_item "U-01" "AUTO"   "root 계정 원격 접속 제한"
add_item "U-02" "AUTO"   "비밀번호 관리정책 설정"
add_item "U-03" "AUTO"   "계정 잠금 임계값 설정"
add_item "U-12" "AUTO"   "세션 종료 시간 설정 (TMOUT)"
add_item "U-14" "AUTO"   "root PATH에 현재 디렉터리 포함 금지"
add_item "U-25" "AUTO"   "world writable 파일 권한 제거"
add_item "U-64" "AUTO"   "최신 보안 패치 적용"
add_item "U-67" "AUTO"   "로그 디렉터리 소유자 및 권한 설정"
# SEMI
add_item "U-06" "SEMI"   "사용자 계정 su 기능 제한"
add_item "U-07" "SEMI"   "불필요한 계정 shell 비활성화"
add_item "U-24" "MANUAL" "사용자 환경변수 파일 other-write 제거 (시스템 파일 영향 위험으로 수동 처리)"
add_item "U-33" "SEMI"   "숨겨진 파일 (.swp) 점검 및 제거"
add_item "U-62" "SEMI"   "로그인 경고 메시지 설정"
# MANUAL
add_item "U-04" "MANUAL" "비밀번호 파일 보호"
add_item "U-05" "MANUAL" "root 이외 UID=0 금지"
add_item "U-08" "MANUAL" "관리자 그룹 최소 계정 관리"
add_item "U-09" "MANUAL" "계정이 존재하지 않는 GID 금지"
add_item "U-10" "MANUAL" "동일한 UID 금지"
add_item "U-11" "MANUAL" "사용자 Shell 점검"
add_item "U-13" "MANUAL" "안전한 비밀번호 암호화 알고리즘"
add_item "U-15" "MANUAL" "소유자 없는 파일 점검"
add_item "U-16" "MANUAL" "/etc/passwd 소유자 및 권한"
add_item "U-17" "MANUAL" "시스템 시작 스크립트 권한"
add_item "U-18" "MANUAL" "/etc/shadow 소유자 및 권한"
add_item "U-19" "MANUAL" "/etc/hosts 소유자 및 권한"
add_item "U-20" "MANUAL" "/etc/(x)inetd.conf 소유자 및 권한"
add_item "U-21" "MANUAL" "/etc/(r)syslog.conf 소유자 및 권한"
add_item "U-22" "MANUAL" "/etc/services 소유자 및 권한"
add_item "U-23" "MANUAL" "SUID/SGID 설정 파일 점검"
add_item "U-26" "MANUAL" "/dev 불법 device 파일 점검"
add_item "U-27" "MANUAL" ".rhosts, hosts.equiv 사용 금지"
add_item "U-28" "MANUAL" "접속 IP 및 포트 제한 (방화벽)"
add_item "U-29" "MANUAL" "hosts.lpd 파일 소유자 및 권한"
add_item "U-30" "MANUAL" "UMASK 설정 관리"
add_item "U-31" "MANUAL" "홈 디렉토리 소유자 및 권한"
add_item "U-32" "MANUAL" "홈 디렉토리 존재 여부"
add_item "U-34" "MANUAL" "Finger 서비스 비활성화"
add_item "U-35" "MANUAL" "공유 서비스 익명 접근 제한"
add_item "U-36" "MANUAL" "r 계열 서비스 비활성화"
add_item "U-37" "MANUAL" "crontab 설정파일 권한"
add_item "U-38" "MANUAL" "DoS 취약 서비스 비활성화"
add_item "U-39" "MANUAL" "불필요한 NFS 서비스 비활성화"
add_item "U-40" "MANUAL" "NFS 접근 통제"
add_item "U-41" "MANUAL" "불필요한 automountd 제거"
add_item "U-42" "MANUAL" "불필요한 RPC 서비스 비활성화"
add_item "U-43" "MANUAL" "NIS/NIS+ 서비스 점검"
add_item "U-44" "MANUAL" "tftp, talk 서비스 비활성화"
add_item "U-45" "MANUAL" "메일 서비스 버전 점검"
add_item "U-46" "MANUAL" "일반 사용자의 메일 서비스 실행 방지"
add_item "U-47" "MANUAL" "스팸 메일 릴레이 제한"
add_item "U-48" "MANUAL" "SMTP expn, vrfy 명령어 제한"
add_item "U-49" "MANUAL" "DNS 보안 버전 패치"
add_item "U-50" "MANUAL" "DNS Zone Transfer 설정"
add_item "U-51" "MANUAL" "DNS 동적 업데이트 설정 금지"
add_item "U-52" "MANUAL" "Telnet 서비스 비활성화"
add_item "U-53" "MANUAL" "FTP 서비스 정보 노출 제한"
add_item "U-54" "MANUAL" "암호화되지 않은 FTP 비활성화"
add_item "U-55" "MANUAL" "FTP 계정 Shell 제한"
add_item "U-56" "MANUAL" "FTP 서비스 접근 제어 설정"
add_item "U-57" "MANUAL" "Ftpusers 파일 설정 (FTP root 차단)"
add_item "U-58" "MANUAL" "불필요한 SNMP 서비스 점검"
add_item "U-59" "MANUAL" "안전한 SNMP 버전 사용"
add_item "U-60" "MANUAL" "SNMP Community String 복잡성"
add_item "U-61" "MANUAL" "SNMP Access Control 설정"
add_item "U-63" "MANUAL" "sudo 명령어 접근 관리"
add_item "U-65" "MANUAL" "NTP 및 시각 동기화 설정"
add_item "U-66" "MANUAL" "정책에 따른 시스템 로깅 설정"

TOTAL_ITEMS=${#ITEM_IDS[@]}

# ==============================================================================
# 대화형 선택 메뉴 (--dry-run / --auto 아닐 때)
# ==============================================================================
declare -a SELECTED_IDS=()

if ! $DRY_RUN && ! $AUTO_MODE; then
    echo ""
    echo "=== 조치 항목 선택 ==="
    echo ""
    echo "  [취약 항목 목록]"
    echo ""

    declare -a MENU_IDS=()
    declare -a MENU_TYPES=()
    declare -a MENU_DESCS=()

    IDX=0
    for i in "${!ITEM_IDS[@]}"; do
        ID="${ITEM_IDS[$i]}"
        TYPE="${ITEM_TYPES[$i]}"
        DESC="${ITEM_DESCS[$i]}"
        STATUS=$(get_status "$ID")

        if [ "$STATUS" = "[취약]" ]; then
            IDX=$((IDX+1))
            MENU_IDS+=("$ID")
            MENU_TYPES+=("$TYPE")
            MENU_DESCS+=("$DESC")
            printf "  [%2d] %-5s [취약] %-45s (%s)\n" "$IDX" "$ID" "$DESC" "$TYPE"
        fi
    done

    if [ ${#MENU_IDS[@]} -eq 0 ]; then
        echo "  취약 항목이 없습니다. 모든 항목이 양호 또는 N/A입니다."
        echo ""
        echo "  선택 방법:"
        echo "    report  - 전체 항목 현황 리포트 출력"
        echo "    q       - 종료"
        echo ""
        read -r -p "  선택: " MENU_CHOICE
        case "$MENU_CHOICE" in
            report|REPORT|r|R)
                REPORT_SAVE="${SCRIPT_DIR}/infra_remediate_report_${TIMESTAMP}.txt"
                print_full_report "$REPORT_SAVE"
                ;;
        esac
        log "INFO" "취약 항목 없음 - 조치 불필요"
        emit_snapshot_final
        exit 0
    fi

    echo ""
    echo "  [MANUAL 항목은 자동 조치 없음 - 가이드만 출력됩니다]"
    echo ""
    echo "  선택 방법:"
    echo "    all     - 모든 취약 항목 처리 (AUTO 자동, SEMI 승인, MANUAL 가이드)"
    echo "    auto    - AUTO 항목만 자동 적용"
    echo "    1,3,5   - 번호 선택 (쉼표 구분)"
    echo "    report  - 전체 항목 현황 리포트 출력 (U-01~U-67 상태 일람)"
    echo "    q       - 종료"
    echo ""
    read -r -p "  선택: " MENU_CHOICE

    case "$MENU_CHOICE" in
        q|Q)
            echo "  종료합니다."
            emit_snapshot_final
            exit 0
            ;;
        report|REPORT|r|R)
            # 전체 항목 현황 리포트
            REPORT_SAVE="${SCRIPT_DIR}/infra_remediate_report_${TIMESTAMP}.txt"
            print_full_report "$REPORT_SAVE"
            echo ""
            read -r -p "  조치를 계속 진행하시겠습니까? [y/N]: " CONTINUE_ANS
            if [[ ! "$CONTINUE_ANS" =~ ^[Yy]$ ]]; then
                echo "  종료합니다."
                emit_snapshot_final
                exit 0
            fi
            # 메뉴 재표시를 위해 다시 선택 유도
            echo ""
            echo "  [취약 항목 목록]"
            echo ""
            IDX2=0
            MENU_IDS=()
            MENU_TYPES=()
            MENU_DESCS=()
            for i in "${!ITEM_IDS[@]}"; do
                ID="${ITEM_IDS[$i]}"
                TYPE="${ITEM_TYPES[$i]}"
                DESC="${ITEM_DESCS[$i]}"
                STATUS=$(get_status "$ID")
                if [ "$STATUS" = "[취약]" ]; then
                    IDX2=$((IDX2+1))
                    MENU_IDS+=("$ID")
                    MENU_TYPES+=("$TYPE")
                    MENU_DESCS+=("$DESC")
                    printf "  [%2d] %-5s [취약] %-45s (%s)\n" "$IDX2" "$ID" "$DESC" "$TYPE"
                fi
            done
            echo ""
            echo "  all / auto / 번호선택 / q"
            echo ""
            read -r -p "  선택: " MENU_CHOICE
            ;;
        all|ALL)
            for ID in "${MENU_IDS[@]}"; do
                SELECTED_IDS+=("$ID")
            done
            ;;
        auto|AUTO)
            AUTO_MODE=true
            for i in "${!MENU_IDS[@]}"; do
                if [ "${MENU_TYPES[$i]}" = "AUTO" ]; then
                    SELECTED_IDS+=("${MENU_IDS[$i]}")
                fi
            done
            ;;
        *)
            IFS=',' read -ra NUMS <<< "$MENU_CHOICE"
            for NUM in "${NUMS[@]}"; do
                NUM=$(echo "$NUM" | tr -d ' ')
                if [[ "$NUM" =~ ^[0-9]+$ ]] && [ "$NUM" -ge 1 ] && [ "$NUM" -le ${#MENU_IDS[@]} ]; then
                    SELECTED_IDS+=("${MENU_IDS[$((NUM-1))]}")
                else
                    echo "  [경고] 잘못된 번호 무시: $NUM"
                fi
            done
            ;;
    esac

    if [ ${#SELECTED_IDS[@]} -eq 0 ]; then
        echo "  선택된 항목이 없습니다. 종료합니다."
        emit_snapshot_final
        exit 0
    fi

    echo ""
    echo "  선택된 항목: ${SELECTED_IDS[*]}"
    echo ""
    read -r -p "  위 항목을 조치하시겠습니까? [y/N]: " CONFIRM
    if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
        echo "  취소합니다."
        emit_snapshot_final
        exit 0
    fi

elif $AUTO_MODE; then
    # AUTO 모드: AUTO 분류 항목만 선택
    for i in "${!ITEM_IDS[@]}"; do
        if [ "${ITEM_TYPES[$i]}" = "AUTO" ]; then
            SELECTED_IDS+=("${ITEM_IDS[$i]}")
        fi
    done
    echo "  AUTO 모드: ${#SELECTED_IDS[@]}개 AUTO 항목 처리 예정"

elif $DRY_RUN; then
    # DRY-RUN: 모든 항목 시뮬레이션
    for ID in "${ITEM_IDS[@]}"; do
        SELECTED_IDS+=("$ID")
    done
    echo "  DRY-RUN 모드: 모든 항목 미리보기"
fi

# 선택된 ID를 빠르게 조회하기 위한 연관 배열
declare -A SELECTED_MAP
for ID in "${SELECTED_IDS[@]}"; do
    SELECTED_MAP["$ID"]=1
done

# ==============================================================================
# 조치 실행 함수 정의
# ==============================================================================

# --- AUTO 항목 실행 함수 ---

do_u01() {
    local STATUS
    STATUS=$(get_status "U-01")
    print_item "U-01" "AUTO" "root 계정 원격 접속 제한" "${STATUS:-N/A}"
    [ "$STATUS" != "[취약]" ] && log "U-01" "SKIP ($STATUS)" && CNT_SKIP=$((CNT_SKIP+1)) && return

    log "U-01" "조치 시작: PermitRootLogin no 설정"
    backup_file /etc/ssh/sshd_config

    if $DRY_RUN; then
        log_action "[DRY-RUN] sed: PermitRootLogin no 설정"
        log_action "[DRY-RUN] systemctl reload ssh"
    else
        if grep -qE "^[[:space:]]*#*PermitRootLogin" /etc/ssh/sshd_config; then
            sed -i 's/^[[:space:]]*#*PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
        else
            echo "PermitRootLogin no" >> /etc/ssh/sshd_config
        fi
        systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null
        log "U-01" "완료: PermitRootLogin no 적용, SSH 재로드"
        CNT_APPLIED=$((CNT_APPLIED+1))
    fi
}

do_u02() {
    local STATUS
    STATUS=$(get_status "U-02")
    print_item "U-02" "AUTO" "비밀번호 관리정책 설정" "${STATUS:-N/A}"
    [ "$STATUS" != "[취약]" ] && log "U-02" "SKIP ($STATUS)" && CNT_SKIP=$((CNT_SKIP+1)) && return

    log "U-02" "조치 시작: pwquality + login.defs 설정"
    backup_file /etc/security/pwquality.conf
    backup_file /etc/login.defs
    backup_file /etc/pam.d/common-password

    if $DRY_RUN; then
        log_action "[DRY-RUN] apt install -y libpam-pwquality"
        log_action "[DRY-RUN] pwquality.conf: minlen=10, dcredit=-1, ucredit=-1, lcredit=-1, ocredit=-1"
        log_action "[DRY-RUN] login.defs: PASS_MAX_DAYS=90, PASS_MIN_DAYS=1"
        log_action "[DRY-RUN] common-password: pam_pwquality.so 추가"
    else
        apt-get install -y libpam-pwquality >> "$REMEDIATE_LOG" 2>&1

        PWQCONF="/etc/security/pwquality.conf"
        for PARAM in "minlen = 10" "dcredit = -1" "ucredit = -1" "lcredit = -1" "ocredit = -1"; do
            KEY=$(echo "$PARAM" | awk -F'=' '{print $1}' | tr -d ' ')
            if grep -qE "^[[:space:]]*${KEY}[[:space:]]*=" "$PWQCONF" 2>/dev/null; then
                sed -i "s/^[[:space:]]*${KEY}[[:space:]]*=.*/${PARAM}/" "$PWQCONF"
            else
                echo "$PARAM" >> "$PWQCONF"
            fi
        done

        # PASS_MAX_DAYS / PASS_MIN_DAYS
        if grep -q "^PASS_MAX_DAYS" /etc/login.defs; then
            sed -i 's/^PASS_MAX_DAYS.*/PASS_MAX_DAYS   90/' /etc/login.defs
        else
            echo "PASS_MAX_DAYS   90" >> /etc/login.defs
        fi
        if grep -q "^PASS_MIN_DAYS" /etc/login.defs; then
            sed -i 's/^PASS_MIN_DAYS.*/PASS_MIN_DAYS   1/' /etc/login.defs
        else
            echo "PASS_MIN_DAYS   1" >> /etc/login.defs
        fi

        # common-password에 pam_pwquality.so 추가 (PAM success 카운트 안전 처리)
        # 방식: pam_unix.so 라인의 [success=1]을 [success=2]로 올리고
        #       그 앞에 pwquality를 requisite로 삽입한다.
        # 이렇게 하면 pam_unix 성공 시 2줄(pwquality+deny) 건너뛰어 permit에 도달한다.
        if ! grep -q "pam_pwquality.so" /etc/pam.d/common-password; then
            # [success=1 default=ignore] → [success=2 default=ignore] 로 카운트 증가
            sed -i 's/\[success=1 default=ignore\]\(.*pam_unix\.so\)/[success=2 default=ignore]\1/' /etc/pam.d/common-password
            # pam_unix.so 라인 앞에 pwquality 삽입
            sed -i '/pam_unix\.so/i password	requisite				pam_pwquality.so retry=3' /etc/pam.d/common-password
        fi

        log "U-02" "완료: pwquality.conf minlen=10/복잡성, login.defs PASS_MAX_DAYS=90/PASS_MIN_DAYS=1"
        CNT_APPLIED=$((CNT_APPLIED+1))
    fi
}

do_u03() {
    local STATUS
    STATUS=$(get_status "U-03")
    print_item "U-03" "AUTO" "계정 잠금 임계값 설정" "${STATUS:-N/A}"
    [ "$STATUS" != "[취약]" ] && log "U-03" "SKIP ($STATUS)" && CNT_SKIP=$((CNT_SKIP+1)) && return

    log "U-03" "조치 시작: pam_faillock 설정"
    backup_file /etc/security/faillock.conf
    backup_file /etc/pam.d/common-auth
    backup_file /etc/pam.d/common-account

    if $DRY_RUN; then
        log_action "[DRY-RUN] faillock.conf: deny=5, unlock_time=600, fail_interval=900"
        log_action "[DRY-RUN] common-auth: pam_faillock.so preauth/authfail 추가"
        log_action "[DRY-RUN] common-account: pam_faillock.so 추가"
    else
        FCONF="/etc/security/faillock.conf"
        # faillock.conf 생성/설정
        [ -f "$FCONF" ] || touch "$FCONF"
        for PARAM in "deny = 5" "unlock_time = 600" "fail_interval = 900"; do
            KEY=$(echo "$PARAM" | awk -F'=' '{print $1}' | tr -d ' ')
            if grep -qE "^[[:space:]]*${KEY}[[:space:]]*=" "$FCONF" 2>/dev/null; then
                sed -i "s/^[[:space:]]*${KEY}[[:space:]]*=.*/${PARAM}/" "$FCONF"
            else
                echo "$PARAM" >> "$FCONF"
            fi
        done

        COMMON_AUTH="/etc/pam.d/common-auth"
        if ! grep -q "pam_faillock.so" "$COMMON_AUTH"; then
            # PAM faillock 안전 삽입 원칙:
            # 1. preauth는 pam_unix 앞에 required로 삽입 → success 카운트에 영향 없음
            # 2. authfail은 pam_unix 뒤에 삽입하되 [default=die] 사용
            # 3. pam_unix의 [success=1 default=ignore]를 [success=2 default=ignore]로 변경
            #    → pam_unix 성공 시 authfail 라인을 건너뛰고 pam_deny로 가지 않음
            #
            # 결과 구조 (정상 인증 흐름):
            # required  pam_faillock.so preauth  → 잠금 여부 확인, 계속 진행
            # [success=2 default=ignore] pam_unix.so → 성공 시 authfail+deny 2줄 skip → permit 도달
            # [default=die] pam_faillock.so authfail  → pam_unix 실패 시만 실행
            # requisite pam_deny.so
            # required  pam_permit.so
            # optional  pam_cap.so

            # [success=1 default=ignore] → [success=2 default=ignore] 카운트 증가
            sed -i 's/\[success=1 default=ignore\]\(.*pam_unix\.so\)/[success=2 default=ignore]\1/' "$COMMON_AUTH"
            # pam_unix.so 라인 앞에 faillock preauth 삽입
            sed -i '/pam_unix\.so/i auth	required				pam_faillock.so preauth silent' "$COMMON_AUTH"
            # pam_unix.so 라인 뒤에 faillock authfail 삽입
            sed -i '/pam_unix\.so/a auth	[default=die]			pam_faillock.so authfail' "$COMMON_AUTH"
        fi

        COMMON_ACCOUNT="/etc/pam.d/common-account"
        if [ -f "$COMMON_ACCOUNT" ] && ! grep -q "pam_faillock.so" "$COMMON_ACCOUNT"; then
            echo "account required pam_faillock.so" >> "$COMMON_ACCOUNT"
        fi

        log "U-03" "완료: faillock.conf deny=5/unlock_time=600, common-auth 설정 완료"
        CNT_APPLIED=$((CNT_APPLIED+1))
    fi
}

do_u12() {
    local STATUS
    STATUS=$(get_status "U-12")
    print_item "U-12" "AUTO" "세션 종료 시간 설정 (TMOUT)" "${STATUS:-N/A}"
    [ "$STATUS" != "[취약]" ] && log "U-12" "SKIP ($STATUS)" && CNT_SKIP=$((CNT_SKIP+1)) && return

    log "U-12" "조치 시작: TMOUT=600 설정"
    backup_file /etc/profile

    if $DRY_RUN; then
        log_action "[DRY-RUN] /etc/profile에 export TMOUT=600 추가 (중복 방지, dot라인 보호)"
    else
        # 무결성 사전 검증
        if ! verify_profile_integrity /etc/profile; then
            log "U-12" "[ERROR] /etc/profile 손상 감지 - 조치 중단"
            return 1
        fi
        # 기존 TMOUT 설정 제거 시 dot 라인 보호: grep으로 안전하게 확인 후 삭제
        # sed 삭제 전 백업 재확인
        backup_file /etc/profile
        sed -i '/^[[:space:]]*export[[:space:]]\+TMOUT[[:space:]]*=/d' /etc/profile
        sed -i '/^[[:space:]]*TMOUT=[0-9]/d' /etc/profile
        # 삭제 후 무결성 재검증
        if ! verify_profile_integrity /etc/profile; then
            log "U-12" "[CRITICAL] sed 이후 /etc/profile 손상 - 백업에서 복구 필요"
            return 1
        fi
        # append-only 방식으로 추가
        if ! safe_append_profile "export TMOUT=600"; then
            log "U-12" "[ERROR] safe_append_profile 실패"
            return 1
        fi
        log "U-12" "완료: TMOUT=600 설정 (/etc/profile)"
        CNT_APPLIED=$((CNT_APPLIED+1))
    fi
}

do_u14() {
    local STATUS
    STATUS=$(get_status "U-14")
    print_item "U-14" "AUTO" "root PATH에 현재 디렉터리 포함 금지" "${STATUS:-N/A}"
    [ "$STATUS" != "[취약]" ] && log "U-14" "SKIP ($STATUS)" && CNT_SKIP=$((CNT_SKIP+1)) && return

    log "U-14" "조치 시작: PATH에서 '.' 제거"
    for F in /etc/profile /etc/environment /root/.bashrc /root/.bash_profile /root/.profile; do
        [ -f "$F" ] || continue
        backup_file "$F"
    done

    if $DRY_RUN; then
        log_action "[DRY-RUN] /etc/profile, /root/.bashrc 등에서 PATH 내 '.' 제거"
    else
        for F in /etc/profile /etc/environment /root/.bashrc /root/.bash_profile /root/.profile; do
            [ -f "$F" ] || continue
            # /etc/profile은 수정 전 무결성 검증 필수
            if [ "$F" = "/etc/profile" ]; then
                if ! verify_profile_integrity "$F"; then
                    log "U-14" "[ERROR] /etc/profile 손상 감지 - 해당 파일 sed 처리 건너뜀"
                    continue
                fi
            fi
            # PATH=...:. 또는 PATH=.:... 또는 PATH=...:.:... 형태 제거
            # 주의: 's/^\.//' 계열 패턴은 '. /etc/bash.bashrc' 줄과 혼동 금지
            # 현재 패턴은 '^\.' 뒤에 ':' 가 오는 경우만 매치하므로 dot+space는 안전
            sed -i \
                -e 's/:\.\(:\|$\)/\1/g' \
                -e 's/^\.\://g' \
                -e 's/^PATH=\./PATH=/g' \
                -e '/^PATH=/s/::/:/g' \
                "$F"
            # /etc/profile 수정 후 무결성 재검증
            if [ "$F" = "/etc/profile" ]; then
                if ! verify_profile_integrity "$F"; then
                    log "U-14" "[CRITICAL] sed 이후 /etc/profile 손상 감지 - 즉시 점검 필요"
                fi
            fi
        done
        # 현재 세션 PATH에도 즉시 반영 (재로그인 전까지 유지)
        export PATH=$(echo "$PATH" | tr ':' '\n' | grep -v '^\.$' | grep -v '^$' | tr '\n' ':' | sed 's/:$//')
        log "U-14" "완료: 파일 수정 + 현재 세션 PATH 즉시 반영"
        log "U-14" "  적용된 PATH: $PATH"
        CNT_APPLIED=$((CNT_APPLIED+1))
    fi
}

do_u25() {
    local STATUS
    STATUS=$(get_status "U-25")
    print_item "U-25" "AUTO" "world writable 파일 권한 제거" "${STATUS:-N/A}"
    [ "$STATUS" != "[취약]" ] && log "U-25" "SKIP ($STATUS)" && CNT_SKIP=$((CNT_SKIP+1)) && return

    log "U-25" "조치 시작: world writable 파일 other-write 권한 제거"

    # ----------------------------------------------------------------------
    # scanengine versions 메타파일 — 운영자 합의된 명시적 644 정렬
    # /opt/scanengine/Update1/versions.* / /opt/scanengine/Update2/versions.*
    # ----------------------------------------------------------------------
    local SE_TARGETS=( /opt/scanengine/Update1/versions.* /opt/scanengine/Update2/versions.* )
    local SE_COUNT=0
    if $DRY_RUN; then
        for F in "${SE_TARGETS[@]}"; do
            [ -f "$F" ] || continue
            log_action "  [DRY-RUN] chmod 644 $F"
        done
    else
        for F in "${SE_TARGETS[@]}"; do
            [ -f "$F" ] || continue
            local BEFORE_PERM
            BEFORE_PERM=$(stat -c "%a" "$F" 2>/dev/null)
            if chmod 644 "$F" 2>/dev/null; then
                log "U-25" "  chmod 644 (scanengine): $F (${BEFORE_PERM} → 644)"
                SE_COUNT=$((SE_COUNT+1))
            fi
        done
        [ "$SE_COUNT" -gt 0 ] && log "U-25" "  scanengine versions.* ${SE_COUNT}개 644 정렬 완료"
    fi

    # find 공통 예외 절 (가상 fs + 임시 fs + MNX 운영 디렉토리)
    local FIND_EXC=(
        -not -path "/proc/*"        -not -path "/sys/*"
        -not -path "/dev/*"         -not -path "/run/*"
        -not -path "/tmp"           -not -path "/tmp/*"
        -not -path "/var/tmp"       -not -path "/var/tmp/*"
        -not -path "/data"          -not -path "/data/*"
        -not -path "/logs"          -not -path "/logs/*"
        -not -path "/application"   -not -path "/application/*"
        -not -path "/opt/mnx"       -not -path "/opt/mnx/*"
        -not -path "/mnt/*"         -not -path "/media/*"
        -not -path "/var/lib/docker/*" -not -path "/var/lib/containerd/*"
    )

    if $DRY_RUN; then
        WW_LIST=$(find / -xdev -perm -0002 -not -type l "${FIND_EXC[@]}" 2>/dev/null | head -20)
        log_action "[DRY-RUN] chmod o-w 대상 파일 목록:"
        echo "$WW_LIST" | while read -r F; do
            [ -n "$F" ] && log_action "  chmod o-w $F"
        done
    else
        FIXED=0
        while IFS= read -r F; do
            [ -z "$F" ] && continue
            # 시스템 필수 파일 + MNX 운영 디렉토리 이중 보호 (P0-1 패치 반영)
            case "$F" in
                /etc/bash.bashrc|/etc/profile|/etc/environment|\
                /etc/profile.d/*|/root/.bashrc|/root/.profile|\
                /root/.bash_profile|/root/.bash_logout|\
                /usr/bin/*|/usr/sbin/*|/bin/*|/sbin/*|\
                /usr/lib/*|/usr/lib64/*|/lib/*|/lib64/*|\
                /data|/data/*|/logs|/logs/*|\
                /application|/application/*|\
                /opt/mnx|/opt/mnx/*|\
                /mnt/*|/media/*|\
                /var/lib/docker/*|/var/lib/containerd/*)
                    log "U-25" "  SKIP (시스템/운영 디렉토리 보호): $F"
                    continue
                    ;;
            esac
            chmod o-w "$F" 2>/dev/null && FIXED=$((FIXED+1))
            log "U-25" "  chmod o-w: $F"
        done < <(find / -xdev -perm -0002 -not -type l "${FIND_EXC[@]}" 2>/dev/null)
        log "U-25" "완료: ${FIXED}개 파일 other-write 권한 제거"
        CNT_APPLIED=$((CNT_APPLIED+1))
    fi
}

do_u64() {
    local STATUS
    STATUS=$(get_status "U-64")
    print_item "U-64" "AUTO" "최신 보안 패치 적용" "${STATUS:-N/A}"
    [ "$STATUS" != "[취약]" ] && log "U-64" "SKIP ($STATUS)" && CNT_SKIP=$((CNT_SKIP+1)) && return

    log "U-64" "조치 시작: 보안 패키지 업데이트"

    # MNX 운영 환경 보호 대상 패키지 (설정파일 충돌 방지를 위해 hold)
    # suricata: /etc/suricata/ 커스텀 설정 보호
    # mnxcapture 관련 패키지: /opt/mnx/ 설정 보호
    local HOLD_PKGS="suricata"

    if $DRY_RUN; then
        UPGRADABLE=$(apt list --upgradable 2>/dev/null | grep -v "Listing" | wc -l || echo 0)
        log_action "[DRY-RUN] apt-mark hold $HOLD_PKGS  # 설정파일 보호"
        log_action "[DRY-RUN] DEBIAN_FRONTEND=noninteractive apt-get update && apt-get upgrade -y --force-confold"
        log_action "[DRY-RUN] apt-mark unhold $HOLD_PKGS"
        log_action "[DRY-RUN] 업그레이드 대상 패키지 수: $UPGRADABLE"
        log_action "[DRY-RUN] hold 대상: $HOLD_PKGS (설정파일 충돌 방지)"
    else
        echo ""
        echo "  [안내] 보안 패치 적용을 진행합니다."
        echo "         MNX 운영 설정 보호를 위해 다음 패키지는 hold 후 업그레이드에서 제외합니다:"
        echo "           $HOLD_PKGS"
        echo ""

        # 운영 설정 보호 패키지 hold
        for pkg in $HOLD_PKGS; do
            if dpkg -l "$pkg" &>/dev/null; then
                apt-mark hold "$pkg" 2>&1 | tee -a "$REMEDIATE_LOG"
                log "U-64" "hold: $pkg (설정파일 보호)"
            fi
        done

        # 비대화형 + 기존 설정 유지 옵션으로 업그레이드
        DEBIAN_FRONTEND=noninteractive apt-get update -qq 2>&1 | tee -a "$REMEDIATE_LOG"
        DEBIAN_FRONTEND=noninteractive apt-get upgrade -y \
            -o Dpkg::Options::="--force-confold" \
            -o Dpkg::Options::="--force-confdef" \
            2>&1 | tee -a "$REMEDIATE_LOG"

        # hold 해제
        for pkg in $HOLD_PKGS; do
            if dpkg -l "$pkg" &>/dev/null; then
                apt-mark unhold "$pkg" 2>&1 | tee -a "$REMEDIATE_LOG"
                log "U-64" "unhold: $pkg"
            fi
        done

        log "U-64" "완료: 보안 패치 적용 (보호 패키지: $HOLD_PKGS)"
        CNT_APPLIED=$((CNT_APPLIED+1))

        if [ -f /run/reboot-required ]; then
            log "U-64" "[주의] 재부팅 필요: $(cat /run/reboot-required.pkgs 2>/dev/null | tr '\n' ' ')"
            echo ""
            echo "  [주의] 커널 업데이트 등으로 재부팅이 필요합니다!"
            echo "         확인 후 적절한 시간에 재부팅하세요: sudo reboot"
        fi
    fi
}

do_u67() {
    local STATUS
    STATUS=$(get_status "U-67")
    print_item "U-67" "AUTO" "로그 디렉터리 소유자 및 권한 설정" "${STATUS:-N/A}"
    [ "$STATUS" != "[취약]" ] && log "U-67" "SKIP ($STATUS)" && CNT_SKIP=$((CNT_SKIP+1)) && return

    log "U-67" "조치 시작: /var/log 권한 설정"

    if $DRY_RUN; then
        log_action "[DRY-RUN] chmod 755 /var/log"
        log_action "[DRY-RUN] chmod 664 /var/log/wtmp (logrotate 호환)"
        log_action "[DRY-RUN] chmod 600 /var/log/btmp"
        log_action "[DRY-RUN] chmod 644 /var/log/lastlog"
    else
        chmod 755 /var/log
        [ -f /var/log/wtmp ]    && chmod 664 /var/log/wtmp
        [ -f /var/log/btmp ]    && chmod 600 /var/log/btmp
        [ -f /var/log/lastlog ] && chmod 644 /var/log/lastlog
        log "U-67" "완료: /var/log -> 755, wtmp 664, btmp 600, lastlog 644"
        CNT_APPLIED=$((CNT_APPLIED+1))
    fi
}

# --- SEMI 항목 실행 함수 ---

do_u06() {
    local STATUS
    STATUS=$(get_status "U-06")
    print_item "U-06" "SEMI" "사용자 계정 su 기능 제한" "${STATUS:-N/A}"
    [ "$STATUS" != "[취약]" ] && log "U-06" "SKIP ($STATUS)" && CNT_SKIP=$((CNT_SKIP+1)) && return

    if ! ask_confirm "U-06: /etc/pam.d/su에 wheel 그룹 제한 추가"; then
        log "U-06" "SKIP (사용자 거부)"
        CNT_SKIPPED=$((CNT_SKIPPED+1))
        return
    fi

    log "U-06" "조치 시작: su wheel 제한"
    backup_file /etc/pam.d/su

    if $DRY_RUN; then
        log_action "[DRY-RUN] groupadd wheel (없는 경우)"
        log_action "[DRY-RUN] /etc/pam.d/su: auth required pam_wheel.so use_uid 추가"
        log_action "[DRY-RUN] sudo 그룹 멤버를 wheel 그룹에 추가"
    else
        getent group wheel > /dev/null 2>&1 || groupadd wheel

        SUDO_MEMBERS=$(getent group sudo 2>/dev/null | cut -d: -f4 | tr ',' ' ')
        for MEMBER in $SUDO_MEMBERS; do
            [ -n "$MEMBER" ] || continue
            usermod -aG wheel "$MEMBER" 2>/dev/null
            log "U-06" "  wheel 그룹 추가: $MEMBER"
        done

        if ! grep -qE "^[[:space:]]*auth.*pam_wheel.so" /etc/pam.d/su; then
            sed -i '1i auth required pam_wheel.so use_uid' /etc/pam.d/su
        fi

        log "U-06" "완료: wheel 그룹 su 제한 설정"
        CNT_APPLIED=$((CNT_APPLIED+1))
    fi
}

do_u07() {
    local STATUS
    STATUS=$(get_status "U-07")
    print_item "U-07" "SEMI" "불필요한 계정 shell 비활성화" "${STATUS:-N/A}"
    [ "$STATUS" != "[취약]" ] && log "U-07" "SKIP ($STATUS)" && CNT_SKIP=$((CNT_SKIP+1)) && return

    local UNNECESSARY_ACCOUNTS="games news uucp lp irc gnats pcap"
    local FOUND_ACCOUNTS=()
    for ACCT in $UNNECESSARY_ACCOUNTS; do
        getent passwd "$ACCT" > /dev/null 2>&1 && FOUND_ACCOUNTS+=("$ACCT")
    done

    if [ ${#FOUND_ACCOUNTS[@]} -eq 0 ]; then
        log "U-07" "불필요 계정 미발견 (상태 재확인 필요)"
        CNT_SKIP=$((CNT_SKIP+1))
        return
    fi

    echo "  발견된 불필요 계정: ${FOUND_ACCOUNTS[*]}"
    echo "  [안내] 삭제 금지 - Ubuntu 기본 계정 삭제 시 패키지 의존성 문제 발생"
    echo "  [조치] 로그인 Shell을 /usr/sbin/nologin으로 변경합니다"

    if ! ask_confirm "U-07: 위 계정들의 shell을 /usr/sbin/nologin으로 변경"; then
        log "U-07" "SKIP (사용자 거부)"
        CNT_SKIPPED=$((CNT_SKIPPED+1))
        return
    fi

    log "U-07" "조치 시작: 불필요 계정 shell 비활성화"

    if $DRY_RUN; then
        for ACCT in "${FOUND_ACCOUNTS[@]}"; do
            log_action "[DRY-RUN] usermod -s /usr/sbin/nologin $ACCT"
        done
    else
        for ACCT in "${FOUND_ACCOUNTS[@]}"; do
            CURRENT_SHELL=$(getent passwd "$ACCT" | cut -d: -f7)
            if [ "$CURRENT_SHELL" != "/usr/sbin/nologin" ] && [ "$CURRENT_SHELL" != "/bin/false" ]; then
                usermod -s /usr/sbin/nologin "$ACCT" 2>/dev/null
                log "U-07" "  $ACCT: shell -> /usr/sbin/nologin (이전: $CURRENT_SHELL)"
            fi
        done
        log "U-07" "완료: ${#FOUND_ACCOUNTS[@]}개 계정 shell 비활성화"
        CNT_APPLIED=$((CNT_APPLIED+1))
    fi
}

do_u24() {
    # =========================================================================
    # U-24 완벽판: 환경변수 파일 other-write 제거 (MANUAL)
    #
    # 🔥 절대 금지: chmod 644 / chmod 600
    #    → /etc/profile.d/*.sh 실행권한 손상 → bash 초기화 실패
    #
    # ✅ 올바른 조치: chmod o-w [파일]
    #    → other-write bit만 제거, 실행권한 유지
    #
    # 🔥 /etc/profile.d 디렉토리는 반드시 755 유지
    #    → 디렉토리 권한 손상 시 모든 profile.d 스크립트 실행 불가
    # =========================================================================
    local STATUS
    STATUS=$(get_status "U-24")
    print_item "U-24" "MANUAL" "사용자 환경변수 파일 other-write 제거" "${STATUS:-N/A}"
    [ "$STATUS" != "[취약]" ] && log "U-24" "SKIP ($STATUS)" && CNT_SKIP=$((CNT_SKIP+1)) && return

    log "U-24" "[MANUAL] 시스템 파일 권한 손상 위험으로 수동 처리 필요"

    echo ""
    echo "  ╔══════════════════════════════════════════════════════════════╗"
    echo "  ║  U-24 수동 조치 안내                                        ║"
    echo "  ╠══════════════════════════════════════════════════════════════╣"
    echo "  ║  🔥 절대 금지: chmod 644 / chmod 600                        ║"
    echo "  ║     → bash 초기화 실패, SSH 접속 장애 발생                  ║"
    echo "  ║  ✅ 올바른 방법: chmod o-w [파일]  (other-write만 제거)     ║"
    echo "  ╚══════════════════════════════════════════════════════════════╝"
    echo ""

    # --- [1] /etc/profile.d 디렉토리 상태 확인 ---
    local PROFILED_DIR="/etc/profile.d"
    echo "  [1] /etc/profile.d 디렉토리 상태 확인"
    if [ -d "$PROFILED_DIR" ]; then
        local DIR_PERM
        DIR_PERM=$(stat -c "%a" "$PROFILED_DIR")
        local DIR_OWNER
        DIR_OWNER=$(stat -c "%U" "$PROFILED_DIR")
        local DIR_OTHER_W=$(( 8#$DIR_PERM % 8 ))
        echo "      현재 권한: $DIR_PERM (owner=$DIR_OWNER)"
        if [ "$DIR_PERM" != "755" ]; then
            echo "  ⚠️  /etc/profile.d 권한 이상 감지! 정상값: 755"
            echo "      복구 명령: chmod 755 /etc/profile.d"
        else
            echo "      상태: 정상 (755)"
        fi
        if [ $(( DIR_OTHER_W & 2 )) -ne 0 ]; then
            echo "      조치 필요: chmod o-w /etc/profile.d"
        fi
    fi
    echo ""

    # --- [2] 취약 파일 목록 출력 (chmod o-w 명령어 형태로) ---
    local BAD_FILES=()

    for F in /etc/profile /etc/bash.bashrc /etc/environment; do
        [ -f "$F" ] || continue
        local PERM OWNER OTHER_W
        PERM=$(stat -c "%a" "$F")
        OWNER=$(stat -c "%U" "$F")
        OTHER_W=$(( 8#$PERM % 8 ))
        if [ $(( OTHER_W & 2 )) -ne 0 ] || [ "$OWNER" != "root" ]; then
            BAD_FILES+=("$F")
        fi
    done

    for F in /etc/profile.d/*.sh; do
        [ -f "$F" ] || continue
        local PERM OWNER OTHER_W
        PERM=$(stat -c "%a" "$F")
        OWNER=$(stat -c "%U" "$F")
        OTHER_W=$(( 8#$PERM % 8 ))
        if [ $(( OTHER_W & 2 )) -ne 0 ] || [ "$OWNER" != "root" ]; then
            BAD_FILES+=("$F")
        fi
    done

    for F in /root/.bashrc /root/.profile /root/.bash_profile /root/.bash_login; do
        [ -f "$F" ] || continue
        local PERM OWNER OTHER_W
        PERM=$(stat -c "%a" "$F")
        OWNER=$(stat -c "%U" "$F")
        OTHER_W=$(( 8#$PERM % 8 ))
        if [ $(( OTHER_W & 2 )) -ne 0 ] || [ "$OWNER" != "root" ]; then
            BAD_FILES+=("$F")
        fi
    done

    echo "  [2] 조치 대상 파일 및 권장 명령어"
    if [ ${#BAD_FILES[@]} -eq 0 ]; then
        echo "      취약 파일 없음 (점검 결과와 불일치 시 보고서 재확인)"
    else
        for F in "${BAD_FILES[@]}"; do
            local PERM OWNER
            PERM=$(stat -c "%a" "$F")
            OWNER=$(stat -c "%U" "$F")
            echo "      chmod o-w $F   # 현재: $PERM, owner: $OWNER"
        done
    fi
    echo ""
    echo "  [3] 조치 후 검증 명령어"
    echo "      source /etc/profile && echo OK"
    echo "      ls -la /etc/profile.d/"
    echo ""
    echo "  [4] 긴급 복구 명령어 (권한 손상 발생 시)"
    echo "      chmod 755 /etc/profile.d"
    echo "      chmod 644 /etc/profile.d/*.sh"
    echo "      chmod 644 /etc/profile /etc/bash.bashrc /etc/environment"
    echo "      chmod 600 /root/.bashrc /root/.profile"
    echo ""

    CNT_SKIP=$((CNT_SKIP+1))
}

do_u33() {
    local STATUS
    STATUS=$(get_status "U-33")
    print_item "U-33" "SEMI" "숨겨진 파일 (.swp) 점검 및 제거" "${STATUS:-N/A}"
    [ "$STATUS" != "[취약]" ] && log "U-33" "SKIP ($STATUS)" && CNT_SKIP=$((CNT_SKIP+1)) && return

    echo "  [안내] 아래 숨김 파일 중 편집기 스왑 파일(.swp/.swo)만 삭제 대상입니다"

    SWP_FILES=$(find /etc /usr /var -name "*.swp" -o -name "*.swo" 2>/dev/null | head -20)

    if [ -z "$SWP_FILES" ]; then
        log "U-33" "삭제 대상 스왑 파일 없음 (상태 재확인 필요)"
        CNT_SKIP=$((CNT_SKIP+1))
        return
    fi

    echo "  삭제 대상 스왑 파일:"
    echo "$SWP_FILES"

    if ! ask_confirm "U-33: 위 스왑 파일 삭제"; then
        log "U-33" "SKIP (사용자 거부)"
        CNT_SKIPPED=$((CNT_SKIPPED+1))
        return
    fi

    log "U-33" "조치 시작: 스왑 파일 삭제"

    if $DRY_RUN; then
        echo "$SWP_FILES" | while read -r F; do
            [ -n "$F" ] && log_action "[DRY-RUN] rm -f $F"
        done
    else
        echo "$SWP_FILES" | while read -r F; do
            [ -n "$F" ] || continue
            rm -f "$F" && log "U-33" "  삭제: $F"
        done
        log "U-33" "완료"
        CNT_APPLIED=$((CNT_APPLIED+1))
    fi
}

do_u62() {
    local STATUS
    STATUS=$(get_status "U-62")
    print_item "U-62" "SEMI" "로그인 경고 메시지 설정" "${STATUS:-N/A}"
    [ "$STATUS" != "[취약]" ] && log "U-62" "SKIP ($STATUS)" && CNT_SKIP=$((CNT_SKIP+1)) && return

    echo "  [안내] /etc/issue, /etc/issue.net, SSH Banner를 기본 경고 메시지로 설정합니다"
    echo "  [안내] 실제 운영 환경에서는 조직 정책에 맞는 메시지로 변경하세요"

    if ! ask_confirm "U-62: 기본 경고 배너 설정"; then
        log "U-62" "SKIP (사용자 거부)"
        CNT_SKIPPED=$((CNT_SKIPPED+1))
        return
    fi

    log "U-62" "조치 시작: 경고 배너 설정"
    backup_file /etc/issue
    backup_file /etc/issue.net
    backup_file /etc/ssh/sshd_config

    if $DRY_RUN; then
        log_action "[DRY-RUN] /etc/issue 에 경고 메시지 기록"
        log_action "[DRY-RUN] /etc/issue.net 복사"
        log_action "[DRY-RUN] sshd_config: Banner /etc/issue.net 설정"
    else
        cat > /etc/issue.net << 'BANNER_EOF'
************************************************************************
*                      SANDS LAB Inc. NDR SYSTEM                       *
************************************************************************
* This system is for authorized use only.                              *
* Unauthorized access is strictly prohibited.                          *
* All activities on this system are monitored and recorded.            *
* By accessing this system, you consent to such monitoring.            *
************************************************************************
BANNER_EOF
        cp /etc/issue.net /etc/issue

        if grep -q "^[[:space:]]*Banner" /etc/ssh/sshd_config; then
            sed -i 's|^[[:space:]]*Banner.*|Banner /etc/issue.net|' /etc/ssh/sshd_config
        else
            echo "Banner /etc/issue.net" >> /etc/ssh/sshd_config
        fi
        systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null
        log "U-62" "완료: /etc/issue, /etc/issue.net, SSH Banner 설정"
        CNT_APPLIED=$((CNT_APPLIED+1))
    fi
}

# ==============================================================================
# 선택된 항목 실행
# ==============================================================================
echo ""
echo "=== 조치 실행 시작 ==="
echo ""

# 조치 실행 모드: MANUAL 항목도 선택된 것만 출력
FILTER_MANUAL_SELECTED=true

# AUTO/SEMI 항목 실행
for i in "${!ITEM_IDS[@]}"; do
    ID="${ITEM_IDS[$i]}"
    TYPE="${ITEM_TYPES[$i]}"

    # 선택된 항목인지 확인 (DRY-RUN이면 전체 실행)
    if ! $DRY_RUN; then
        [ -z "${SELECTED_MAP[$ID]+_}" ] && continue
    fi

    # MANUAL 항목은 run_manual_items()에서 별도 처리
    [ "$TYPE" = "MANUAL" ] && continue

    case "$ID" in
        "U-01") do_u01 ;;
        "U-02") do_u02 ;;
        "U-03") do_u03 ;;
        "U-06") do_u06 ;;
        "U-07") do_u07 ;;
        "U-12") do_u12 ;;
        "U-14") do_u14 ;;
        "U-24") do_u24 ;;
        "U-25") do_u25 ;;
        "U-33") do_u33 ;;
        "U-62") do_u62 ;;
        "U-64") do_u64 ;;
        "U-67") do_u67 ;;
    esac
done

# MANUAL 항목: 취약 항목만 가이드 출력
echo ""
echo "=== MANUAL 항목 (수동 조치 가이드) ==="

MANUAL_SELECTED=false
for i in "${!ITEM_IDS[@]}"; do
    ID="${ITEM_IDS[$i]}"
    TYPE="${ITEM_TYPES[$i]}"
    [ "$TYPE" != "MANUAL" ] && continue

    # 선택된 항목 또는 DRY-RUN이면 출력
    if $DRY_RUN || [ -n "${SELECTED_MAP[$ID]+_}" ]; then
        STATUS=$(get_status "$ID")
        if [ "$STATUS" = "[취약]" ]; then
            MANUAL_SELECTED=true
        fi
    fi
done

if $MANUAL_SELECTED || $DRY_RUN; then
    # 선택된 MANUAL 항목의 가이드 출력 (취약인 경우만)
    for i in "${!ITEM_IDS[@]}"; do
        ID="${ITEM_IDS[$i]}"
        TYPE="${ITEM_TYPES[$i]}"
        [ "$TYPE" != "MANUAL" ] && continue
        if $DRY_RUN || [ -n "${SELECTED_MAP[$ID]+_}" ]; then
            STATUS=$(get_status "$ID")
            if [ "$STATUS" = "[취약]" ]; then
                # run_manual_items 내 print_manual 사용하여 개별 출력
                :
            fi
        fi
    done
    run_manual_items
else
    echo "  선택된 MANUAL 항목 없음 (또는 모두 양호/N/A)"
fi

# ==============================================================================
# 결과 요약 (조치 단계)
# ==============================================================================
echo ""
echo "================================================================"
echo "  조치 완료 요약"
echo "================================================================"
printf "  적용 완료 (AUTO/SEMI) : %d 개\n" "$CNT_APPLIED"
printf "  SKIP (양호/N/A)       : %d 개\n" "$CNT_SKIP"
printf "  SKIP (미승인)         : %d 개\n" "$CNT_SKIPPED"
printf "  MANUAL 취약 항목      : %d 개 (수동 조치 필요)\n" "$CNT_MANUAL_VULN"
echo "  ----------------------------------------------------------------"
echo "  조치 로그 : $REMEDIATE_LOG"
[ -d "$BACKUP_DIR" ] && echo "  설정 백업 : $BACKUP_DIR/"
echo "================================================================"

# ==============================================================================
# 조치 후 audit 자동 재실행 + Before/After 비교 (최종 리포트)
# (parse_summary / extract_vuln_ids 정의는 스크립트 상단으로 이동 — 조기 종료 경로에서도 사용)
# ==============================================================================

if ! $DRY_RUN && ! $FINAL_EMITTED; then
    BEFORE_FILE="$REPORT_FILE"
    BEFORE_STATS=$(parse_summary "$BEFORE_FILE")
    BEFORE_VULNS=$(extract_vuln_ids "$BEFORE_FILE")
    AFTER_FILE=""

    if [ "$CNT_APPLIED" -gt 0 ]; then
        # 실제 조치가 적용된 경우: audit 재실행하여 After 리포트 생성
        AUDIT_SH="${SCRIPT_DIR}/infra_audit.sh"
        if [ ! -x "$AUDIT_SH" ] && [ ! -f "$AUDIT_SH" ]; then
            echo ""
            echo "  [경고] infra_audit.sh 미발견: $AUDIT_SH"
            echo "         재점검을 건너뛰고 Before 리포트만으로 final 리포트 생성"
            log "POST" "infra_audit.sh 미발견 — Before 리포트로 fallback"
            AFTER_FILE="$BEFORE_FILE"
        else
            echo ""
            echo "================================================================"
            echo "  조치 후 재점검 시작 (infra_audit.sh 자동 재실행)"
            echo "================================================================"
            log "POST" "조치 후 audit 재실행 시작"
            ( cd "$SCRIPT_DIR" && bash "$AUDIT_SH" ) | tail -20

            AFTER_FILE=$(ls -t "${SCRIPT_DIR}"/infra_audit_report_*.txt 2>/dev/null | head -1)
            if [ -z "$AFTER_FILE" ] || [ "$AFTER_FILE" = "$BEFORE_FILE" ]; then
                echo "  [경고] 재점검 리포트를 찾을 수 없습니다 — Before 리포트로 대체"
                log "POST" "재점검 리포트 누락 — Before 리포트로 fallback"
                AFTER_FILE="$BEFORE_FILE"
            fi
        fi
    else
        # 조치 미적용 (MANUAL-only / 사용자 종료 / 양호만): 재점검 생략, Before=After
        echo ""
        echo "================================================================"
        echo "  자동 조치 적용 없음 — 재점검 생략 (현재 상태로 final 리포트 생성)"
        echo "================================================================"
        log "POST" "조치 미적용 - audit 재실행 생략 (Before=After)"
        AFTER_FILE="$BEFORE_FILE"
    fi

    AFTER_STATS=$(parse_summary "$AFTER_FILE")
    AFTER_VULNS=$(extract_vuln_ids "$AFTER_FILE")

    read -r BG BV BN <<< "$BEFORE_STATS"
    read -r AG AV AN <<< "$AFTER_STATS"

    # 해결된 / 잔존 / 신규 항목
    RESOLVED=$(comm -23 <(echo "$BEFORE_VULNS") <(echo "$AFTER_VULNS") | tr '\n' ' ')
    REMAIN=$(comm -12 <(echo "$BEFORE_VULNS") <(echo "$AFTER_VULNS") | tr '\n' ' ')
    NEW=$(comm -13 <(echo "$BEFORE_VULNS") <(echo "$AFTER_VULNS") | tr '\n' ' ')

    FINAL_REPORT="${SCRIPT_DIR}/infra_remediate_final_${TIMESTAMP}.txt"
    {
        echo "================================================================================"
        echo "         조치 적용 최종 리포트 (Before / After 비교)"
        echo "         생성: $(date "+%Y-%m-%d %H:%M:%S")"
        echo "================================================================================"
        echo ""
        echo " [입력 리포트]"
        echo "   Before : $BEFORE_FILE"
        echo "   After  : $AFTER_FILE"
        [ "$BEFORE_FILE" = "$AFTER_FILE" ] && echo "   (※ 자동 조치 미적용 또는 재점검 생략 — Before=After 단일 스냅샷)"
        echo ""
        echo " [조치 단계 요약]"
        printf "   적용 완료 (AUTO/SEMI) : %d 개\n" "$CNT_APPLIED"
        printf "   SKIP (양호/N/A)       : %d 개\n" "$CNT_SKIP"
        printf "   SKIP (미승인)         : %d 개\n" "$CNT_SKIPPED"
        printf "   MANUAL 취약 항목      : %d 개\n" "$CNT_MANUAL_VULN"
        echo ""
        echo " [재점검 결과 비교]"
        printf "   %-15s %8s %8s %8s\n" "구분" "Before" "After" "변화"
        printf "   ---------------------------------------------\n"
        printf "   %-15s %8d %8d %+8d\n" "양호" "$BG" "$AG" "$((AG-BG))"
        printf "   %-15s %8d %8d %+8d\n" "취약" "$BV" "$AV" "$((AV-BV))"
        printf "   %-15s %8d %8d %+8d\n" "N/A" "$BN" "$AN" "$((AN-BN))"
        echo ""
        echo " [항목별 상태 변화]"
        echo "   해결된 항목 (취약 → 양호/N/A) : ${RESOLVED:-(없음)}"
        echo "   잔존 취약 항목               : ${REMAIN:-(없음)}"
        echo "   신규 발견 취약 항목 (regression) : ${NEW:-(없음)}"
        echo ""
        echo " [백업 / 로그]"
        [ -d "$BACKUP_DIR" ] && echo "   설정 백업 : $BACKUP_DIR/"
        echo "   조치 로그 : $REMEDIATE_LOG"
        echo ""
        echo "================================================================================"
        if [ "$CNT_APPLIED" -eq 0 ] && [ "$AV" -gt 0 ]; then
            echo "   [최종 판정] 자동 조치 미적용 — 현재 취약 ${AV}건 (MANUAL 가이드 참조)"
        elif [ "$AV" -eq 0 ]; then
            echo "   [최종 판정] 모든 취약 항목 해소 — 양호"
        elif [ -n "$NEW" ]; then
            echo "   [최종 판정] 조치 후 신규 취약 발견 — 재점검 필요"
        elif [ -n "$REMAIN" ]; then
            echo "   [최종 판정] 잔존 취약 ${AV}건 — MANUAL/SEMI 수동 조치 필요"
        fi
        echo "================================================================================"
    } | tee "$FINAL_REPORT"

    FINAL_EMITTED=true
    log "POST" "최종 리포트: $FINAL_REPORT (해결: ${RESOLVED:-0}, 잔존: ${REMAIN:-0}, 신규: ${NEW:-0})"
elif $DRY_RUN; then
    echo ""
    echo "  [DRY-RUN] 변경 없음 - 재점검 생략"
fi

log "END" "조치 완료 - 적용: ${CNT_APPLIED}개, SKIP: ${CNT_SKIP}개, 미승인SKIP: ${CNT_SKIPPED}개, MANUAL취약: ${CNT_MANUAL_VULN}개"
