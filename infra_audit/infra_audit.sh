#!/bin/bash
# ==============================================================================
# 주요정보통신기반시설 기술적 취약점 분석·평가 점검 스크립트
# 기준: 2026년판 주요정보통신기반시설 기술적 취약점 분석·평가 방법 상세가이드
# 대상: Ubuntu 22.04 LTS (Debian 계열 Linux)
# 항목: U-01 ~ U-67 전체 67개 항목
# 버전: 2.0.0 (2026-03-26)
# ==============================================================================

# set -e / set -o pipefail 제거:
#   grep이 매칭 없을 때 exit 1을 반환하며 스크립트가 중단되는 문제 방지
#   점검 스크립트에서 "결과 없음"은 정상적인 상태값이므로 에러로 처리하지 않음

# ------------------------------------------------------------------------------
# 권한 확인
# ------------------------------------------------------------------------------
if [ "$EUID" -ne 0 ]; then
    echo "[오류] root 권한으로 실행해야 합니다."
    echo "  사용법: sudo bash $0"
    exit 1
fi

# ------------------------------------------------------------------------------
# 변수 정의
# ------------------------------------------------------------------------------
REPORT_DATE=$(date +%Y%m%d_%H%M%S)
RESULT_FILE="infra_audit_report_${REPORT_DATE}.txt"
HOSTNAME_VAL=$(hostname)
OS_VAL=$(grep PRETTY_NAME /etc/os-release 2>/dev/null | cut -d'"' -f2 || echo "Unknown")
KERNEL_VAL=$(uname -r)
IP_VAL=$(ip -4 addr show scope global | grep -oP '(?<=inet )\d+\.\d+\.\d+\.\d+' | head -1 || echo "N/A")
START_TIME=$(date "+%Y-%m-%d %H:%M:%S")

TOTAL=0
GOOD=0
VULN=0
NA=0

# 항목별 결과 ID 추적 (요약 출력용)
GOOD_IDS=()
VULN_IDS=()
NA_IDS=()
CURRENT_ID=""

# ------------------------------------------------------------------------------
# 예외 디렉토리/파일 정책 (MNX 운영 환경)
#   - SUID/SGID(U-23), world-writable(U-25), 환경변수(U-24), 홈 디렉토리(U-31) 등
#     find 기반 점검에서 운영 디렉토리는 정상 동작에 필요한 권한이므로 제외
#   - suricata 등 데몬이 다른 UID로 로그를 적재하기 위해 0777/0775 디렉토리가 정상
# ------------------------------------------------------------------------------
EXCLUDE_PATHS=(
    # 가상 파일시스템
    "/proc" "/sys" "/dev" "/run"
    # 임시 파일시스템 (정상적으로 world-writable + sticky)
    "/tmp" "/var/tmp"
    # MNX 운영 디렉토리 (suricata, mnxcapture, application 데이터)
    "/data" "/logs" "/application" "/opt/mnx"
    # 마운트된 외부 디스크 / 컨테이너
    "/mnt" "/media" "/var/lib/docker" "/var/lib/containerd"
)

# find -not -path 옵션 문자열 생성 (디렉토리 자체 + 하위)
build_find_excludes() {
    local OUT=()
    for P in "${EXCLUDE_PATHS[@]}"; do
        OUT+=("-not" "-path" "$P" "-not" "-path" "$P/*")
    done
    printf '%s\n' "${OUT[@]}"
}

# case 패턴 화이트리스트 (do_u25 등에서 활용; 참조용)
EXCLUDE_CASE_PATTERN='/proc|/proc/*|/sys|/sys/*|/dev|/dev/*|/run|/run/*|/tmp|/tmp/*|/var/tmp|/var/tmp/*|/data|/data/*|/logs|/logs/*|/application|/application/*|/opt/mnx|/opt/mnx/*|/mnt|/mnt/*|/media|/media/*'

# ------------------------------------------------------------------------------
# 로그 함수
# ------------------------------------------------------------------------------
log_raw() {
    printf "%s\n" "$*" >> "$RESULT_FILE"
}

log_header() {
    log_raw ""
    log_raw "============================================================"
    log_raw "  $1"
    log_raw "============================================================"
}

log_section() {
    log_raw ""
    log_raw "------------------------------------------------------------"
    log_raw "  $1"
    log_raw "------------------------------------------------------------"
}

log_item() {
    local ID=$1
    local DESC=$2
    local IMPORTANCE=$3
    TOTAL=$((TOTAL + 1))
    CURRENT_ID="$ID"
    log_raw ""
    log_raw "┌─ [$ID] $DESC (중요도: $IMPORTANCE)"
    printf "  점검 중: %-8s %-50s " "$ID" "$DESC"
}

log_result() {
    local STATUS=$1   # 양호 / 취약 / N/A
    local EVIDENCE=$2
    case "$STATUS" in
        "양호")
            GOOD=$((GOOD + 1))
            GOOD_IDS+=("$CURRENT_ID")
            log_raw "│  진단결과: [양호]"
            ;;
        "취약")
            VULN=$((VULN + 1))
            VULN_IDS+=("$CURRENT_ID")
            log_raw "│  진단결과: [취약]"
            ;;
        "N/A")
            NA=$((NA + 1))
            NA_IDS+=("$CURRENT_ID")
            log_raw "│  진단결과: [N/A] 해당 없음"
            ;;
    esac
    # 증거를 여러 줄로 출력
    while IFS= read -r line; do
        log_raw "│  상세근거: $line"
    done <<< "$EVIDENCE"
    log_raw "└──────────────────────────────────────────────────────────"
    echo "[$STATUS]"
}

# ------------------------------------------------------------------------------
# 보조 함수
# ------------------------------------------------------------------------------

# 서비스 활성화 여부 확인 (active/inactive/not-installed)
check_service() {
    local SVC=$1
    if ! systemctl list-unit-files --quiet 2>/dev/null | grep -q "^${SVC}"; then
        echo "not-installed"
    elif systemctl is-active --quiet "$SVC" 2>/dev/null; then
        echo "active"
    else
        echo "inactive"
    fi
}

# 패키지 설치 여부 확인
pkg_installed() {
    dpkg -l "$1" 2>/dev/null | grep -q "^ii"
}

# 권한 숫자 비교 (stat 출력이 8진수 문자열)
perm_le() {
    local PERM=$1
    local LIMIT=$2
    # 8진수 → 10진수 비교
    [ "$((8#$PERM))" -le "$((8#$LIMIT))" ]
}

# ==============================================================================
# 보고서 헤더
# ==============================================================================
{
cat << HEADER_EOF
================================================================================
     주요정보통신기반시설 기술적 취약점 분석·평가 점검 보고서
     기준: 2026년판 KISA 상세가이드
================================================================================
 점검 일시  : $START_TIME
 대상 호스트: $HOSTNAME_VAL
 IP 주소   : $IP_VAL
 운영 체제  : $OS_VAL
 커널 버전  : $KERNEL_VAL
 점검 항목  : U-01 ~ U-67 (총 67개)
--------------------------------------------------------------------------------
 [예외 디렉토리/파일 정책 — find 기반 점검(U-15/U-23/U-24/U-25/U-31)에서 제외]
   ${EXCLUDE_PATHS[*]}
   사유: 가상 fs / 임시 fs / MNX 운영 데이터·로그 디렉토리(suricata, mnxcapture 등)
        / 컨테이너 레이어(/var/lib/containerd, /var/lib/docker) — 호스트 점검 범위 밖
================================================================================
HEADER_EOF
} > "$RESULT_FILE"

# ==============================================================================
# 1. 계정 관리 (U-01 ~ U-13)
# ==============================================================================
log_header "1. 계정 관리"

# ------------------------------------------------------------------------------
# U-01: root 계정 원격 접속 제한 (중요도: 상)
# 판단기준: 원격터미널 서비스 미사용 또는 root 직접 접속 차단 시 양호
# ------------------------------------------------------------------------------
log_item "U-01" "root 계정 원격 접속 제한" "상"
EV=""
STATUS="취약"

SSHD_CONF="/etc/ssh/sshd_config"
SSHD_DIR="/etc/ssh/sshd_config.d"
PERMIT_ROOT=""

if [ -f "$SSHD_CONF" ]; then
    PERMIT_ROOT=$(grep -iE "^[[:space:]]*PermitRootLogin" "$SSHD_CONF" | head -1)
fi
# sshd_config.d 디렉토리도 확인
if [ -z "$PERMIT_ROOT" ] && [ -d "$SSHD_DIR" ]; then
    PERMIT_ROOT=$(grep -rlE "^[[:space:]]*PermitRootLogin" "$SSHD_DIR" 2>/dev/null | xargs grep -hE "^[[:space:]]*PermitRootLogin" 2>/dev/null | head -1)
fi

if [ -z "$PERMIT_ROOT" ]; then
    EV="PermitRootLogin 설정 없음 (Ubuntu 22.04 기본값: prohibit-password)"
    # Ubuntu 22.04 기본값은 prohibit-password (패스워드 직접 로그인 금지)
    EV="${EV}
Ubuntu 22.04 기본값(prohibit-password)은 패스워드 root 로그인 차단이나
SSH 키 기반 root 로그인은 허용됩니다. 보안 강화를 위해 'no' 명시 권고."
    STATUS="취약"
elif echo "$PERMIT_ROOT" | grep -qi "^[[:space:]]*PermitRootLogin[[:space:]]\+no"; then
    EV="설정 확인: $PERMIT_ROOT"
    STATUS="양호"
elif echo "$PERMIT_ROOT" | grep -qi "prohibit-password\|forced-commands-only"; then
    EV="설정 확인: $PERMIT_ROOT (패스워드 직접 로그인 차단, 키 기반은 허용)"
    STATUS="취약"
else
    EV="설정 확인: $PERMIT_ROOT (root 원격 로그인 허용 상태)"
    STATUS="취약"
fi
log_result "$STATUS" "$EV"

# ------------------------------------------------------------------------------
# U-02: 비밀번호 관리정책 설정 (중요도: 상)
# 판단기준: 비밀번호 복잡성(minlen=8, dcredit/ucredit/lcredit/ocredit=-1)
#           최소사용기간 1일, 최대사용기간 90일 설정 시 양호
# Debian계열: /etc/security/pwquality.conf 또는 /etc/pam.d/common-password
# ------------------------------------------------------------------------------
log_item "U-02" "비밀번호 관리정책 설정" "상"
EV=""
STATUS="취약"
PWQUALITY_OK=false
LOGINDEF_OK=false
EV_PARTS=()

# pwquality.conf 확인
PWQUALITY_CONF="/etc/security/pwquality.conf"
if [ -f "$PWQUALITY_CONF" ]; then
    MINLEN=$(grep -E "^[[:space:]]*minlen" "$PWQUALITY_CONF" | awk -F'=' '{print $2}' | tr -d ' ' | head -1)
    DCREDIT=$(grep -E "^[[:space:]]*dcredit" "$PWQUALITY_CONF" | awk -F'=' '{print $2}' | tr -d ' ' | head -1)
    UCREDIT=$(grep -E "^[[:space:]]*ucredit" "$PWQUALITY_CONF" | awk -F'=' '{print $2}' | tr -d ' ' | head -1)
    LCREDIT=$(grep -E "^[[:space:]]*lcredit" "$PWQUALITY_CONF" | awk -F'=' '{print $2}' | tr -d ' ' | head -1)
    OCREDIT=$(grep -E "^[[:space:]]*ocredit" "$PWQUALITY_CONF" | awk -F'=' '{print $2}' | tr -d ' ' | head -1)
    EV_PARTS+=("[$PWQUALITY_CONF] minlen=${MINLEN:-미설정}, dcredit=${DCREDIT:-미설정}, ucredit=${UCREDIT:-미설정}, lcredit=${LCREDIT:-미설정}, ocredit=${OCREDIT:-미설정}")
    if [ "${MINLEN:-0}" -ge 8 ] 2>/dev/null && \
       [ "${DCREDIT:-0}" -le -1 ] 2>/dev/null && \
       [ "${UCREDIT:-0}" -le -1 ] 2>/dev/null && \
       [ "${LCREDIT:-0}" -le -1 ] 2>/dev/null && \
       [ "${OCREDIT:-0}" -le -1 ] 2>/dev/null; then
        PWQUALITY_OK=true
    fi
else
    EV_PARTS+=("$PWQUALITY_CONF 파일 없음")
fi

# /etc/pam.d/common-password 확인
PAM_COMMON="/etc/pam.d/common-password"
if [ -f "$PAM_COMMON" ]; then
    PAM_PWQUAL=$(grep "pam_pwquality.so" "$PAM_COMMON" | grep -v "^#" | head -1)
    EV_PARTS+=("[$PAM_COMMON] pam_pwquality: ${PAM_PWQUAL:-미설정}")
    if [ -n "$PAM_PWQUAL" ]; then
        PWQUALITY_OK=true
    fi
fi

# /etc/login.defs 확인
LOGIN_DEFS="/etc/login.defs"
PASS_MAX=""
PASS_MIN=""
PASS_MIN_DAYS=""
if [ -f "$LOGIN_DEFS" ]; then
    PASS_MAX=$(grep "^PASS_MAX_DAYS" "$LOGIN_DEFS" | awk '{print $2}')
    PASS_MIN_DAYS=$(grep "^PASS_MIN_DAYS" "$LOGIN_DEFS" | awk '{print $2}')
    EV_PARTS+=("[$LOGIN_DEFS] PASS_MAX_DAYS=${PASS_MAX:-미설정}, PASS_MIN_DAYS=${PASS_MIN_DAYS:-미설정}")
    if [ "${PASS_MAX:-9999}" -le 90 ] 2>/dev/null && [ "${PASS_MIN_DAYS:-0}" -ge 1 ] 2>/dev/null; then
        LOGINDEF_OK=true
    fi
fi

EV=$(printf "%s\n" "${EV_PARTS[@]}")
if $PWQUALITY_OK && $LOGINDEF_OK; then
    STATUS="양호"
elif $PWQUALITY_OK; then
    STATUS="취약"
    EV="${EV}
[판정] 복잡성은 설정되어 있으나 로그인.defs 기간 정책 미충족 (최소 1일/최대 90일 필요)"
else
    STATUS="취약"
    EV="${EV}
[판정] pam_pwquality 복잡성 설정 미충족 (minlen>=8, dcredit/ucredit/lcredit/ocredit=-1 필요)"
fi
log_result "$STATUS" "$EV"

# ------------------------------------------------------------------------------
# U-03: 계정 잠금 임계값 설정 (중요도: 상)
# 판단기준: 로그인 실패 10회 이하 잠금 설정 시 양호
# Ubuntu 22.04: pam_faillock (pam_tally2는 Ubuntu 20.04까지)
# ------------------------------------------------------------------------------
log_item "U-03" "계정 잠금 임계값 설정" "상"
EV=""
STATUS="취약"
EV_PARTS=()

# /etc/security/faillock.conf 확인
FAILLOCK_CONF="/etc/security/faillock.conf"
if [ -f "$FAILLOCK_CONF" ]; then
    DENY_VAL=$(grep -E "^[[:space:]]*deny[[:space:]]*=" "$FAILLOCK_CONF" | awk -F'=' '{print $2}' | tr -d ' ' | head -1)
    EV_PARTS+=("[$FAILLOCK_CONF] deny=${DENY_VAL:-미설정}")
    if [ -n "$DENY_VAL" ] && [ "$DENY_VAL" -le 10 ] && [ "$DENY_VAL" -gt 0 ] 2>/dev/null; then
        STATUS="양호"
    fi
fi

# /etc/pam.d/common-auth pam_faillock.so 확인
PAM_AUTH="/etc/pam.d/common-auth"
if [ -f "$PAM_AUTH" ]; then
    FAILLOCK_LINE=$(grep "pam_faillock.so" "$PAM_AUTH" | grep -v "^#" | head -2)
    EV_PARTS+=("[$PAM_AUTH] pam_faillock: ${FAILLOCK_LINE:-미설정}")
    if [ -n "$FAILLOCK_LINE" ]; then
        DENY_INLINE=$(echo "$FAILLOCK_LINE" | grep -oP 'deny=\K[0-9]+' | head -1)
        if [ -n "$DENY_INLINE" ]; then
            EV_PARTS+=("  - 인라인 deny값: $DENY_INLINE")
            if [ "$DENY_INLINE" -le 10 ] && [ "$DENY_INLINE" -gt 0 ] 2>/dev/null; then
                STATUS="양호"
            fi
        elif [ "$STATUS" != "양호" ]; then
            # faillock.conf에서 deny를 읽었을 경우
            :
        fi
    fi
fi

EV=$(printf "%s\n" "${EV_PARTS[@]}")
[ "$STATUS" = "취약" ] && EV="${EV}
[판정] pam_faillock.so 설정 미비 또는 deny 값이 10 초과/미설정 (Ubuntu 22.04는 pam_faillock 사용)"
log_result "$STATUS" "$EV"

# ------------------------------------------------------------------------------
# U-04: 비밀번호 파일 보호 (중요도: 상)
# 판단기준: /etc/passwd 두 번째 필드가 'x' (shadow 사용) 시 양호
# ------------------------------------------------------------------------------
log_item "U-04" "비밀번호 파일 보호" "상"
EV=""
STATUS="취약"

PASSWD_SHADOW=$(awk -F: '$2 != "x" && $2 != "!" && $2 != "" {print "평문 비밀번호 계정:", $1}' /etc/passwd)
SHADOW_EXIST=$([ -f /etc/shadow ] && echo "존재" || echo "미존재")
SAMPLE=$(head -3 /etc/passwd | awk -F: '{print $1":"$2":..."}')

EV="/etc/shadow 파일: $SHADOW_EXIST
/etc/passwd 샘플 (첫 3행): $SAMPLE"

if [ -f /etc/shadow ] && [ -z "$PASSWD_SHADOW" ]; then
    EV="${EV}
shadow 비밀번호 사용 중, 모든 계정 두 번째 필드='x'"
    STATUS="양호"
else
    EV="${EV}
평문 비밀번호 저장 계정 발견: ${PASSWD_SHADOW:-없음}"
fi
log_result "$STATUS" "$EV"

# ------------------------------------------------------------------------------
# U-05: root 이외의 UID가 '0' 금지 (중요도: 상)
# 판단기준: root 계정만 UID=0인 경우 양호
# ------------------------------------------------------------------------------
log_item "U-05" "root 이외의 UID=0 금지" "상"
UID0_ACCTS=$(awk -F: '$3 == 0 && $1 != "root" {print $1}' /etc/passwd)
UID0_LIST=$(awk -F: '$3 == 0 {print $1"(UID=0)"}' /etc/passwd)

EV="UID=0인 계정 목록: $UID0_LIST"
if [ -z "$UID0_ACCTS" ]; then
    EV="${EV}
root 외에 UID=0인 계정 없음"
    log_result "양호" "$EV"
else
    EV="${EV}
[경고] root 외 UID=0 계정 발견: $UID0_ACCTS"
    log_result "취약" "$EV"
fi

# ------------------------------------------------------------------------------
# U-06: 사용자 계정 su 기능 제한 (중요도: 상)
# 판단기준: su 명령어를 특정 그룹(wheel/sudo)에만 허용 시 양호
# ------------------------------------------------------------------------------
log_item "U-06" "사용자 계정 su 기능 제한" "상"
EV_PARTS=()
STATUS="취약"

# PAM su 설정 확인
PAM_SU="/etc/pam.d/su"
if [ -f "$PAM_SU" ]; then
    SU_PAM=$(grep -v "^#" "$PAM_SU" | grep -E "pam_wheel|pam_group" | head -3)
    EV_PARTS+=("[$PAM_SU] wheel/group 제한: ${SU_PAM:-미설정}")
    if [ -n "$SU_PAM" ]; then
        STATUS="양호"
    fi
fi

# wheel/sudo 그룹 존재 및 멤버 확인
WHEEL_MEMBERS=$(getent group wheel 2>/dev/null | cut -d: -f4)
SUDO_MEMBERS=$(getent group sudo 2>/dev/null | cut -d: -f4)
EV_PARTS+=("wheel 그룹 멤버: ${WHEEL_MEMBERS:-없음}")
EV_PARTS+=("sudo 그룹 멤버: ${SUDO_MEMBERS:-없음}")

# su 바이너리 권한 확인
SU_BIN=$(ls -l /usr/bin/su 2>/dev/null || ls -l /bin/su 2>/dev/null || echo "su 없음")
EV_PARTS+=("su 바이너리: $SU_BIN")

EV=$(printf "%s\n" "${EV_PARTS[@]}")
log_result "$STATUS" "$EV"

# ------------------------------------------------------------------------------
# U-07: 불필요한 계정 제거 (중요도: 하)
# 판단기준: 불필요한 계정이 미존재하거나, 존재하더라도 shell이 nologin/false이면 양호
#           (Ubuntu 기본 계정은 삭제 시 패키지 의존성 문제 → shell 비활성화로 대체 허용)
# ------------------------------------------------------------------------------
log_item "U-07" "불필요한 계정 제거" "하"
UNNECESSARY=("games" "news" "uucp" "lp" "irc" "gnats" "pcap")
FOUND_ACCTS=()
DISABLED_ACCTS=()
for ACCT in "${UNNECESSARY[@]}"; do
    if getent passwd "$ACCT" > /dev/null 2>&1; then
        ACCT_SHELL=$(getent passwd "$ACCT" | cut -d: -f7)
        if echo "$ACCT_SHELL" | grep -qE "nologin|/bin/false"; then
            DISABLED_ACCTS+=("$ACCT (shell=$ACCT_SHELL)")
        else
            FOUND_ACCTS+=("$ACCT (shell=$ACCT_SHELL)")
        fi
    fi
done

EV="점검 대상 계정: ${UNNECESSARY[*]}
로그인 가능 불필요 계정: ${FOUND_ACCTS[*]:-없음}
비활성화(nologin) 처리 계정: ${DISABLED_ACCTS[*]:-없음}"
if [ ${#FOUND_ACCTS[@]} -eq 0 ]; then
    log_result "양호" "$EV"
else
    log_result "취약" "$EV"
fi

# ------------------------------------------------------------------------------
# U-08: 관리자 그룹에 최소한의 계정 포함 (중요도: 중)
# 판단기준: sudo/wheel 그룹에 불필요한 계정 미존재 시 양호
# ------------------------------------------------------------------------------
log_item "U-08" "관리자 그룹 최소 계정" "중"
SUDO_GRP=$(getent group sudo 2>/dev/null | cut -d: -f4)
WHEEL_GRP=$(getent group wheel 2>/dev/null | cut -d: -f4)
ADDUSR_GRP=$(getent group adm 2>/dev/null | cut -d: -f4)

EV="sudo 그룹: ${SUDO_GRP:-없음}
wheel 그룹: ${WHEEL_GRP:-없음}
adm 그룹: ${ADDUSR_GRP:-없음}"
log_result "양호" "$EV
[안내] 위 그룹 구성원이 최소화되어 있는지 운영자가 직접 확인 필요"

# ------------------------------------------------------------------------------
# U-09: 계정이 존재하지 않는 GID 금지 (중요도: 하)
# 판단기준: /etc/passwd에 사용된 GID가 /etc/group에 모두 존재 시 양호
# ------------------------------------------------------------------------------
log_item "U-09" "계정이 존재하지 않는 GID 금지" "하"
ORPHAN_GID=()
while IFS=: read -r USER _ ACCT_UID GID _; do
    if ! getent group "$GID" > /dev/null 2>&1; then
        ORPHAN_GID+=("${USER}(GID=${GID})")
    fi
done < /etc/passwd

EV="고아 GID (그룹 미존재) 계정: ${ORPHAN_GID[*]:-없음}"
if [ ${#ORPHAN_GID[@]} -eq 0 ]; then
    log_result "양호" "$EV"
else
    log_result "취약" "$EV"
fi

# ------------------------------------------------------------------------------
# U-10: 동일한 UID 금지 (중요도: 중)
# 판단기준: 동일 UID를 가진 계정이 없는 경우 양호
# ------------------------------------------------------------------------------
log_item "U-10" "동일한 UID 금지" "중"
DUP_UID=$(awk -F: '{print $3}' /etc/passwd | sort | uniq -d)
DUP_DETAIL=""
if [ -n "$DUP_UID" ]; then
    for UID_VAL in $DUP_UID; do
        ACCTS=$(awk -F: -v u="$UID_VAL" '$3==u {printf "%s ", $1}' /etc/passwd)
        DUP_DETAIL="${DUP_DETAIL}  UID=${UID_VAL}: $ACCTS\n"
    done
fi

EV="중복 UID 발견: ${DUP_UID:-없음}
${DUP_DETAIL}"
if [ -z "$DUP_UID" ]; then
    log_result "양호" "$EV"
else
    log_result "취약" "$EV"
fi

# ------------------------------------------------------------------------------
# U-11: 사용자 Shell 점검 (중요도: 하)
# 판단기준: 로그인 불필요 계정에 /bin/false 또는 /sbin/nologin 부여 시 양호
# ------------------------------------------------------------------------------
log_item "U-11" "사용자 Shell 점검" "하"
SYS_ACCTS_BAD=()
# UID 1000 미만 시스템 계정 중 nologin/false가 아닌 로그인 가능 쉘 보유 계정
while IFS=: read -r USER _ ACCT_UID _ _ _ SHELL; do
    if [ "$ACCT_UID" -lt 1000 ] && [ "$USER" != "root" ] && [ "$USER" != "sync" ]; then
        case "$SHELL" in
            /bin/false|/sbin/nologin|/usr/sbin/nologin|"")
                ;;
            *)
                SYS_ACCTS_BAD+=("${USER}(shell=${SHELL})")
                ;;
        esac
    fi
done < /etc/passwd

EV="로그인 가능 쉘을 가진 시스템 계정(UID<1000): ${SYS_ACCTS_BAD[*]:-없음}"
if [ ${#SYS_ACCTS_BAD[@]} -eq 0 ]; then
    log_result "양호" "$EV"
else
    log_result "취약" "$EV"
fi

# ------------------------------------------------------------------------------
# U-12: 세션 종료 시간 설정 (중요도: 하)
# 판단기준: TMOUT=600 이하로 설정 시 양호
# ------------------------------------------------------------------------------
log_item "U-12" "세션 종료 시간 설정 (TMOUT)" "하"
TMOUT_VAL=""
TMOUT_SRC=""
for F in /etc/profile /etc/bash.bashrc /etc/environment /etc/profile.d/*.sh; do
    [ -f "$F" ] || continue
    VAL=$(grep -E "^[[:space:]]*(export[[:space:]]+)?TMOUT=" "$F" 2>/dev/null | tail -1 | grep -oP '\d+' | head -1)
    if [ -n "$VAL" ]; then
        TMOUT_VAL="$VAL"
        TMOUT_SRC="$F"
        break
    fi
done

EV="TMOUT 설정 파일: ${TMOUT_SRC:-미발견}
TMOUT 값: ${TMOUT_VAL:-미설정} (600초 이하 권고)"
if [ -n "$TMOUT_VAL" ] && [ "$TMOUT_VAL" -le 600 ] && [ "$TMOUT_VAL" -gt 0 ] 2>/dev/null; then
    log_result "양호" "$EV"
else
    log_result "취약" "$EV"
fi

# ------------------------------------------------------------------------------
# U-13: 안전한 비밀번호 암호화 알고리즘 (중요도: 중)
# 판단기준: SHA-512(yescrypt, sha512crypt) 이상 사용 시 양호
# ------------------------------------------------------------------------------
log_item "U-13" "안전한 비밀번호 암호화 알고리즘" "중"
ENCRYPT_METHOD=$(grep "^ENCRYPT_METHOD" /etc/login.defs 2>/dev/null | awk '{print $2}')
PAM_UNIX_HASH=$(grep "pam_unix.so" /etc/pam.d/common-password 2>/dev/null | grep -v "^#" | grep -oE "sha512|sha256|yescrypt|md5|blowfish" | head -1)

# /etc/shadow에서 실제 해시 알고리즘 확인
SHADOW_PREFIX=$(awk -F: '$2 ~ /^\$/ {print substr($2,1,5); exit}' /etc/shadow 2>/dev/null)
case "$SHADOW_PREFIX" in
    '$y$'*) ALGO_ACTUAL="yescrypt (Ubuntu 22.04 기본, SHA-512 이상 수준)" ;;
    '$6$'*) ALGO_ACTUAL="SHA-512" ;;
    '$5$'*) ALGO_ACTUAL="SHA-256" ;;
    '$2b$'*|'$2a$'*) ALGO_ACTUAL="bcrypt" ;;
    '$1$'*) ALGO_ACTUAL="MD5 (취약)" ;;
    *) ALGO_ACTUAL="알 수 없음 또는 잠금 계정" ;;
esac

EV="/etc/login.defs ENCRYPT_METHOD: ${ENCRYPT_METHOD:-미설정}
/etc/pam.d/common-password 해시: ${PAM_UNIX_HASH:-미설정}
/etc/shadow 실제 해시 접두사: ${SHADOW_PREFIX:-없음} → $ALGO_ACTUAL"

case "$ALGO_ACTUAL" in
    *MD5*|*취약*)
        log_result "취약" "$EV"
        ;;
    *)
        log_result "양호" "$EV"
        ;;
esac

# ==============================================================================
# 2. 파일 및 디렉토리 관리 (U-14 ~ U-33)
# ==============================================================================
log_header "2. 파일 및 디렉토리 관리"

# ------------------------------------------------------------------------------
# U-14: root 홈, 패스 디렉터리 권한 및 PATH 설정 (중요도: 상)
# 판단기준: PATH에 "." 이 맨 앞이나 중간에 없는 경우 양호
# ------------------------------------------------------------------------------
log_item "U-14" "root PATH 디렉터리 권한 설정" "상"
# su -l root는 PAM 대기/profile 로딩으로 블로킹될 수 있으므로 timeout 5초 적용
# 실패 시 /etc/environment + /etc/profile 직접 파싱으로 fallback
ROOT_PATH=$(timeout 5 su -l root -s /bin/bash -c 'echo $PATH' 2>/dev/null)
if [ -z "$ROOT_PATH" ]; then
    # fallback 1: /etc/environment 파싱
    ROOT_PATH=$(grep -oP '(?<=^PATH=")[^"]+' /etc/environment 2>/dev/null | head -1)
fi
if [ -z "$ROOT_PATH" ]; then
    # fallback 2: 현재 실행 환경 PATH 사용
    ROOT_PATH="${PATH}"
fi

DOT_IN_PATH=""
IFS=: read -ra PATH_PARTS <<< "$ROOT_PATH"
for PART in "${PATH_PARTS[@]}"; do
    if [ "$PART" = "." ] || [ -z "$PART" ]; then
        DOT_IN_PATH="발견 (요소: '${PART:-빈문자열}')"
        break
    fi
done

EV="root PATH: $ROOT_PATH
'.' 포함 여부: ${DOT_IN_PATH:-미발견}"
if [ -z "$DOT_IN_PATH" ]; then
    log_result "양호" "$EV"
else
    log_result "취약" "$EV"
fi

# ------------------------------------------------------------------------------
# U-15: 파일 및 디렉터리 소유자 설정 (중요도: 상)
# 판단기준: 소유자 없는 파일/디렉터리 미존재 시 양호
# ------------------------------------------------------------------------------
log_item "U-15" "파일 및 디렉터리 소유자 설정" "상"
echo ""
printf "    (소유자 없는 파일 검색 중, 시간이 소요될 수 있습니다...)"
# EXCLUDE_PATHS 적용 — 컨테이너 레이어(/var/lib/containerd, /var/lib/docker) 등
# overlayfs 스냅샷의 비등록 UID/GID는 호스트 점검 범위 밖이므로 제외
mapfile -t U15_EXCLUDES < <(build_find_excludes)
NOOWNER_FILES=$(find / -xdev \( -nouser -o -nogroup \) "${U15_EXCLUDES[@]}" 2>/dev/null | head -20)
echo ""

EV="소유자/그룹 없는 파일 (최대 20개): ${NOOWNER_FILES:-없음}
검사 제외 경로: ${EXCLUDE_PATHS[*]}"
if [ -z "$NOOWNER_FILES" ]; then
    log_result "양호" "$EV"
else
    log_result "취약" "$EV"
fi

# ------------------------------------------------------------------------------
# U-16: /etc/passwd 소유자 및 권한 (중요도: 상)
# 판단기준: 소유자=root, 권한=644 이하
# ------------------------------------------------------------------------------
log_item "U-16" "/etc/passwd 소유자 및 권한" "상"
F="/etc/passwd"
PERM=$(stat -c "%a" "$F")
OWNER=$(stat -c "%U" "$F")
EV="파일: $F | 소유자: $OWNER | 권한: $PERM (644 이하, root 소유 필요)"
if [ "$OWNER" = "root" ] && perm_le "$PERM" "644"; then
    log_result "양호" "$EV"
else
    log_result "취약" "$EV"
fi

# ------------------------------------------------------------------------------
# U-17: 시스템 시작 스크립트 권한 설정 (중요도: 상)
# 판단기준: /etc/init.d 등 스크립트 소유자=root, 타 사용자 쓰기 권한 없음
# ------------------------------------------------------------------------------
log_item "U-17" "시스템 시작 스크립트 권한 설정" "상"
INIT_DIR="/etc/init.d"
BAD_SCRIPTS=()
if [ -d "$INIT_DIR" ]; then
    while IFS= read -r SCRIPT; do
        OWNER_S=$(stat -c "%U" "$SCRIPT" 2>/dev/null)
        PERM_S=$(stat -c "%a" "$SCRIPT" 2>/dev/null)
        # 그룹/기타 쓰기 권한 확인 (owner 쓰기는 root이므로 정상 - group/other만 체크)
        if [ "$OWNER_S" != "root" ] || echo "$PERM_S" | grep -qE "[0-7][2367][0-7]$|[0-7][0-7][2367]$"; then
            BAD_SCRIPTS+=("$SCRIPT (owner=$OWNER_S, perm=$PERM_S)")
        fi
    done < <(find "$INIT_DIR" -maxdepth 1 -type f 2>/dev/null | head -20)
fi

EV="/etc/init.d 디렉터리 권한 이상 스크립트: ${BAD_SCRIPTS[*]:-없음 (정상)}"
if [ ${#BAD_SCRIPTS[@]} -eq 0 ]; then
    log_result "양호" "$EV"
else
    log_result "취약" "$EV"
fi

# ------------------------------------------------------------------------------
# U-18: /etc/shadow 소유자 및 권한 (중요도: 상)
# 판단기준: 소유자=root, 권한=400 이하 (Ubuntu: 640도 허용)
# ------------------------------------------------------------------------------
log_item "U-18" "/etc/shadow 소유자 및 권한" "상"
F="/etc/shadow"
if [ -f "$F" ]; then
    PERM=$(stat -c "%a" "$F")
    OWNER=$(stat -c "%U" "$F")
    GROUP=$(stat -c "%G" "$F")
    EV="파일: $F | 소유자: $OWNER | 그룹: $GROUP | 권한: $PERM (400 이하 권고, Ubuntu는 640/root:shadow 허용)"
    if [ "$OWNER" = "root" ] && perm_le "$PERM" "640"; then
        log_result "양호" "$EV"
    else
        log_result "취약" "$EV"
    fi
else
    log_result "N/A" "/etc/shadow 파일 없음"
fi

# ------------------------------------------------------------------------------
# U-19: /etc/hosts 소유자 및 권한 (중요도: 상)
# 판단기준: 소유자=root, 권한=644 이하
# ------------------------------------------------------------------------------
log_item "U-19" "/etc/hosts 소유자 및 권한" "상"
F="/etc/hosts"
PERM=$(stat -c "%a" "$F" 2>/dev/null || echo "N/A")
OWNER=$(stat -c "%U" "$F" 2>/dev/null || echo "N/A")
EV="파일: $F | 소유자: $OWNER | 권한: $PERM (644 이하, root 소유 필요)"
if [ "$OWNER" = "root" ] && perm_le "$PERM" "644" 2>/dev/null; then
    log_result "양호" "$EV"
else
    log_result "취약" "$EV"
fi

# ------------------------------------------------------------------------------
# U-20: /etc/(x)inetd.conf 소유자 및 권한 (중요도: 상)
# 판단기준: 소유자=root, 권한=600 이하 / 미설치 시 N/A
# ------------------------------------------------------------------------------
log_item "U-20" "/etc/(x)inetd.conf 소유자 및 권한" "상"
INETD_FILES=()
for F in /etc/inetd.conf /etc/xinetd.conf /etc/xinetd.d; do
    [ -e "$F" ] && INETD_FILES+=("$F")
done

if [ ${#INETD_FILES[@]} -eq 0 ]; then
    log_result "N/A" "inetd/xinetd 미설치 (관련 설정 파일 없음)"
else
    BAD_INETD=()
    for F in "${INETD_FILES[@]}"; do
        PERM=$(stat -c "%a" "$F")
        OWNER=$(stat -c "%U" "$F")
        if [ "$OWNER" != "root" ] || ! perm_le "$PERM" "600"; then
            BAD_INETD+=("$F (owner=$OWNER, perm=$PERM)")
        fi
    done
    EV="점검 파일/디렉터리: ${INETD_FILES[*]}
권한 이상: ${BAD_INETD[*]:-없음}"
    if [ ${#BAD_INETD[@]} -eq 0 ]; then
        log_result "양호" "$EV"
    else
        log_result "취약" "$EV"
    fi
fi

# ------------------------------------------------------------------------------
# U-21: /etc/(r)syslog.conf 소유자 및 권한 (중요도: 상)
# 판단기준: 소유자=root(또는 bin,sys), 권한=640 이하 (KISA 기준)
# ------------------------------------------------------------------------------
log_item "U-21" "/etc/(r)syslog.conf 소유자 및 권한" "상"
SYSLOG_FILES=()
for F in /etc/syslog.conf /etc/rsyslog.conf; do
    [ -f "$F" ] && SYSLOG_FILES+=("$F")
done
# rsyslog.d 디렉터리 내 파일만 개별 추가 (디렉토리 자체는 755가 정상이므로 제외)
if [ -d /etc/rsyslog.d ]; then
    while IFS= read -r -d '' F; do
        SYSLOG_FILES+=("$F")
    done < <(find /etc/rsyslog.d -maxdepth 1 -type f -print0 2>/dev/null)
fi

if [ ${#SYSLOG_FILES[@]} -eq 0 ]; then
    log_result "N/A" "syslog/rsyslog 설정 파일 없음"
else
    BAD_SYSLOG=()
    GOOD_SYSLOG=()
    for F in "${SYSLOG_FILES[@]}"; do
        PERM=$(stat -c "%a" "$F")
        OWNER=$(stat -c "%U" "$F")
        if [[ "$OWNER" =~ ^(root|bin|sys)$ ]] && perm_le "$PERM" "640"; then
            GOOD_SYSLOG+=("$F (owner=$OWNER, perm=$PERM)")
        else
            BAD_SYSLOG+=("$F (owner=$OWNER, perm=$PERM)")
        fi
    done
    EV="양호 파일: ${GOOD_SYSLOG[*]:-없음}
취약 파일: ${BAD_SYSLOG[*]:-없음}"
    if [ ${#BAD_SYSLOG[@]} -eq 0 ]; then
        log_result "양호" "$EV"
    else
        log_result "취약" "$EV"
    fi
fi

# ------------------------------------------------------------------------------
# U-22: /etc/services 소유자 및 권한 (중요도: 상)
# 판단기준: 소유자=root(또는 bin,sys), 권한=644 이하
# ------------------------------------------------------------------------------
log_item "U-22" "/etc/services 소유자 및 권한" "상"
F="/etc/services"
if [ -f "$F" ]; then
    PERM=$(stat -c "%a" "$F")
    OWNER=$(stat -c "%U" "$F")
    EV="파일: $F | 소유자: $OWNER | 권한: $PERM (644 이하, root/bin/sys 소유 필요)"
    if [[ "$OWNER" =~ ^(root|bin|sys)$ ]] && perm_le "$PERM" "644"; then
        log_result "양호" "$EV"
    else
        log_result "취약" "$EV"
    fi
else
    log_result "N/A" "/etc/services 파일 없음"
fi

# ------------------------------------------------------------------------------
# U-23: SUID, SGID, Sticky bit 설정 파일 점검 (중요도: 상)
# 판단기준: 주요 실행 파일에 불필요한 SUID/SGID 미설정 시 양호
# ------------------------------------------------------------------------------
log_item "U-23" "SUID/SGID 설정 파일 점검" "상"
echo ""
printf "    (SUID/SGID 파일 검색 중...)"
# 일반적으로 허용되는 SUID 파일 목록 (Ubuntu 22.04 기준)
ALLOWED_SUID=(
    # 계정/인증 관련 (필수 SUID)
    "/usr/bin/sudo" "/usr/bin/passwd" "/usr/bin/chfn" "/usr/bin/chsh"
    "/usr/bin/gpasswd" "/usr/bin/newgrp" "/usr/bin/su" "/bin/su"
    "/usr/bin/chage" "/usr/bin/expiry"
    # PAM 인증 보조
    "/sbin/unix_chkpwd" "/usr/sbin/unix_chkpwd"
    "/usr/sbin/pam_extrausers_chkpwd"           # Ubuntu PAM 추가 사용자 인증
    # 파일시스템/마운트
    "/usr/bin/mount" "/usr/bin/umount"
    "/usr/bin/fusermount3" "/usr/bin/fusermount"
    # 네트워크
    "/usr/bin/ping"
    # SSH
    "/usr/lib/openssh/ssh-keysign"
    "/usr/bin/ssh-agent"                         # Ubuntu 22.04 SGID ssh
    # D-Bus/Polkit (시스템 서비스)
    "/usr/lib/dbus-1.0/dbus-daemon-launch-helper"
    "/usr/bin/pkexec"
    "/usr/libexec/polkit-agent-helper-1"         # Ubuntu 22.04 polkit
    # 스케줄러
    "/usr/bin/at"
    "/usr/bin/crontab"                           # SGID crontab - 일반 사용자 cron 필수
    # PPP
    "/usr/sbin/pppd"
    # 터미널
    "/usr/lib/x86_64-linux-gnu/utempter/utempter"
    # 메일 (postfix 설치 시)
    "/usr/sbin/postdrop" "/usr/sbin/postqueue"
    # NFS 클라이언트 (nfs-common) — mount/umount.nfs SUID 정상
    "/usr/sbin/mount.nfs"
    # MySQL PAM 인증 플러그인 — auth_pam_tool은 PAM stack 호출용으로 SUID 필요
    "/usr/lib/mysql/plugin/auth_pam_tool_dir/auth_pam_tool"
)

mapfile -t FIND_EXC < <(build_find_excludes)
SUID_FOUND=$(find / -xdev -perm /6000 -type f "${FIND_EXC[@]}" 2>/dev/null)
SUID_SUSPICIOUS=()
while IFS= read -r FILE; do
    [ -z "$FILE" ] && continue
    ALLOWED=false
    for A in "${ALLOWED_SUID[@]}"; do
        [ "$FILE" = "$A" ] && ALLOWED=true && break
    done
    $ALLOWED || SUID_SUSPICIOUS+=("$FILE")
done <<< "$SUID_FOUND"
echo ""

SUID_COUNT=$(echo "$SUID_FOUND" | grep -c . || true)
EV="총 SUID/SGID 파일 수: $SUID_COUNT
의심스러운 SUID/SGID 파일 (허용 목록 외): ${SUID_SUSPICIOUS[*]:-없음}
검사 제외 경로: ${EXCLUDE_PATHS[*]}"
if [ ${#SUID_SUSPICIOUS[@]} -eq 0 ]; then
    log_result "양호" "$EV"
else
    log_result "취약" "$EV"
fi

# ------------------------------------------------------------------------------
# U-24: 사용자, 시스템 환경변수 파일 소유자 및 권한 (중요도: 상)
# 판단기준: 환경파일 소유자=root/해당계정, other-write 없음
# ※ 조치 시 반드시 chmod o-w 사용 (chmod 644/600 금지 — 실행권한 손상 위험)
# ※ /etc/profile.d 디렉토리는 반드시 755 유지
# ------------------------------------------------------------------------------
log_item "U-24" "사용자 환경변수 파일 소유자 및 권한" "상"

BAD_ENV=()
ENV_FILES_FOUND=()

# [1] /etc/profile.d 디렉토리 권한 체크 (755 이어야 함)
PROFILED_DIR="/etc/profile.d"
if [ -d "$PROFILED_DIR" ]; then
    DIR_PERM=$(stat -c "%a" "$PROFILED_DIR")
    DIR_OTHER_W=$(( 8#$DIR_PERM % 8 ))
    if [ $(( DIR_OTHER_W & 2 )) -ne 0 ]; then
        BAD_ENV+=("$PROFILED_DIR/ [디렉토리] (perm=$DIR_PERM, other-write 있음)")
    fi
fi

# [2] 시스템 환경 파일 체크 (other-write only)
for F in /etc/profile /etc/bash.bashrc /etc/environment; do
    [ -f "$F" ] || continue
    ENV_FILES_FOUND+=("$F")
    PERM=$(stat -c "%a" "$F")
    OWNER=$(stat -c "%U" "$F")
    OTHER_W=$(( 8#$PERM % 8 ))
    if [ "$OWNER" != "root" ]; then
        BAD_ENV+=("$F (owner=$OWNER, perm=$PERM) — 소유자 이상")
    elif [ $(( OTHER_W & 2 )) -ne 0 ]; then
        BAD_ENV+=("$F (perm=$PERM) — other-write 있음")
    fi
done

# [3] /etc/profile.d/*.sh 체크 (other-write only; 실행권한은 체크 제외)
for F in /etc/profile.d/*.sh; do
    [ -f "$F" ] || continue
    ENV_FILES_FOUND+=("$F")
    PERM=$(stat -c "%a" "$F")
    OWNER=$(stat -c "%U" "$F")
    OTHER_W=$(( 8#$PERM % 8 ))
    if [ "$OWNER" != "root" ]; then
        BAD_ENV+=("$F (owner=$OWNER, perm=$PERM) — 소유자 이상")
    elif [ $(( OTHER_W & 2 )) -ne 0 ]; then
        BAD_ENV+=("$F (perm=$PERM) — other-write 있음")
    fi
done

# [4] root 홈 환경 파일 체크 (other-write only)
for F in /root/.bashrc /root/.profile /root/.bash_profile /root/.bash_login; do
    [ -f "$F" ] || continue
    ENV_FILES_FOUND+=("$F")
    PERM=$(stat -c "%a" "$F")
    OWNER=$(stat -c "%U" "$F")
    OTHER_W=$(( 8#$PERM % 8 ))
    if [ "$OWNER" != "root" ]; then
        BAD_ENV+=("$F (owner=$OWNER, perm=$PERM) — 소유자 이상")
    elif [ $(( OTHER_W & 2 )) -ne 0 ]; then
        BAD_ENV+=("$F (perm=$PERM) — other-write 있음")
    fi
done

# [5] 일반 사용자 홈 환경 파일 체크
while IFS=: read -r U_NAME _ ACCT_UID _ _ U_HOME _; do
    [ "$ACCT_UID" -ge 1000 ] 2>/dev/null || continue
    [ -d "$U_HOME" ] || continue
    for F in "$U_HOME/.bashrc" "$U_HOME/.profile" "$U_HOME/.bash_profile" "$U_HOME/.bash_login"; do
        [ -f "$F" ] || continue
        ENV_FILES_FOUND+=("$F")
        PERM=$(stat -c "%a" "$F")
        OWNER=$(stat -c "%U" "$F")
        OTHER_W=$(( 8#$PERM % 8 ))
        if [ "$OWNER" != "$U_NAME" ] && [ "$OWNER" != "root" ]; then
            BAD_ENV+=("$F (owner=$OWNER, perm=$PERM) — 소유자 이상")
        elif [ $(( OTHER_W & 2 )) -ne 0 ]; then
            BAD_ENV+=("$F (perm=$PERM) — other-write 있음")
        fi
    done
done < /etc/passwd

EV="점검 파일 수: ${#ENV_FILES_FOUND[@]}
취약 항목: ${BAD_ENV[*]:-없음}
[조치 주의] chmod o-w 사용할 것 — chmod 644/600 사용 시 실행권한 손상으로 bash 초기화 실패"
if [ ${#BAD_ENV[@]} -eq 0 ]; then
    log_result "양호" "$EV"
else
    log_result "취약" "$EV"
fi

# ------------------------------------------------------------------------------
# U-25: world writable 파일 점검 (중요도: 상)
# 판단기준: world writable 파일 미존재 또는 설정 이유 인지 시 양호
# ------------------------------------------------------------------------------
log_item "U-25" "world writable 파일 점검" "상"
echo ""
printf "    (world writable 파일 검색 중...)"
mapfile -t FIND_EXC < <(build_find_excludes)
WW_FILES=$(find / -xdev -perm -0002 -not -type l "${FIND_EXC[@]}" 2>/dev/null | head -20)
echo ""

EV="world writable 파일 (운영/임시 디렉토리 제외, 최대 20개): ${WW_FILES:-없음}
검사 제외 경로: ${EXCLUDE_PATHS[*]}"
if [ -z "$WW_FILES" ]; then
    log_result "양호" "$EV"
else
    log_result "취약" "$EV"
fi

# ------------------------------------------------------------------------------
# U-26: /dev에 존재하지 않는 device 파일 점검 (중요도: 상)
# 판단기준: major/minor number 없는 device 파일 미존재 시 양호
# ------------------------------------------------------------------------------
log_item "U-26" "/dev 불법 device 파일 점검" "상"
FAKE_DEV=$(find /dev -not \( -type b -o -type c -o -type d -o -type l -o -type p -o -type s \) -type f 2>/dev/null | head -10)

EV="/dev 내 일반 파일(fake device): ${FAKE_DEV:-없음}"
if [ -z "$FAKE_DEV" ]; then
    log_result "양호" "$EV"
else
    log_result "취약" "$EV"
fi

# ------------------------------------------------------------------------------
# U-27: $HOME/.rhosts, hosts.equiv 사용 금지 (중요도: 상)
# 판단기준: r 계열 서비스 미사용 또는 rhosts 파일 적절 설정 시 양호
# ------------------------------------------------------------------------------
log_item "U-27" ".rhosts, hosts.equiv 사용 금지" "상"
EV_PARTS=()
STATUS="양호"

# hosts.equiv 확인
if [ -f /etc/hosts.equiv ]; then
    PERM=$(stat -c "%a" /etc/hosts.equiv)
    OWNER=$(stat -c "%U" /etc/hosts.equiv)
    PLUS_SIGN=$(grep -c "^+" /etc/hosts.equiv 2>/dev/null || true)
    EV_PARTS+=("/etc/hosts.equiv: owner=$OWNER, perm=$PERM, '+' 설정수=$PLUS_SIGN")
    if [ "$OWNER" != "root" ] || ! perm_le "$PERM" "600" || [ "$PLUS_SIGN" -gt 0 ]; then
        STATUS="취약"
    fi
else
    EV_PARTS+=("/etc/hosts.equiv: 파일 없음 (양호)")
fi

# root .rhosts 확인
if [ -f /root/.rhosts ]; then
    PERM=$(stat -c "%a" /root/.rhosts)
    PLUS_SIGN=$(grep -c "^+" /root/.rhosts 2>/dev/null || true)
    EV_PARTS+=("/root/.rhosts: perm=$PERM, '+' 설정수=$PLUS_SIGN")
    if ! perm_le "$PERM" "600" || [ "$PLUS_SIGN" -gt 0 ]; then
        STATUS="취약"
    fi
else
    EV_PARTS+=("/root/.rhosts: 파일 없음 (양호)")
fi

EV=$(printf "%s\n" "${EV_PARTS[@]}")
log_result "$STATUS" "$EV"

# ------------------------------------------------------------------------------
# U-28: 접속 IP 및 포트 제한 (중요도: 상)
# 판단기준: 방화벽(ufw/iptables) 또는 TCP Wrapper로 접근 제한 설정 시 양호
# ------------------------------------------------------------------------------
log_item "U-28" "접속 IP 및 포트 제한" "상"
EV_PARTS=()
STATUS="취약"

# UFW 확인
if command -v ufw > /dev/null 2>&1; then
    UFW_STATUS=$(ufw status 2>/dev/null | head -1)
    EV_PARTS+=("UFW: $UFW_STATUS")
    echo "$UFW_STATUS" | grep -q "^Status: active" && STATUS="양호"
fi

# iptables 확인
if command -v iptables > /dev/null 2>&1; then
    IPTABLES_RULES=$(iptables -L INPUT --line-numbers -n 2>/dev/null | grep -v "^Chain\|^num\|^$" | wc -l)
    EV_PARTS+=("iptables INPUT 규칙 수: $IPTABLES_RULES")
    [ "$IPTABLES_RULES" -gt 0 ] && STATUS="양호"
fi

# TCP Wrapper 확인
if [ -f /etc/hosts.allow ] || [ -f /etc/hosts.deny ]; then
    HOSTS_ALLOW=$(grep -v "^#\|^$" /etc/hosts.allow 2>/dev/null | wc -l)
    HOSTS_DENY=$(grep -v "^#\|^$" /etc/hosts.deny 2>/dev/null | wc -l)
    EV_PARTS+=("TCP Wrapper - hosts.allow 규칙: $HOSTS_ALLOW, hosts.deny 규칙: $HOSTS_DENY")
    [ "$HOSTS_ALLOW" -gt 0 ] || [ "$HOSTS_DENY" -gt 0 ] && STATUS="양호"
fi

EV=$(printf "%s\n" "${EV_PARTS[@]}")
[ "$STATUS" = "취약" ] && EV="${EV}
[판정] UFW/iptables 접근 제어 미설정 또는 규칙 없음"
log_result "$STATUS" "$EV"

# ------------------------------------------------------------------------------
# U-29: hosts.lpd 파일 소유자 및 권한 (중요도: 하)
# 판단기준: 파일 없거나, 있으면 소유자=root, 권한=600 이하
# ------------------------------------------------------------------------------
log_item "U-29" "hosts.lpd 파일 소유자 및 권한" "하"
if [ -f /etc/hosts.lpd ]; then
    PERM=$(stat -c "%a" /etc/hosts.lpd)
    OWNER=$(stat -c "%U" /etc/hosts.lpd)
    EV="/etc/hosts.lpd: owner=$OWNER, perm=$PERM (600 이하, root 소유 필요)"
    if [ "$OWNER" = "root" ] && perm_le "$PERM" "600"; then
        log_result "양호" "$EV"
    else
        log_result "취약" "$EV"
    fi
else
    log_result "N/A" "/etc/hosts.lpd 파일 없음 (양호)"
fi

# ------------------------------------------------------------------------------
# U-30: UMASK 설정 관리 (중요도: 중)
# 판단기준: UMASK 022 이상(022, 027, 077 등) 설정 시 양호
# ------------------------------------------------------------------------------
log_item "U-30" "UMASK 설정 관리" "중"
UMASK_VAL=""
UMASK_SRC=""
for F in /etc/profile /etc/bash.bashrc /etc/login.defs /etc/profile.d/*.sh; do
    [ -f "$F" ] || continue
    VAL=$(grep -iE "^[[:space:]]*umask[[:space:]]" "$F" 2>/dev/null | awk '{print $2}' | head -1)
    if [ -n "$VAL" ]; then
        UMASK_VAL="$VAL"
        UMASK_SRC="$F"
        break
    fi
done
# login.defs의 UMASK
if [ -z "$UMASK_VAL" ]; then
    UMASK_VAL=$(grep "^UMASK" /etc/login.defs 2>/dev/null | awk '{print $2}')
    UMASK_SRC="/etc/login.defs"
fi

EV="UMASK 설정 파일: ${UMASK_SRC:-미발견}
UMASK 값: ${UMASK_VAL:-미설정} (022 이상 권고)"
if [ -n "$UMASK_VAL" ]; then
    # UMASK 022 이상 = 8진수로 022(18) 이상
    UMASK_DEC=$((8#${UMASK_VAL})) 2>/dev/null || UMASK_DEC=0
    LIMIT_DEC=$((8#022))
    if [ "$UMASK_DEC" -ge "$LIMIT_DEC" ]; then
        log_result "양호" "$EV"
    else
        log_result "취약" "$EV"
    fi
else
    log_result "취약" "$EV"
fi

# ------------------------------------------------------------------------------
# U-31: 홈 디렉토리 소유자 및 권한 (중요도: 중)
# 판단기준: 홈 디렉토리 소유자=해당계정, 타 사용자 쓰기 권한 없음
# ------------------------------------------------------------------------------
log_item "U-31" "홈 디렉토리 소유자 및 권한" "중"
BAD_HOME=()
while IFS=: read -r USER _ ACCT_UID _ _ HOME _; do
    [ "$ACCT_UID" -lt 1000 ] && [ "$USER" != "root" ] && continue
    [ -z "$HOME" ] || [ ! -d "$HOME" ] && continue
    OWNER=$(stat -c "%U" "$HOME" 2>/dev/null)
    PERM=$(stat -c "%a" "$HOME" 2>/dev/null)
    # 기타(other) 쓰기 권한: perm 마지막 자리가 2,3,6,7
    OTHER_W=$((8#$PERM % 8))
    if [ "$OWNER" != "$USER" ] || [ $((OTHER_W & 2)) -ne 0 ]; then
        BAD_HOME+=("$USER: home=$HOME, owner=$OWNER, perm=$PERM")
    fi
done < /etc/passwd

EV="홈 디렉토리 소유자/권한 이상: ${BAD_HOME[*]:-없음}"
if [ ${#BAD_HOME[@]} -eq 0 ]; then
    log_result "양호" "$EV"
else
    log_result "취약" "$EV"
fi

# ------------------------------------------------------------------------------
# U-32: 홈 디렉토리가 존재하지 않는 계정 (중요도: 중)
# 판단기준: 홈 디렉토리 미존재 계정 없는 경우 양호
# ------------------------------------------------------------------------------
log_item "U-32" "홈 디렉토리 존재 여부" "중"
NO_HOME=()
while IFS=: read -r USER _ ACCT_UID _ _ HOME SHELL; do
    [ "$ACCT_UID" -lt 1000 ] && [ "$USER" != "root" ] && continue
    case "$SHELL" in
        /bin/false|/sbin/nologin|/usr/sbin/nologin) continue ;;
    esac
    [ -n "$HOME" ] && [ ! -d "$HOME" ] && NO_HOME+=("$USER (home=$HOME)")
done < /etc/passwd

EV="홈 디렉토리 미존재 계정: ${NO_HOME[*]:-없음}"
if [ ${#NO_HOME[@]} -eq 0 ]; then
    log_result "양호" "$EV"
else
    log_result "취약" "$EV"
fi

# ------------------------------------------------------------------------------
# U-33: 숨겨진 파일 및 디렉토리 검색 및 제거 (중요도: 하)
# 판단기준: 편집기 스왑 파일(.swp/.swo/.bak) 미존재 시 양호
#           (시스템 정상 숨김 파일은 판단 대상 제외)
# ------------------------------------------------------------------------------
log_item "U-33" "숨겨진 파일 및 디렉토리 점검" "하"
# 편집기 스왑/임시 파일만 취약 판정 대상 (정상 숨김파일과 구분)
SWP_FILES=$(find /etc /usr /bin /sbin /var /root /home -name "*.swp" -o -name "*.swo" -o -name "*.swpx" 2>/dev/null | head -20)
# 기타 숨김 파일은 참고 정보로만 출력 (취약 판정 제외)
OTHER_HIDDEN=$(find /etc /usr /bin /sbin /var -maxdepth 3 -name ".*" -not -name ".." -not -name "." 2>/dev/null | head -20)

EV="편집기 스왑 파일 (.swp/.swo): ${SWP_FILES:-없음}
기타 숨김 파일 (참고용, 취약 판정 제외): ${OTHER_HIDDEN:-없음}
[안내] 스왑 파일은 편집 중 비정상 종료 시 생성됨 — 직접 삭제 가능"
if [ -z "$SWP_FILES" ]; then
    log_result "양호" "$EV"
else
    log_result "취약" "$EV"
fi

# ==============================================================================
# 3. 서비스 관리 (U-34 ~ U-63)
# ==============================================================================
log_header "3. 서비스 관리"

# ------------------------------------------------------------------------------
# U-34: Finger 서비스 비활성화 (중요도: 상)
# 판단기준: Finger 서비스 비활성화 시 양호
# ------------------------------------------------------------------------------
log_item "U-34" "Finger 서비스 비활성화" "상"
FINGER_STATUS=$(check_service "finger")
FINGER_PKG=$(dpkg -l finger 2>/dev/null | grep "^ii" | head -1)
EV="finger 패키지: ${FINGER_PKG:-미설치}
finger 서비스 상태: $FINGER_STATUS"
if [ "$FINGER_STATUS" = "not-installed" ] || [ "$FINGER_STATUS" = "inactive" ]; then
    log_result "N/A" "$EV"
else
    log_result "취약" "$EV"
fi

# ------------------------------------------------------------------------------
# U-35: 공유 서비스에 대한 익명 접근 제한 (중요도: 상)
# 판단기준: Samba/NFS 공유 익명 접근 제한 시 양호
# ------------------------------------------------------------------------------
log_item "U-35" "공유 서비스 익명 접근 제한" "상"
EV_PARTS=()
STATUS="양호"

# Samba 확인
SMBD_STATUS=$(check_service "smbd")
if [ "$SMBD_STATUS" = "active" ]; then
    SMB_ANON=$(grep -iE "^[[:space:]]*(guest ok|map to guest)" /etc/samba/smb.conf 2>/dev/null | grep -iv "^#" | head -3)
    EV_PARTS+=("Samba: 활성 | 익명 접근 설정: ${SMB_ANON:-없음}")
    echo "$SMB_ANON" | grep -qi "yes" && STATUS="취약"
else
    EV_PARTS+=("Samba(smbd): ${SMBD_STATUS}")
fi

EV=$(printf "%s\n" "${EV_PARTS[@]}")
if [ "$SMBD_STATUS" = "not-installed" ]; then
    log_result "N/A" "Samba 미설치"
else
    log_result "$STATUS" "$EV"
fi

# ------------------------------------------------------------------------------
# U-36: r 계열 서비스 비활성화 (중요도: 상)
# 판단기준: rsh, rlogin, rexec, rcp 서비스 비활성화 시 양호
# ------------------------------------------------------------------------------
log_item "U-36" "r 계열 서비스 비활성화" "상"
R_SVCS=("rsh" "rlogin" "rexec" "rsh-server" "rsh.socket")
R_ACTIVE=()
for SVC in "${R_SVCS[@]}"; do
    STATUS_R=$(check_service "$SVC")
    [ "$STATUS_R" = "active" ] && R_ACTIVE+=("$SVC")
done
# rsh, rlogin 패키지 확인
R_PKG=$(dpkg -l rsh-server 2>/dev/null | grep "^ii" | head -1)

EV="r 계열 서비스 패키지: ${R_PKG:-미설치}
활성화된 r 계열 서비스: ${R_ACTIVE[*]:-없음}"
if [ ${#R_ACTIVE[@]} -eq 0 ]; then
    log_result "N/A" "$EV"
else
    log_result "취약" "$EV"
fi

# ------------------------------------------------------------------------------
# U-37: crontab 설정파일 권한 설정 (중요도: 상)
# 판단기준: crontab 명령어 권한 750 이하, cron 관련 파일 640 이하
# ------------------------------------------------------------------------------
log_item "U-37" "crontab 설정파일 권한" "상"
EV_PARTS=()
STATUS="양호"

CRONTAB_BIN=$(which crontab 2>/dev/null || echo "/usr/bin/crontab")
if [ -f "$CRONTAB_BIN" ]; then
    PERM=$(stat -c "%a" "$CRONTAB_BIN")
    OWNER=$(stat -c "%U" "$CRONTAB_BIN")
    EV_PARTS+=("$CRONTAB_BIN: owner=$OWNER, perm=$PERM")
    # SUID(4xxx)/SGID(2xxx) 비트 제거 후 순수 권한만 비교
    # Ubuntu 22.04에서 /usr/bin/crontab 기본값 2755(SGID)는 정상
    PERM_PLAIN=$(( 8#$PERM & 0777 ))
    PERM_PLAIN_OCT=$(printf "%o" "$PERM_PLAIN")
    perm_le "$PERM_PLAIN_OCT" "755" || STATUS="취약"
fi

for CRON_F in /etc/crontab /etc/cron.allow /etc/cron.deny; do
    [ -f "$CRON_F" ] || continue
    PERM=$(stat -c "%a" "$CRON_F")
    OWNER=$(stat -c "%U" "$CRON_F")
    EV_PARTS+=("$CRON_F: owner=$OWNER, perm=$PERM")
    if [ "$OWNER" != "root" ] || ! perm_le "$PERM" "640"; then
        STATUS="취약"
    fi
done

for CRON_D in /etc/cron.d /etc/cron.daily /etc/cron.hourly /etc/cron.weekly /etc/cron.monthly; do
    [ -d "$CRON_D" ] || continue
    PERM=$(stat -c "%a" "$CRON_D")
    OWNER=$(stat -c "%U" "$CRON_D")
    EV_PARTS+=("$CRON_D/: owner=$OWNER, perm=$PERM")
    if [ "$OWNER" != "root" ] || ! perm_le "$PERM" "755"; then
        STATUS="취약"
    fi
done

EV=$(printf "%s\n" "${EV_PARTS[@]}")
log_result "$STATUS" "$EV"

# ------------------------------------------------------------------------------
# U-38: DoS 공격에 취약한 서비스 비활성화 (중요도: 상)
# 판단기준: echo, discard, daytime, chargen 서비스 비활성화 시 양호
# ------------------------------------------------------------------------------
log_item "U-38" "DoS 취약 서비스 비활성화" "상"
DOS_SVCS=("echo" "discard" "daytime" "chargen" "time")
DOS_ACTIVE=()
for SVC in "${DOS_SVCS[@]}"; do
    for SOCK in "${SVC}.socket" "${SVC}@.service"; do
        STATUS_S=$(check_service "$SOCK")
        [ "$STATUS_S" = "active" ] && DOS_ACTIVE+=("$SOCK") && break
    done
done
# inetd 기반 서비스 확인
for F in /etc/inetd.conf /etc/xinetd.d/*; do
    [ -f "$F" ] || continue
    for SVC in echo discard daytime chargen; do
        grep -q "^$SVC" "$F" 2>/dev/null && DOS_ACTIVE+=("inetd:$SVC")
    done
done

EV="활성화된 DoS 취약 서비스: ${DOS_ACTIVE[*]:-없음}"
if [ ${#DOS_ACTIVE[@]} -eq 0 ]; then
    log_result "N/A" "$EV (해당 서비스 미설치/비활성)"
else
    log_result "취약" "$EV"
fi

# ------------------------------------------------------------------------------
# U-39: 불필요한 NFS 서비스 비활성화 (중요도: 상)
# ------------------------------------------------------------------------------
log_item "U-39" "불필요한 NFS 서비스 비활성화" "상"
NFS_STATUS=$(check_service "nfs-server")
NFS_KERNEL=$(check_service "nfs-kernel-server")
EV="nfs-server 상태: $NFS_STATUS
nfs-kernel-server 상태: $NFS_KERNEL"
if [ "$NFS_STATUS" = "active" ] || [ "$NFS_KERNEL" = "active" ]; then
    EXPORTS=$(cat /etc/exports 2>/dev/null | grep -v "^#\|^$")
    EV="${EV}
/etc/exports 내용: ${EXPORTS:-없음}"
    log_result "취약" "$EV"
else
    log_result "N/A" "$EV (NFS 서비스 비활성화)"
fi

# ------------------------------------------------------------------------------
# U-40: NFS 접근 통제 (중요도: 상)
# 판단기준: NFS 접근 통제 설정, /etc/exports 권한 644 이하
# ------------------------------------------------------------------------------
log_item "U-40" "NFS 접근 통제" "상"
if [ -f /etc/exports ]; then
    PERM=$(stat -c "%a" /etc/exports)
    OWNER=$(stat -c "%U" /etc/exports)
    EXPORTS_NO_RESTRICT=$(grep -v "^#\|^$" /etc/exports 2>/dev/null | grep -v "$(no_root_squash\|subtree_check)" | head -5 || true)
    EV="/etc/exports: owner=$OWNER, perm=$PERM
와일드카드(*) NFS 공유: $(grep '\*' /etc/exports | grep -v '^#' | head -3 || echo '없음')"
    if [ "$OWNER" = "root" ] && perm_le "$PERM" "644"; then
        log_result "양호" "$EV"
    else
        log_result "취약" "$EV"
    fi
else
    log_result "N/A" "/etc/exports 없음 (NFS 미사용)"
fi

# ------------------------------------------------------------------------------
# U-41: 불필요한 automountd 제거 (중요도: 상)
# ------------------------------------------------------------------------------
log_item "U-41" "불필요한 automountd 제거" "상"
AUTO_STATUS=$(check_service "autofs")
EV="autofs 서비스 상태: $AUTO_STATUS"
if [ "$AUTO_STATUS" = "active" ]; then
    log_result "취약" "$EV (autofs 비활성화 필요)"
else
    log_result "N/A" "$EV (autofs 비활성화 상태)"
fi

# ------------------------------------------------------------------------------
# U-42: 불필요한 RPC 서비스 비활성화 (중요도: 상)
# ------------------------------------------------------------------------------
log_item "U-42" "불필요한 RPC 서비스 비활성화" "상"
RPC_SVCS=("rpcbind" "rpcd" "rpc-statd")
RPC_ACTIVE=()
for SVC in "${RPC_SVCS[@]}"; do
    STATUS_R=$(check_service "$SVC")
    [ "$STATUS_R" = "active" ] && RPC_ACTIVE+=("$SVC")
done

EV="활성화된 RPC 서비스: ${RPC_ACTIVE[*]:-없음}"
if [ ${#RPC_ACTIVE[@]} -gt 0 ]; then
    log_result "취약" "$EV (불필요한 경우 비활성화 권고)"
else
    log_result "N/A" "$EV (RPC 서비스 비활성화)"
fi

# ------------------------------------------------------------------------------
# U-43: NIS, NIS+ 점검 (중요도: 상)
# 판단기준: NIS 비활성화 시 양호
# ------------------------------------------------------------------------------
log_item "U-43" "NIS/NIS+ 서비스 점검" "상"
NIS_SVCS=("nis" "ypbind" "ypserv" "yppasswdd" "ypxfrd")
NIS_ACTIVE=()
for SVC in "${NIS_SVCS[@]}"; do
    STATUS_N=$(check_service "$SVC")
    [ "$STATUS_N" = "active" ] && NIS_ACTIVE+=("$SVC")
done
NIS_PKG=$(dpkg -l nis 2>/dev/null | grep "^ii" | head -1)

EV="NIS 패키지: ${NIS_PKG:-미설치}
활성화된 NIS 서비스: ${NIS_ACTIVE[*]:-없음}"
if [ ${#NIS_ACTIVE[@]} -gt 0 ]; then
    log_result "취약" "$EV"
else
    log_result "N/A" "$EV (NIS 비활성화 상태)"
fi

# ------------------------------------------------------------------------------
# U-44: tftp, talk 서비스 비활성화 (중요도: 상)
# ------------------------------------------------------------------------------
log_item "U-44" "tftp, talk 서비스 비활성화" "상"
UNSAFE_SVCS=("tftp" "tftpd" "talkd" "ntalk" "tftpd-hpa")
UNSAFE_ACTIVE=()
for SVC in "${UNSAFE_SVCS[@]}"; do
    STATUS_S=$(check_service "$SVC")
    [ "$STATUS_S" = "active" ] && UNSAFE_ACTIVE+=("$SVC")
done
TFTP_PKG=$(dpkg -l tftpd tftpd-hpa 2>/dev/null | grep "^ii" | awk '{print $2}' | tr '\n' ' ')
TALK_PKG=$(dpkg -l talkd 2>/dev/null | grep "^ii" | awk '{print $2}' | tr '\n' ' ')

EV="tftp 패키지: ${TFTP_PKG:-미설치}, talk 패키지: ${TALK_PKG:-미설치}
활성화된 서비스: ${UNSAFE_ACTIVE[*]:-없음}"
if [ ${#UNSAFE_ACTIVE[@]} -gt 0 ]; then
    log_result "취약" "$EV"
else
    log_result "N/A" "$EV (서비스 비활성화 상태)"
fi

# ------------------------------------------------------------------------------
# U-45: 메일 서비스 버전 점검 (중요도: 상)
# 판단기준: 최신 버전 사용 또는 서비스 미사용 시 양호
# ------------------------------------------------------------------------------
log_item "U-45" "메일 서비스 버전 점검" "상"
MAIL_SVCS=("postfix" "sendmail" "exim4" "dovecot")
MAIL_ACTIVE=()
MAIL_VERS=()
for SVC in "${MAIL_SVCS[@]}"; do
    STATUS_M=$(check_service "$SVC")
    if [ "$STATUS_M" = "active" ]; then
        MAIL_ACTIVE+=("$SVC")
        case "$SVC" in
            postfix) VER=$(postconf -d mail_version 2>/dev/null | awk '{print $3}') ;;
            exim4)   VER=$(exim4 --version 2>/dev/null | head -1) ;;
            *)       VER="버전 확인 불가" ;;
        esac
        MAIL_VERS+=("$SVC=$VER")
    fi
done

EV="활성화된 메일 서비스: ${MAIL_ACTIVE[*]:-없음}
버전 정보: ${MAIL_VERS[*]:-N/A}"
if [ ${#MAIL_ACTIVE[@]} -eq 0 ]; then
    log_result "N/A" "$EV (메일 서비스 미사용)"
else
    log_result "양호" "$EV
[안내] 메일 서비스 사용 중. 운영자가 최신 버전 여부를 직접 확인 필요"
fi

# ------------------------------------------------------------------------------
# U-46: 일반 사용자의 메일 서비스 실행 방지 (중요도: 상)
# 판단기준: root 또는 전용 계정으로 메일 서비스 실행 시 양호
# ------------------------------------------------------------------------------
log_item "U-46" "일반 사용자의 메일 서비스 실행 방지" "상"
MAIL_PROC=$(ps aux 2>/dev/null | grep -E "postfix|sendmail|exim" | grep -v grep | awk '{print $1, $11}' | head -5)
EV="메일 서비스 프로세스 실행 계정: ${MAIL_PROC:-메일 서비스 미실행}"
if [ -z "$MAIL_PROC" ]; then
    # 메일 서비스 미실행 → 점검 대상 아님
    log_result "N/A" "$EV"
elif echo "$MAIL_PROC" | grep -qvE "^(root|postfix|mail|nobody)"; then
    log_result "취약" "$EV"
else
    log_result "양호" "$EV"
fi

# ------------------------------------------------------------------------------
# U-47: 스팸 메일 릴레이 제한 (중요도: 상)
# 판단기준: 릴레이 제한 설정 시 양호
# ------------------------------------------------------------------------------
log_item "U-47" "스팸 메일 릴레이 제한" "상"
POSTFIX_STATUS=$(check_service "postfix")
if [ "$POSTFIX_STATUS" = "active" ]; then
    RELAY=$(postconf -n smtpd_recipient_restrictions 2>/dev/null || echo "미설정")
    MY_NET=$(postconf -n mynetworks 2>/dev/null || echo "미설정")
    EV="postfix smtpd_recipient_restrictions: $RELAY
postfix mynetworks: $MY_NET"
    if echo "$RELAY" | grep -q "permit_mynetworks\|reject_unauth_destination"; then
        log_result "양호" "$EV"
    else
        log_result "취약" "$EV"
    fi
else
    log_result "N/A" "메일 서비스(postfix) 비활성화 상태"
fi

# ------------------------------------------------------------------------------
# U-48: expn, vrfy 명령어 제한 (중요도: 중)
# 판단기준: noexpn, novrfy 옵션 설정 시 양호
# ------------------------------------------------------------------------------
log_item "U-48" "SMTP expn, vrfy 명령어 제한" "중"
POSTFIX_STATUS=$(check_service "postfix")
if [ "$POSTFIX_STATUS" = "active" ]; then
    VRFY=$(postconf -n disable_vrfy_command 2>/dev/null || echo "미설정")
    EV="postfix disable_vrfy_command: $VRFY"
    echo "$VRFY" | grep -qi "yes" && log_result "양호" "$EV" || log_result "취약" "$EV"
else
    log_result "N/A" "메일 서비스(postfix) 비활성화 상태"
fi

# ------------------------------------------------------------------------------
# U-49: DNS 보안 버전 패치 (중요도: 상)
# 판단기준: 최신 패치 또는 서비스 미사용 시 양호
# ------------------------------------------------------------------------------
log_item "U-49" "DNS 보안 버전 패치" "상"
NAMED_STATUS=$(check_service "named")
BIND9_STATUS=$(check_service "bind9")
if [ "$NAMED_STATUS" = "active" ] || [ "$BIND9_STATUS" = "active" ]; then
    NAMED_VER=$(named -v 2>/dev/null | head -1 || echo "버전 확인 불가")
    EV="BIND9 버전: $NAMED_VER
[안내] 운영자가 최신 보안 패치 적용 여부 확인 필요"
    log_result "양호" "$EV"
else
    log_result "N/A" "DNS 서비스(named/bind9) 비활성화 상태"
fi

# ------------------------------------------------------------------------------
# U-50: DNS Zone Transfer 설정 (중요도: 상)
# 판단기준: Zone Transfer 허가된 호스트에만 허용 시 양호
# ------------------------------------------------------------------------------
log_item "U-50" "DNS Zone Transfer 설정" "상"
BIND9_STATUS=$(check_service "bind9")
if [ "$BIND9_STATUS" = "active" ]; then
    NAMED_CONF=$(find /etc/bind /etc/named -name "named.conf*" 2>/dev/null | head -1)
    if [ -n "$NAMED_CONF" ]; then
        ALLOW_TRANSFER=$(grep -i "allow-transfer" "$NAMED_CONF" 2>/dev/null | head -3)
        EV="$NAMED_CONF allow-transfer 설정: ${ALLOW_TRANSFER:-미설정}"
        if echo "$ALLOW_TRANSFER" | grep -qE "none|[0-9]+\.[0-9]+"; then
            log_result "양호" "$EV"
        else
            log_result "취약" "$EV"
        fi
    else
        log_result "취약" "BIND 설정 파일 미발견"
    fi
else
    log_result "N/A" "DNS 서비스(bind9) 비활성화 상태"
fi

# ------------------------------------------------------------------------------
# U-51: DNS 동적 업데이트 설정 금지 (중요도: 중)
# 판단기준: 동적 업데이트 비활성화 또는 접근통제 설정 시 양호
# ------------------------------------------------------------------------------
log_item "U-51" "DNS 동적 업데이트 설정 금지" "중"
BIND9_STATUS=$(check_service "bind9")
if [ "$BIND9_STATUS" = "active" ]; then
    NAMED_CONF=$(find /etc/bind /etc/named -name "named.conf*" 2>/dev/null | head -1)
    if [ -n "$NAMED_CONF" ]; then
        ALLOW_UPDATE=$(grep -i "allow-update" "$NAMED_CONF" 2>/dev/null | head -3)
        EV="allow-update 설정: ${ALLOW_UPDATE:-미설정}"
        if echo "$ALLOW_UPDATE" | grep -qE "none"; then
            log_result "양호" "$EV"
        elif [ -z "$ALLOW_UPDATE" ]; then
            log_result "양호" "$EV (allow-update 미설정 = 동적 업데이트 비활성화)"
        else
            log_result "취약" "$EV"
        fi
    else
        log_result "N/A" "BIND 설정 파일 미발견"
    fi
else
    log_result "N/A" "DNS 서비스(bind9) 비활성화 상태"
fi

# ------------------------------------------------------------------------------
# U-52: Telnet 서비스 비활성화 (중요도: 중)
# 판단기준: Telnet 비활성화 시 양호
# ------------------------------------------------------------------------------
log_item "U-52" "Telnet 서비스 비활성화" "중"
TELNET_SVC=$(check_service "telnet")
TELNETD_SVC=$(check_service "telnetd")
TELNET_INETD=""
for F in /etc/inetd.conf /etc/xinetd.d/telnet; do
    [ -f "$F" ] && grep -q "^telnet" "$F" 2>/dev/null && TELNET_INETD="$F"
done
TELNET_LISTEN=$(ss -tlnp 2>/dev/null | grep ":23 " | head -1)

EV="telnet 서비스: $TELNET_SVC, telnetd: $TELNETD_SVC
inetd 기반 telnet: ${TELNET_INETD:-없음}
TCP 23번 포트 Listen: ${TELNET_LISTEN:-없음}"
if [ "$TELNET_SVC" = "active" ] || [ "$TELNETD_SVC" = "active" ] || \
   [ -n "$TELNET_INETD" ] || [ -n "$TELNET_LISTEN" ]; then
    log_result "취약" "$EV"
else
    log_result "N/A" "$EV (Telnet 비활성화)"
fi

# ------------------------------------------------------------------------------
# U-53: FTP 서비스 정보 노출 제한 (중요도: 하)
# 판단기준: FTP 배너 정보 최소화 시 양호
# ------------------------------------------------------------------------------
log_item "U-53" "FTP 서비스 정보 노출 제한" "하"
FTP_STATUS=$(check_service "vsftpd")
FTPD_STATUS=$(check_service "proftpd")
if [ "$FTP_STATUS" = "active" ]; then
    FTP_BANNER=$(grep -iE "^[[:space:]]*(ftpd_banner|banner_file)" /etc/vsftpd.conf 2>/dev/null | head -3)
    EV="vsftpd: 활성 | 배너 설정: ${FTP_BANNER:-미설정 (기본 배너 노출 가능)}"
    [ -n "$FTP_BANNER" ] && log_result "양호" "$EV" || log_result "취약" "$EV"
elif [ "$FTPD_STATUS" = "active" ]; then
    log_result "양호" "proftpd: 활성 (배너 설정 운영자 확인 필요)"
else
    log_result "N/A" "FTP 서비스(vsftpd/proftpd) 비활성화 상태"
fi

# ------------------------------------------------------------------------------
# U-54: 암호화되지 않은 FTP 서비스 비활성화 (중요도: 중)
# 판단기준: 평문 FTP 비활성화 시 양호
# ------------------------------------------------------------------------------
log_item "U-54" "암호화되지 않은 FTP 비활성화" "중"
FTP_STATUS=$(check_service "vsftpd")
FTP_LISTEN=$(ss -tlnp 2>/dev/null | grep ":21 " | head -1)
EV="vsftpd 상태: $FTP_STATUS
TCP 21번 포트 Listen: ${FTP_LISTEN:-없음}"
if [ "$FTP_STATUS" = "active" ] || [ -n "$FTP_LISTEN" ]; then
    log_result "취약" "$EV (평문 FTP 사용 중. SFTP/FTPS 전환 권고)"
else
    log_result "N/A" "$EV (FTP 비활성화 상태)"
fi

# ------------------------------------------------------------------------------
# U-55: FTP 계정 Shell 제한 (중요도: 중)
# 판단기준: FTP 계정에 /bin/false 또는 /sbin/nologin 쉘 부여 시 양호
# ------------------------------------------------------------------------------
log_item "U-55" "FTP 계정 Shell 제한" "중"
FTP_PKG=$(dpkg -l vsftpd proftpd-core 2>/dev/null | grep "^ii" | awk '{print $2}' | tr '\n' ' ')
FTP_STATUS=$(check_service "vsftpd")
if [ -n "$FTP_PKG" ] || [ "$FTP_STATUS" = "active" ]; then
    FTP_ACCT=$(getent passwd ftp 2>/dev/null)
    if [ -n "$FTP_ACCT" ]; then
        FTP_SHELL=$(echo "$FTP_ACCT" | awk -F: '{print $7}')
        EV="ftp 계정: $FTP_ACCT
ftp 계정 Shell: $FTP_SHELL"
        case "$FTP_SHELL" in
            /bin/false|/sbin/nologin|/usr/sbin/nologin)
                log_result "양호" "$EV" ;;
            *)
                log_result "취약" "$EV (nologin/false 설정 필요)" ;;
        esac
    else
        log_result "N/A" "ftp 계정 없음"
    fi
else
    log_result "N/A" "FTP 서비스 미설치"
fi

# ------------------------------------------------------------------------------
# U-56: FTP 서비스 접근 제어 설정 (중요도: 하)
# 판단기준: 특정 IP/호스트만 FTP 접근 허용 시 양호
# ------------------------------------------------------------------------------
log_item "U-56" "FTP 서비스 접근 제어 설정" "하"
FTP_STATUS=$(check_service "vsftpd")
if [ "$FTP_STATUS" = "active" ]; then
    TCP_WRAP=$(grep -E "^vsftpd" /etc/hosts.allow /etc/hosts.deny 2>/dev/null | head -3)
    PAM_FTP=$(grep -r "pam_access\|userlist" /etc/vsftpd.conf 2>/dev/null | head -3)
    EV="TCP Wrapper FTP 제한: ${TCP_WRAP:-없음}
vsftpd 접근 제어: ${PAM_FTP:-없음}"
    if [ -n "$TCP_WRAP" ] || [ -n "$PAM_FTP" ]; then
        log_result "양호" "$EV"
    else
        log_result "취약" "$EV"
    fi
else
    log_result "N/A" "FTP 서비스 비활성화 상태"
fi

# ------------------------------------------------------------------------------
# U-57: Ftpusers 파일 설정 (중요도: 중)
# 판단기준: FTP root 계정 접속 차단 시 양호 (ftpusers에 root 등록)
# ------------------------------------------------------------------------------
log_item "U-57" "Ftpusers 파일 설정 (FTP root 차단)" "중"
FTP_STATUS=$(check_service "vsftpd")
if [ "$FTP_STATUS" = "active" ]; then
    FTPUSERS_FOUND=false
    for FTPUSERS_F in /etc/ftpusers /etc/vsftpd.ftpusers /etc/vsftpd/ftpusers; do
        if [ -f "$FTPUSERS_F" ]; then
            FTPUSERS_FOUND=true
            ROOT_IN_FILE=$(grep "^root" "$FTPUSERS_F" || true)
            EV="$FTPUSERS_F 내 root 차단: ${ROOT_IN_FILE:-미설정}"
            if [ -n "$ROOT_IN_FILE" ]; then
                log_result "양호" "$EV"
            else
                log_result "취약" "$EV"
            fi
            break
        fi
    done
    # 파일 없을 경우
    if ! $FTPUSERS_FOUND; then
        log_result "취약" "ftpusers 파일 없음 (root FTP 접근 차단 설정 필요)"
    fi
else
    log_result "N/A" "FTP 서비스 비활성화 상태"
fi

# ------------------------------------------------------------------------------
# U-58: 불필요한 SNMP 서비스 구동 점검 (중요도: 중)
# 판단기준: SNMP 서비스 미사용 시 양호
# ------------------------------------------------------------------------------
log_item "U-58" "불필요한 SNMP 서비스 점검" "중"
SNMP_STATUS=$(check_service "snmpd")
SNMP_PKG=$(dpkg -l snmpd 2>/dev/null | grep "^ii" | head -1)
EV="snmpd 패키지: ${SNMP_PKG:-미설치}
snmpd 서비스 상태: $SNMP_STATUS"
if [ "$SNMP_STATUS" = "active" ]; then
    log_result "취약" "$EV (SNMP 미사용 시 비활성화 필요)"
else
    log_result "N/A" "$EV (SNMP 비활성화 상태)"
fi

# ------------------------------------------------------------------------------
# U-59: 안전한 SNMP 버전 사용 (중요도: 상)
# 판단기준: SNMP v3 이상 사용 시 양호
# ------------------------------------------------------------------------------
log_item "U-59" "안전한 SNMP 버전 사용" "상"
SNMP_STATUS=$(check_service "snmpd")
if [ "$SNMP_STATUS" = "active" ]; then
    SNMP_CONF="/etc/snmp/snmpd.conf"
    if [ -f "$SNMP_CONF" ]; then
        SNMPV3_USR=$(grep "^createUser\|^rouser\|^rwuser" "$SNMP_CONF" | head -3)
        V1V2_COM=$(grep "^rocommunity\|^rwcommunity" "$SNMP_CONF" | grep -v "^#" | head -3)
        EV="SNMPv3 사용자: ${SNMPV3_USR:-없음}
v1/v2 Community: ${V1V2_COM:-없음}"
        if [ -n "$SNMPV3_USR" ] && [ -z "$V1V2_COM" ]; then
            log_result "양호" "$EV"
        else
            log_result "취약" "$EV (v1/v2 사용 중 또는 v3 미설정)"
        fi
    else
        log_result "취약" "SNMP 설정 파일($SNMP_CONF) 없음"
    fi
else
    log_result "N/A" "SNMP 서비스 비활성화 상태"
fi

# ------------------------------------------------------------------------------
# U-60: SNMP Community String 복잡성 설정 (중요도: 중)
# 판단기준: Community String이 public/private 아닌 영숫자 10자 이상 또는 영숫특 8자 이상
# ------------------------------------------------------------------------------
log_item "U-60" "SNMP Community String 복잡성" "중"
SNMP_STATUS=$(check_service "snmpd")
if [ "$SNMP_STATUS" = "active" ]; then
    SNMP_CONF="/etc/snmp/snmpd.conf"
    if [ -f "$SNMP_CONF" ]; then
        COMMUNITIES=$(grep -E "^(rocommunity|rwcommunity)" "$SNMP_CONF" | grep -v "^#" | awk '{print $2}')
        BAD_COM=()
        for COM in $COMMUNITIES; do
            if echo "$COM" | grep -qiE "^(public|private)$"; then
                BAD_COM+=("$COM(기본값)")
            elif [ ${#COM} -lt 8 ]; then
                BAD_COM+=("$COM(8자 미만)")
            fi
        done
        EV="Community String: ${COMMUNITIES:-없음}
취약 Community: ${BAD_COM[*]:-없음}"
        if [ ${#BAD_COM[@]} -eq 0 ] && [ -n "$COMMUNITIES" ]; then
            log_result "양호" "$EV"
        else
            log_result "취약" "$EV"
        fi
    else
        log_result "취약" "SNMP 설정 파일 없음"
    fi
else
    log_result "N/A" "SNMP 서비스 비활성화 상태"
fi

# ------------------------------------------------------------------------------
# U-61: SNMP Access Control 설정 (중요도: 상)
# 판단기준: SNMP 접근 제어 설정 시 양호
# ------------------------------------------------------------------------------
log_item "U-61" "SNMP Access Control 설정" "상"
SNMP_STATUS=$(check_service "snmpd")
if [ "$SNMP_STATUS" = "active" ]; then
    SNMP_CONF="/etc/snmp/snmpd.conf"
    if [ -f "$SNMP_CONF" ]; then
        ACCESS_CTRL=$(grep -E "^(com2sec|access|view|agentaddress)" "$SNMP_CONF" | grep -v "^#" | head -5)
        EV="SNMP 접근 제어 설정: ${ACCESS_CTRL:-없음}"
        if [ -n "$ACCESS_CTRL" ]; then
            log_result "양호" "$EV"
        else
            log_result "취약" "$EV"
        fi
    else
        log_result "취약" "SNMP 설정 파일 없음"
    fi
else
    log_result "N/A" "SNMP 서비스 비활성화 상태"
fi

# ------------------------------------------------------------------------------
# U-62: 로그인 시 경고 메시지 설정 (중요도: 하)
# 판단기준: 서버 및 서비스 로그온 시 경고 메시지 설정 시 양호
# ------------------------------------------------------------------------------
log_item "U-62" "로그인 시 경고 메시지 설정" "하"
EV_PARTS=()
STATUS="취약"

# /etc/motd 확인
MOTD=$(cat /etc/motd 2>/dev/null | grep -v "^$" | head -3)
[ -n "$MOTD" ] && EV_PARTS+=("/etc/motd: $MOTD") && STATUS="양호"

# /etc/issue 및 /etc/issue.net 확인
ISSUE=$(cat /etc/issue 2>/dev/null | grep -v "^$\|Ubuntu\|\\\\n\|\\\\l" | head -2)
ISSUE_NET=$(cat /etc/issue.net 2>/dev/null | grep -v "^$\|Ubuntu" | head -2)
[ -n "$ISSUE" ] && EV_PARTS+=("/etc/issue: $ISSUE") && STATUS="양호"
[ -n "$ISSUE_NET" ] && EV_PARTS+=("/etc/issue.net: $ISSUE_NET") && STATUS="양호"

# SSH 배너 확인
SSH_BANNER=$(grep -iE "^[[:space:]]*Banner" /etc/ssh/sshd_config 2>/dev/null | head -1)
[ -n "$SSH_BANNER" ] && EV_PARTS+=("SSH Banner: $SSH_BANNER") && STATUS="양호"

[ ${#EV_PARTS[@]} -eq 0 ] && EV_PARTS+=("경고 메시지 미설정 (/etc/motd, /etc/issue, SSH Banner 없음)")

EV=$(printf "%s\n" "${EV_PARTS[@]}")
log_result "$STATUS" "$EV"

# ------------------------------------------------------------------------------
# U-63: sudo 명령어 접근 관리 (중요도: 중)
# 판단기준: /etc/sudoers 소유자=root, 권한=640 이하 (Ubuntu 기본 440)
# ------------------------------------------------------------------------------
log_item "U-63" "sudo 명령어 접근 관리" "중"
SUDOERS="/etc/sudoers"
if [ -f "$SUDOERS" ]; then
    PERM=$(stat -c "%a" "$SUDOERS")
    OWNER=$(stat -c "%U" "$SUDOERS")
    SUDO_RULES=$(grep -v "^#\|^$\|^Defaults\|^%sudo\|ALL=(ALL" "$SUDOERS" 2>/dev/null | grep "ALL" | head -5)
    EV="/etc/sudoers: owner=$OWNER, perm=$PERM (640 이하, root 소유 필요)
위험 sudo 규칙(NOPASSWD 등): $(grep -i NOPASSWD "$SUDOERS" 2>/dev/null | grep -v '^#' | head -5 || echo '없음')"
    if [ "$OWNER" = "root" ] && perm_le "$PERM" "640"; then
        log_result "양호" "$EV"
    else
        log_result "취약" "$EV"
    fi
else
    log_result "N/A" "/etc/sudoers 파일 없음"
fi

# ==============================================================================
# 4. 패치 관리 (U-64 ~ U-65)
# ==============================================================================
log_header "4. 패치 관리"

# ------------------------------------------------------------------------------
# U-64: 최신 보안 패치 적용 (중요도: 상)
# 판단기준: 주기적 패치 관리 및 보안 패치 적용 시 양호
# ------------------------------------------------------------------------------
log_item "U-64" "최신 보안 패치 적용" "상"
echo ""
printf "    (업그레이드 가능한 패키지 확인 중...)"
UPGRADABLE=$(apt list --upgradable 2>/dev/null | grep -v "Listing" | grep -c . || true)
SECURITY_UP=$(apt list --upgradable 2>/dev/null | grep -i "security" | head -10)
SECURITY_COUNT=$(echo "$SECURITY_UP" | grep -c . || true)
echo ""

LAST_UPDATE=$(stat -c "%y" /var/lib/apt/lists/ 2>/dev/null | cut -d'.' -f1)
KERNEL_CURRENT=$(uname -r)

EV="업그레이드 가능한 패키지 수: $UPGRADABLE
보안 업데이트 대기 수: $SECURITY_COUNT
apt 마지막 업데이트: ${LAST_UPDATE:-알 수 없음}
현재 커널: $KERNEL_CURRENT
보안 업데이트 패키지(상위 10개):
${SECURITY_UP:-없음}"

if [ "$UPGRADABLE" -eq 0 ]; then
    log_result "양호" "$EV"
elif [ "$SECURITY_COUNT" -gt 0 ]; then
    log_result "취약" "$EV"
else
    log_result "양호" "$EV
[안내] 일반 업데이트 $UPGRADABLE개 대기 중 (보안 업데이트 없음 확인됨)"
fi

# ------------------------------------------------------------------------------
# U-65: NTP 및 시각 동기화 (중요도: 중)
# 판단기준: NTP 동기화 설정 시 양호
# ------------------------------------------------------------------------------
log_item "U-65" "NTP 및 시각 동기화 설정" "중"
EV_PARTS=()
STATUS="취약"

# systemd-timesyncd 확인
TIMESYNC_STATUS=$(check_service "systemd-timesyncd")
if [ "$TIMESYNC_STATUS" = "active" ]; then
    TIMESYNC_STATUS_DETAIL=$(timedatectl status 2>/dev/null | grep -E "NTP|synchronized|Time zone" | head -3)
    EV_PARTS+=("systemd-timesyncd: 활성")
    EV_PARTS+=("timedatectl: $TIMESYNC_STATUS_DETAIL")
    STATUS="양호"
fi

# chrony 확인
CHRONY_STATUS=$(check_service "chronyd")
if [ "$CHRONY_STATUS" = "active" ]; then
    CHRONY_SOURCES=$(chronyc sources 2>/dev/null | head -5 || echo "소스 없음")
    EV_PARTS+=("chrony: 활성 | 소스: $CHRONY_SOURCES")
    STATUS="양호"
fi

# ntpd 확인
NTP_STATUS=$(check_service "ntp")
if [ "$NTP_STATUS" = "active" ]; then
    NTP_SERVERS=$(grep "^server\|^pool" /etc/ntp.conf 2>/dev/null | head -3)
    EV_PARTS+=("ntpd: 활성 | 서버: ${NTP_SERVERS:-미설정}")
    STATUS="양호"
fi

[ ${#EV_PARTS[@]} -eq 0 ] && EV_PARTS+=("NTP 관련 서비스 미활성화")
EV=$(printf "%s\n" "${EV_PARTS[@]}")
log_result "$STATUS" "$EV"

# ==============================================================================
# 5. 로그 관리 (U-66 ~ U-67)
# ==============================================================================
log_header "5. 로그 관리"

# ------------------------------------------------------------------------------
# U-66: 정책에 따른 시스템 로깅 설정 (중요도: 중)
# 판단기준: 로그 기록 정책 수립 및 rsyslog 설정 시 양호
# ------------------------------------------------------------------------------
log_item "U-66" "정책에 따른 시스템 로깅 설정" "중"
RSYSLOG_STATUS=$(check_service "rsyslog")
SYSLOG_STATUS=$(check_service "syslog")
EV_PARTS=()
STATUS="취약"

if [ "$RSYSLOG_STATUS" = "active" ]; then
    STATUS="양호"
    EV_PARTS+=("rsyslog: 활성")
    # 주요 로그 파일 존재 확인
    for LOGF in /var/log/syslog /var/log/auth.log /var/log/kern.log /var/log/mail.log; do
        if [ -f "$LOGF" ]; then
            LOGSIZE=$(du -sh "$LOGF" 2>/dev/null | awk '{print $1}')
            LASTMOD=$(stat -c "%y" "$LOGF" | cut -d'.' -f1)
            EV_PARTS+=("$LOGF: $LOGSIZE, 최종수정=$LASTMOD")
        else
            EV_PARTS+=("$LOGF: 미존재")
        fi
    done
    # rsyslog.conf 주요 설정 확인
    RSYSLOG_CONF_CHECK=$(grep -v "^#\|^$" /etc/rsyslog.conf 2>/dev/null | head -10)
    EV_PARTS+=("/etc/rsyslog.conf 주요 설정: $RSYSLOG_CONF_CHECK")
elif [ "$SYSLOG_STATUS" = "active" ]; then
    STATUS="양호"
    EV_PARTS+=("syslog: 활성")
else
    EV_PARTS+=("rsyslog/syslog 서비스 비활성화")
fi

EV=$(printf "%s\n" "${EV_PARTS[@]}")
log_result "$STATUS" "$EV"

# ------------------------------------------------------------------------------
# U-67: 로그 디렉터리 소유자 및 권한 설정 (중요도: 중)
# 판단기준: /var/log 내 로그 파일 소유자=root, 권한=644 이하
# ------------------------------------------------------------------------------
log_item "U-67" "로그 디렉터리 소유자 및 권한" "중"
VARLOG_PERM=$(stat -c "%a" /var/log)
VARLOG_OWNER=$(stat -c "%U" /var/log)
BAD_LOGS=()

# /var/log 디렉터리 자체
EV_PARTS=("/var/log: owner=$VARLOG_OWNER, perm=$VARLOG_PERM")

# 주요 로그 파일 권한 확인
# wtmp: root:utmp 664 정상 (getty/login 그룹 쓰기 필요, logrotate 호환)
# btmp: root:utmp 600 정상 (실패 로그인 기록, root 전용)
# lastlog: root 644 정상
while IFS= read -r LOGF; do
    PERM=$(stat -c "%a" "$LOGF" 2>/dev/null)
    OWNER=$(stat -c "%U" "$LOGF" 2>/dev/null)
    BASENAME=$(basename "$LOGF")
    case "$BASENAME" in
        wtmp)
            # 664 이하 허용 (root:utmp, logrotate 호환)
            if ! [[ "$OWNER" =~ ^(root|syslog)$ ]] || ! perm_le "$PERM" "664" 2>/dev/null; then
                BAD_LOGS+=("$LOGF: owner=$OWNER, perm=$PERM")
            fi
            ;;
        btmp)
            # 600 이하 허용
            if ! [[ "$OWNER" =~ ^(root|syslog)$ ]] || ! perm_le "$PERM" "600" 2>/dev/null; then
                BAD_LOGS+=("$LOGF: owner=$OWNER, perm=$PERM")
            fi
            ;;
        *)
            # 일반 로그 파일: 644 이하
            # Ubuntu rsyslog는 syslog 유저로 로그 파일 생성 (syslog:adm 640) → 허용
            if ! [[ "$OWNER" =~ ^(root|syslog)$ ]] || ! perm_le "$PERM" "644" 2>/dev/null; then
                BAD_LOGS+=("$LOGF: owner=$OWNER, perm=$PERM")
            fi
            ;;
    esac
done < <(find /var/log -maxdepth 1 -type f 2>/dev/null | head -20)

EV_PARTS+=("권한 이상 로그 파일: ${BAD_LOGS[*]:-없음}")
EV=$(printf "%s\n" "${EV_PARTS[@]}")

if [ "$VARLOG_OWNER" = "root" ] && perm_le "$VARLOG_PERM" "755" && [ ${#BAD_LOGS[@]} -eq 0 ]; then
    log_result "양호" "$EV"
else
    log_result "취약" "$EV"
fi

# ==============================================================================
# 최종 요약 보고서
# ==============================================================================
END_TIME=$(date "+%Y-%m-%d %H:%M:%S")
ELAPSED=$(($(date +%s) - $(date -d "$START_TIME" +%s 2>/dev/null || date +%s)))

{
log_raw ""
log_raw ""
log_header "점검 결과 요약"
log_raw ""
log_raw "  점검 완료 시각 : $END_TIME"
log_raw "  총 점검 항목   : $TOTAL 개"
log_raw "  양 호          : $GOOD 개"
log_raw "  취 약          : $VULN 개"
log_raw "  N/A (해당없음) : $NA 개"
log_raw ""

# 항목별 ID 목록 출력 (8개씩 줄바꿈)
print_id_list() {
    local LABEL="$1"; shift
    local IDS=("$@")
    if [ ${#IDS[@]} -eq 0 ]; then
        log_raw "  ${LABEL}: (없음)"
        return
    fi
    log_raw "  ${LABEL} (${#IDS[@]}개):"
    local LINE=""
    local CNT=0
    for ID in "${IDS[@]}"; do
        LINE="${LINE}${ID} "
        CNT=$((CNT+1))
        if [ $((CNT % 8)) -eq 0 ]; then
            log_raw "    ${LINE}"
            LINE=""
        fi
    done
    [ -n "$LINE" ] && log_raw "    ${LINE}"
}

print_id_list "양 호 항목" "${GOOD_IDS[@]}"
log_raw ""
print_id_list "취 약 항목" "${VULN_IDS[@]}"
log_raw ""
print_id_list "N/A 항목" "${NA_IDS[@]}"
log_raw ""

# 취약률 계산
if [ "$((GOOD + VULN))" -gt 0 ]; then
    VULN_RATE=$(( VULN * 100 / (GOOD + VULN) ))
    GOOD_RATE=$(( GOOD * 100 / (GOOD + VULN) ))
    log_raw "  양호율 (N/A 제외): ${GOOD_RATE}%  |  취약률: ${VULN_RATE}%"
fi

log_raw ""
log_raw "  [위험도 평가]"
if [ "$VULN" -ge 20 ]; then
    log_raw "  판정: 위험 (취약 항목 $VULN개 - 즉각적인 보안 조치 필요)"
elif [ "$VULN" -ge 10 ]; then
    log_raw "  판정: 주의 (취약 항목 $VULN개 - 단기 내 보안 조치 필요)"
elif [ "$VULN" -ge 5 ]; then
    log_raw "  판정: 보통 (취약 항목 $VULN개 - 개선 권고)"
else
    log_raw "  판정: 양호 (취약 항목 $VULN개)"
fi

log_raw ""
log_raw "=================================================================================="
log_raw "  보고서 파일: $RESULT_FILE"
log_raw "  기준: 2026 주요정보통신기반시설 기술적 취약점 분석·평가 방법 상세가이드 (KISA)"
log_raw "=================================================================================="
} 2>/dev/null || true

echo ""
echo "================================================================"
echo "  점검 완료"
echo "  총 항목: $TOTAL | 양호: $GOOD | 취약: $VULN | N/A: $NA"
echo "  보고서: $RESULT_FILE"
echo "================================================================"
