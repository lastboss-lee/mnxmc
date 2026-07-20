#!/bin/bash
# ==============================================================================
# MNX 기술적 취약점 분석·평가 — 최종 As-is / To-be 보고서 생성기
# 출력: PDF (xelatex), HTML, DOCX
# 입력: 가장 최근 infra_remediate_final_*.txt + Before/After audit 리포트
# ------------------------------------------------------------------------------
# 사용법:
#   sudo bash generate_pdf_report.sh                  # 기본: 최신 final 자동 선택
#   sudo bash generate_pdf_report.sh <final_txt>      # 명시 지정
#   sudo bash generate_pdf_report.sh --install-deps   # 의존성만 설치
#   sudo bash generate_pdf_report.sh --offline        # apt 건너뛰고 HTML/MD만 생성
#   sudo bash generate_pdf_report.sh --yes            # 확인 프롬프트 자동 승인
# ==============================================================================

set -u

# ------------------------------------------------------------------------------
# 권한 확인
# ------------------------------------------------------------------------------
if [ "$EUID" -ne 0 ]; then
    echo "[오류] root 권한으로 실행해야 합니다. sudo bash $0"
    exit 1
fi

# ------------------------------------------------------------------------------
# 인자 처리
# ------------------------------------------------------------------------------
INSTALL_DEPS_ONLY=false
OFFLINE=false
ASSUME_YES=false
FINAL_FILE=""

for ARG in "$@"; do
    case "$ARG" in
        --install-deps) INSTALL_DEPS_ONLY=true ;;
        --offline)      OFFLINE=true ;;
        --yes|-y)       ASSUME_YES=true ;;
        -h|--help)
            sed -n '2,16p' "$0"; exit 0 ;;
        *)              FINAL_FILE="$ARG" ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${SCRIPT_DIR}/reports"
mkdir -p "$OUT_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BASE_NAME="infra_audit_as-is_to-be_${TIMESTAMP}"
MD_FILE="${OUT_DIR}/${BASE_NAME}.md"
PDF_FILE="${OUT_DIR}/${BASE_NAME}.pdf"
HTML_FILE="${OUT_DIR}/${BASE_NAME}.html"
DOCX_FILE="${OUT_DIR}/${BASE_NAME}.docx"
HEADER_TEX="${OUT_DIR}/${BASE_NAME}.header.tex"

# ------------------------------------------------------------------------------
# 의존성 정의 / 확인 / 설치
# ------------------------------------------------------------------------------
REQUIRED_PKGS=(
    pandoc
    texlive-xetex
    texlive-fonts-recommended
    texlive-lang-korean
    fonts-noto-cjk
    fonts-noto-cjk-extra
)

check_dep() {
    local PKG="$1"
    dpkg -l "$PKG" 2>/dev/null | grep -q "^ii"
}

missing_pkgs() {
    local MISSING=()
    for P in "${REQUIRED_PKGS[@]}"; do
        check_dep "$P" || MISSING+=("$P")
    done
    printf '%s\n' "${MISSING[@]}"
}

install_deps() {
    local MISSING
    MISSING=$(missing_pkgs)
    if [ -z "$MISSING" ]; then
        echo "[정보] 모든 의존성 패키지 설치됨."
        return 0
    fi

    echo "[정보] 누락된 패키지 ($(echo "$MISSING" | wc -l)개):"
    echo "$MISSING" | sed 's/^/  - /'

    if ! $ASSUME_YES; then
        read -r -p "  apt-get install 을 진행하시겠습니까? [y/N]: " ANS
        if [[ ! "$ANS" =~ ^[Yy]$ ]]; then
            echo "[정보] 의존성 설치 건너뜀 — HTML/MD만 생성됩니다."
            return 1
        fi
    fi

    echo "[정보] 패키지 설치 시작 (인터넷 연결 필요, 약 1.5GB)..."
    DEBIAN_FRONTEND=noninteractive apt-get update -qq
    # shellcheck disable=SC2086
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends $(echo "$MISSING" | tr '\n' ' ')
    local APT_RC=$?

    # TeX live 패키지 설치/갱신 후에는 파일 인덱스(ls-R)를 재구축해야 xelatex가 새 .sty를 찾을 수 있음
    if command -v mktexlsr >/dev/null 2>&1; then
        echo "[정보] TeX live 파일 인덱스 재구축 (mktexlsr)..."
        mktexlsr >/dev/null 2>&1 || true
    fi

    return $APT_RC
}

# 의존성이 이미 모두 설치된 환경에서도 ls-R 캐시가 stale일 수 있으므로,
# pandoc PDF 변환 전에 한 번 더 보장 (idempotent, 비용 낮음)
ensure_texlive_index() {
    if command -v mktexlsr >/dev/null 2>&1 && command -v xelatex >/dev/null 2>&1; then
        if ! kpsewhich ctexhook.sty >/dev/null 2>&1; then
            echo "[정보] ctexhook.sty kpsewhich 미발견 — mktexlsr 강제 갱신"
            mktexlsr >/dev/null 2>&1 || true
        fi
    fi
}

if $INSTALL_DEPS_ONLY; then
    install_deps
    exit $?
fi

CAN_PDF=true
if ! $OFFLINE; then
    if ! install_deps; then
        CAN_PDF=false
    fi
fi

# 최종 의존성 재확인
if ! command -v pandoc >/dev/null 2>&1; then
    echo "[경고] pandoc 미설치 — MD만 출력됩니다."
    CAN_PDF=false
fi
if ! command -v xelatex >/dev/null 2>&1; then
    echo "[경고] xelatex 미설치 — PDF 변환 생략, HTML/DOCX만 시도합니다."
    CAN_PDF=false
fi

# ------------------------------------------------------------------------------
# 입력 리포트 자동 탐색
# ------------------------------------------------------------------------------
AUDIT_ONLY=false

if [ -z "$FINAL_FILE" ]; then
    FINAL_FILE=$(ls -t "${SCRIPT_DIR}"/infra_remediate_final_*.txt 2>/dev/null | head -1)
    if [ -z "$FINAL_FILE" ]; then
        FINAL_FILE=$(ls -t "${SCRIPT_DIR}"/tmp/infra_remediate_final_*.txt 2>/dev/null | head -1)
    fi
fi

if [ -z "$FINAL_FILE" ] || [ ! -f "$FINAL_FILE" ]; then
    # Fallback: final 리포트가 없으면 가장 최근 audit 리포트 1개로 단일 스냅샷 PDF 생성
    AUDIT_SNAPSHOT=$(ls -t "${SCRIPT_DIR}"/infra_audit_report_*.txt 2>/dev/null | head -1)
    if [ -z "$AUDIT_SNAPSHOT" ] || [ ! -f "$AUDIT_SNAPSHOT" ]; then
        echo "[오류] final 리포트와 audit 리포트 모두 찾을 수 없습니다."
        echo "       먼저 infra_audit.sh 를 실행하여 infra_audit_report_*.txt 를"
        echo "       생성하세요. (조치를 적용했다면 infra_remediate.sh 도 실행)"
        exit 1
    fi
    AUDIT_ONLY=true
    FINAL_FILE=""
    BEFORE_FILE="$AUDIT_SNAPSHOT"
    AFTER_FILE="$AUDIT_SNAPSHOT"
    echo "[정보] Final 리포트 미발견 — audit 단일 스냅샷 모드로 PDF 생성"
    echo "[정보] Audit 리포트: $AUDIT_SNAPSHOT"
else
    echo "[정보] Final 리포트: $FINAL_FILE"

    # Before/After 추출
    BEFORE_FILE=$(grep -E "Before[[:space:]]*:" "$FINAL_FILE" | awk '{print $NF}' | head -1)
    AFTER_FILE=$(grep -E "After[[:space:]]*:" "$FINAL_FILE" | awk '{print $NF}' | head -1)

    # final 파일과 같은 디렉토리 우선, 없으면 tmp/ 도 탐색
    resolve_path() {
        local P="$1"
        [ -f "$P" ] && { echo "$P"; return; }
        local BN
        BN=$(basename "$P")
        for D in "$(dirname "$FINAL_FILE")" "$SCRIPT_DIR" "$SCRIPT_DIR/tmp"; do
            [ -f "$D/$BN" ] && { echo "$D/$BN"; return; }
        done
        echo ""
    }

    BEFORE_FILE=$(resolve_path "$BEFORE_FILE")
    AFTER_FILE=$(resolve_path "$AFTER_FILE")

    if [ -z "$BEFORE_FILE" ] || [ -z "$AFTER_FILE" ]; then
        echo "[오류] Before/After 리포트 경로 해석 실패"
        echo "  Before: ${BEFORE_FILE:-(없음)}"
        echo "  After : ${AFTER_FILE:-(없음)}"
        exit 1
    fi
fi

# 부가 자료 — FINAL_FILE이 비어 있으면 SCRIPT_DIR 폴백
LOG_SEARCH_DIR="${FINAL_FILE:+$(dirname "$FINAL_FILE")}"
LOG_SEARCH_DIR="${LOG_SEARCH_DIR:-$SCRIPT_DIR}"
REMEDIATE_LOG=$(ls -t "$LOG_SEARCH_DIR"/infra_remediate_*.log 2>/dev/null | head -1)
REMEDIATE_REPORT=$(ls -t "$LOG_SEARCH_DIR"/infra_remediate_report_*.txt 2>/dev/null | head -1)

echo "[정보] Before  : $BEFORE_FILE"
echo "[정보] After   : $AFTER_FILE"
echo "[정보] 조치로그 : ${REMEDIATE_LOG:-(없음)}"
echo "[정보] 상세리포트: ${REMEDIATE_REPORT:-(없음)}"

# ------------------------------------------------------------------------------
# 파서
# ------------------------------------------------------------------------------
HOSTNAME_VAL=$(hostname)
OS_VAL=$(grep PRETTY_NAME /etc/os-release 2>/dev/null | cut -d'"' -f2 || echo "Unknown")
KERNEL_VAL=$(uname -r)
GEN_TIME=$(date "+%Y-%m-%d %H:%M:%S %Z")

# 항목 블록 추출 (audit 리포트에서 [U-XX] 블록 ─ 진단결과 + 상세근거)
get_item_block() {
    local F="$1"
    local ID="$2"
    awk -v id="$ID" '
        $0 ~ "^┌─ \\["id"\\]" {flag=1}
        flag {print}
        /^└/ && flag {flag=0; print ""; exit}
    ' "$F" 2>/dev/null
}

# 진단결과 추출
get_status_only() {
    local BLOCK="$1"
    echo "$BLOCK" | grep -oE "\[양호\]|\[취약\]|\[N/A\]" | head -1
}

# 상세근거 한 줄(들)만
get_evidence_only() {
    echo "$1" | sed -n 's/^│[[:space:]]*상세근거:[[:space:]]*//p'
}

# 항목 제목 (audit 헤더에서 추출)
get_item_title() {
    local BLOCK="$1"
    echo "$BLOCK" | grep -oP '┌─ \[U-\d+\]\s+\K[^(]+' | sed 's/[[:space:]]*$//'
}

get_item_importance() {
    local BLOCK="$1"
    echo "$BLOCK" | grep -oP '중요도:\s*\K[상중하]'
}

# 조치 로그에서 해당 항목의 적용 명령 추출
get_applied_commands() {
    local ID="$1"
    [ -z "$REMEDIATE_LOG" ] && return
    awk -v id="$ID" '
        $0 ~ "\\["id"\\]" {print}
    ' "$REMEDIATE_LOG" 2>/dev/null | head -15
}

# remediate_report 에서 평가기준 + 현재설정 발췌
get_remediate_section() {
    local ID="$1"
    [ -z "$REMEDIATE_REPORT" ] && return
    awk -v id="$ID" '
        $0 ~ "\\["id"\\]" && /^[[:space:]]*\[(AUTO|SEMI|MANUAL)/ {flag=1; print; next}
        flag && /^======/ {flag=0; exit}
        flag {print}
    ' "$REMEDIATE_REPORT" 2>/dev/null
}

# ------------------------------------------------------------------------------
# Summary 파싱
# ------------------------------------------------------------------------------
parse_summary() {
    local F="$1"; local G V N
    G=$(grep -E "^[[:space:]]*양[[:space:]]*호[[:space:]]*:" "$F" 2>/dev/null | head -1 | grep -oE '[0-9]+' | head -1)
    V=$(grep -E "^[[:space:]]*취[[:space:]]*약[[:space:]]*:" "$F" 2>/dev/null | head -1 | grep -oE '[0-9]+' | head -1)
    N=$(grep -E "^[[:space:]]*N/A[[:space:]]*\(해당없음\)" "$F" 2>/dev/null | head -1 | grep -oE '[0-9]+' | head -1)
    echo "${G:-0} ${V:-0} ${N:-0}"
}

read -r BG BV BN <<< "$(parse_summary "$BEFORE_FILE")"
read -r AG AV AN <<< "$(parse_summary "$AFTER_FILE")"

# 해결/잔존/신규 항목
extract_vuln_ids() {
    awk '/^┌─ \[U-[0-9]+\]/{ match($0,/U-[0-9]+/); id=substr($0,RSTART,RLENGTH) }
         /진단결과:[[:space:]]*\[취약\]/{print id}' "$1" 2>/dev/null | sort -u
}
RESOLVED_IDS=$(comm -23 <(extract_vuln_ids "$BEFORE_FILE") <(extract_vuln_ids "$AFTER_FILE") | tr '\n' ' ')
REMAIN_IDS=$(comm -12 <(extract_vuln_ids "$BEFORE_FILE") <(extract_vuln_ids "$AFTER_FILE") | tr '\n' ' ')
NEW_IDS=$(comm -13 <(extract_vuln_ids "$BEFORE_FILE") <(extract_vuln_ids "$AFTER_FILE") | tr '\n' ' ')

# ------------------------------------------------------------------------------
# Markdown 본문 생성
# ------------------------------------------------------------------------------
echo "[정보] Markdown 생성: $MD_FILE"

# 마크다운 안전 escape (백틱/파이프)
md_escape() {
    sed -e 's/\\/\\\\/g' -e 's/|/\\|/g'
}

# 코드블록 안전 출력 — pandoc이 Shaded/Highlighting 환경을 생성하도록 언어 태그 부여
code_block() {
    local TITLE="$1"; shift
    local CONTENT="$*"
    [ -z "$CONTENT" ] && CONTENT="(내용 없음)"
    cat << CB
**${TITLE}**

\`\`\`text
${CONTENT}
\`\`\`

CB
}

# 항목 1개 마크다운 섹션 생성
emit_item_section() {
    local ID="$1"
    local BEFORE_BLOCK AFTER_BLOCK
    BEFORE_BLOCK=$(get_item_block "$BEFORE_FILE" "$ID")
    AFTER_BLOCK=$(get_item_block "$AFTER_FILE" "$ID")

    local TITLE IMP B_STATUS A_STATUS
    TITLE=$(get_item_title "$BEFORE_BLOCK")
    [ -z "$TITLE" ] && TITLE=$(get_item_title "$AFTER_BLOCK")
    IMP=$(get_item_importance "$BEFORE_BLOCK")
    [ -z "$IMP" ] && IMP=$(get_item_importance "$AFTER_BLOCK")
    B_STATUS=$(get_status_only "$BEFORE_BLOCK")
    A_STATUS=$(get_status_only "$AFTER_BLOCK")

    local B_EV A_EV CMDS REM_SEC
    B_EV=$(get_evidence_only "$BEFORE_BLOCK")
    A_EV=$(get_evidence_only "$AFTER_BLOCK")
    CMDS=$(get_applied_commands "$ID")
    REM_SEC=$(get_remediate_section "$ID")

    # 상태 변화 아이콘
    local CHANGE_MARK=""
    if [ "$B_STATUS" = "[취약]" ] && [ "$A_STATUS" != "[취약]" ]; then
        CHANGE_MARK="해결됨"
    elif [ "$B_STATUS" = "[취약]" ] && [ "$A_STATUS" = "[취약]" ]; then
        CHANGE_MARK="잔존 (수동 조치 필요)"
    elif [ "$B_STATUS" != "[취약]" ] && [ "$A_STATUS" = "[취약]" ]; then
        CHANGE_MARK="신규 발견 (regression)"
    elif [ "$B_STATUS" = "[양호]" ] && [ "$A_STATUS" = "[양호]" ]; then
        CHANGE_MARK="양호 유지"
    elif [ "$B_STATUS" = "[N/A]" ]; then
        CHANGE_MARK="해당 없음"
    else
        CHANGE_MARK="변화 없음"
    fi

    cat << HDR

### ${ID} ${TITLE}

| 속성 | 값 |
|---|---|
| 중요도 | ${IMP:-?} |
| Before | ${B_STATUS:-N/A} |
| After  | ${A_STATUS:-N/A} |
| 상태   | **${CHANGE_MARK}** |

HDR

    code_block "As-is (조치 전 점검 결과)" "${B_EV:-(데이터 없음)}"
    code_block "To-be (조치 후 재점검 결과)" "${A_EV:-(데이터 없음)}"

    if [ -n "$CMDS" ]; then
        code_block "적용 명령 / 변경 로그 (조치 로그 발췌)" "$CMDS"
    fi

    if [ -n "$REM_SEC" ]; then
        code_block "평가 기준 / 권장 설정 (remediate 가이드)" "$REM_SEC"
    fi
}

# Header
{
cat << HEADER
---
title: "MNX 기술적 취약점 분석·평가 — 조치 보고서"
subtitle: "Unix 서버 (Ubuntu 22.04) 67개 항목 전수"
author: "SANDS LAB Inc. — MNX (NDR) Security Audit"
date: "${GEN_TIME}"
geometry: a4paper,margin=1.8cm,headheight=14pt
mainfont: "Noto Sans CJK KR"
monofont: "Noto Sans Mono CJK KR"
fontsize: 10pt
linkcolor: mnxblue
urlcolor: mnxblue
toccolor: mnxdark
---

\\newpage

# 1. 개요

| 항목 | 값 |
|---|---|
| 점검 기준 | 2026 주요정보통신기반시설 기술적 취약점 분석·평가 방법 상세가이드 (KISA) |
| 대상 호스트 | ${HOSTNAME_VAL} |
| 운영체제 | ${OS_VAL} |
| 커널 | ${KERNEL_VAL} |
| 점검 범위 | U-01 ~ U-67 (Unix 서버 전체 67항목) |
| 생성 시각 | ${GEN_TIME} |
| Before 리포트 | \`$(basename "$BEFORE_FILE")\` |
| After 리포트 | \`$(basename "$AFTER_FILE")\` |

\\newpage

# 2. Executive Summary

## 2.1 점검 결과 요약 (Before vs After)

| 구분 | Before | After | 변화 |
|---|---:|---:|---:|
| 양호 | ${BG} | ${AG} | $((AG-BG)) |
| 취약 | ${BV} | ${AV} | $((AV-BV)) |
| N/A  | ${BN} | ${AN} | $((AN-BN)) |
| **합계** | **$((BG+BV+BN))** | **$((AG+AV+AN))** | — |

HEADER

if [ "$((BG+BV))" -gt 0 ]; then
    GOOD_RATE_B=$(( BG * 100 / (BG + BV) ))
    GOOD_RATE_A=$(( AG * 100 / (AG + AV) ))
    echo "양호율 (N/A 제외): **Before ${GOOD_RATE_B}% → After ${GOOD_RATE_A}%**"
    echo ""
fi

cat << SUMMARY

## 2.2 항목별 상태 변화

| 분류 | 항목 ID | 건수 |
|---|---|---:|
| 해결 (취약 → 양호/N/A) | ${RESOLVED_IDS:-(없음)} | $(echo "$RESOLVED_IDS" | wc -w) |
| 잔존 취약 | ${REMAIN_IDS:-(없음)} | $(echo "$REMAIN_IDS" | wc -w) |
| 신규 발견 (regression) | ${NEW_IDS:-(없음)} | $(echo "$NEW_IDS" | wc -w) |

## 2.3 최종 판정

SUMMARY

if [ "$AV" -eq 0 ]; then
    echo "> **모든 취약 항목이 해소되었습니다 — 양호**"
elif [ -n "$NEW_IDS" ]; then
    echo "> **조치 후 신규 취약 발견 — 재점검 필요**"
elif [ -n "$REMAIN_IDS" ]; then
    echo "> **잔존 취약 ${AV}건 — MANUAL 가이드에 따른 수동 조치 필요**"
fi
echo ""
echo "\\newpage"
echo ""

# ------------------------------------------------------------------------------
# 본문: 67항목 전수 (분류별)
# ------------------------------------------------------------------------------

cat << SECT3
# 3. 해결된 항목 (취약 → 양호/N/A)

조치 적용으로 취약 → 양호 또는 N/A로 전환된 항목입니다. As-is(조치 전), To-be(조치 후), 적용 명령을 항목별로 기록합니다.

SECT3

if [ -n "$RESOLVED_IDS" ]; then
    for ID in $RESOLVED_IDS; do
        emit_item_section "$ID"
    done
else
    echo "_(해당 없음 — 조치된 항목이 없습니다)_"
fi

echo ""
echo "\\newpage"
echo ""

cat << SECT4
# 4. 잔존 취약 항목 (MANUAL 수동 조치 필요)

자동 조치 대상이 아니거나 운영 영향 검토 후 수동 적용이 필요한 항목입니다. 평가 기준과 권장 조치를 함께 기록합니다.

SECT4

if [ -n "$REMAIN_IDS" ]; then
    for ID in $REMAIN_IDS; do
        emit_item_section "$ID"
    done
else
    echo "_(잔존 취약 항목 없음)_"
fi

echo ""
echo "\\newpage"
echo ""

cat << SECT5
# 5. 신규 발견 취약 항목 (Regression)

조치 후 새롭게 취약으로 전환된 항목입니다. 조치 부작용 가능성이 있어 즉시 재검토가 필요합니다.

SECT5

if [ -n "$NEW_IDS" ]; then
    for ID in $NEW_IDS; do
        emit_item_section "$ID"
    done
else
    echo "_(신규 발견 항목 없음 — regression zero)_"
fi

echo ""
echo "\\newpage"
echo ""

cat << SECT6
# 6. 양호 항목 (변화 없음)

조치 전후 모두 양호로 판정된 항목입니다. 현재 설정이 KISA 2026 기준을 충족합니다.

SECT6

# After가 양호인 항목들 중 해결된 항목 제외
AFTER_GOOD_IDS=$(awk '/^┌─ \[U-[0-9]+\]/{ match($0,/U-[0-9]+/); id=substr($0,RSTART,RLENGTH) }
                      /진단결과:[[:space:]]*\[양호\]/{print id}' "$AFTER_FILE" | sort -u)
PURE_GOOD_IDS=$(comm -23 <(echo "$AFTER_GOOD_IDS") <(echo "$RESOLVED_IDS" | tr ' ' '\n' | sort -u) | tr '\n' ' ')

if [ -n "$PURE_GOOD_IDS" ]; then
    for ID in $PURE_GOOD_IDS; do
        emit_item_section "$ID"
    done
else
    echo "_(해당 없음)_"
fi

echo ""
echo "\\newpage"
echo ""

cat << SECT7
# 7. N/A 항목 (해당 없음)

서비스 미구동 / 미설치 등으로 점검 대상이 아닌 항목입니다.

SECT7

AFTER_NA_IDS=$(awk '/^┌─ \[U-[0-9]+\]/{ match($0,/U-[0-9]+/); id=substr($0,RSTART,RLENGTH) }
                    /진단결과:[[:space:]]*\[N\/A\]/{print id}' "$AFTER_FILE" | sort -u | tr '\n' ' ')

if [ -n "$AFTER_NA_IDS" ]; then
    for ID in $AFTER_NA_IDS; do
        emit_item_section "$ID"
    done
else
    echo "_(해당 없음)_"
fi

echo ""
echo "\\newpage"
echo ""

# ------------------------------------------------------------------------------
# 부록
# ------------------------------------------------------------------------------

# 예외 정책은 audit 리포트 헤더에서 추출
EXCLUDE_LINE=$(grep -A 1 "예외 디렉토리/파일 정책" "$AFTER_FILE" | tail -1)

cat << APPENDIX
# 8. 부록

## 8.1 예외 디렉토리/파일 정책

KISA 2026 가이드의 find 기반 점검(U-15 소유자 없는 파일, U-23 SUID/SGID, U-24 환경변수 파일, U-25 world-writable, U-31 홈 디렉토리 권한 등)에서 다음 경로는 점검 대상에서 제외되었습니다.

\`\`\`text
${EXCLUDE_LINE:-(정보 없음)}
\`\`\`

**사유:**

- \`/proc, /sys, /dev, /run\` — Linux 가상 파일시스템 (수정 불가)
- \`/tmp, /var/tmp\` — 정상적으로 world-writable + sticky bit 운영 디렉토리
- \`/data, /logs, /application, /opt/mnx\` — MNX 운영 데이터·로그 디렉토리. suricata/mnxcapture 등 데몬이 다른 UID로 로그를 적재하기 위해 0775/0777 권한이 정상 동작에 필요
- \`/mnt, /media, /var/lib/docker, /var/lib/containerd\` — 외부 마운트 / 컨테이너 레이어 (호스트 점검 범위 밖). containerd overlayfs 스냅샷에는 호스트에 등록되지 않은 UID/GID로 생성된 파일이 정상적으로 존재함 (U-15 \`-nouser/-nogroup\` false positive 방지)

## 8.2 백업 / 로그 위치

| 종류 | 경로 |
|---|---|
APPENDIX

if $AUDIT_ONLY; then
    echo "| 현재 상태 리포트 (단일 스냅샷) | \`${AFTER_FILE}\` |"
else
    echo "| Before 리포트 | \`${BEFORE_FILE}\` |"
    echo "| After 리포트 | \`${AFTER_FILE}\` |"
    echo "| Final 비교 리포트 | \`${FINAL_FILE}\` |"
fi

[ -n "$REMEDIATE_LOG" ] && echo "| 조치 로그 | \`${REMEDIATE_LOG}\` |"
[ -n "$REMEDIATE_REPORT" ] && echo "| 항목별 상세 리포트 | \`${REMEDIATE_REPORT}\` |"

BACKUP_SEARCH_DIR="${FINAL_FILE:+$(dirname "$FINAL_FILE")}"
BACKUP_SEARCH_DIR="${BACKUP_SEARCH_DIR:-$SCRIPT_DIR}"
BACKUP_DIR=$(ls -td "$BACKUP_SEARCH_DIR"/backup_*/ 2>/dev/null | head -1)
[ -n "$BACKUP_DIR" ] && echo "| 설정 파일 백업 | \`${BACKUP_DIR}\` |"

cat << TAIL

## 8.3 점검 도구 버전

| 도구 | 버전 |
|---|---|
| infra_audit.sh | 2.0.0 (2026-03-26) |
| infra_remediate.sh | 3.0.0 (2026-03-26) |
| generate_pdf_report.sh | 1.0.0 ($(date +%Y-%m-%d)) |
| pandoc | $(pandoc --version 2>/dev/null | head -1 | awk '{print $2}' || echo "미설치") |
| xelatex | $(xelatex --version 2>/dev/null | head -1 | awk '{print $NF}' || echo "미설치") |

---

*본 보고서는 자동 생성되었습니다. 조치 명령 적용 전 반드시 운영 환경 영향을 검토하시기 바랍니다.*
TAIL

} > "$MD_FILE"

echo "[정보] Markdown 생성 완료: $(wc -l < "$MD_FILE") 줄"

# ------------------------------------------------------------------------------
# PDF / HTML / DOCX 변환
# ------------------------------------------------------------------------------
GENERATED=()
GENERATED+=("$MD_FILE")

if command -v pandoc >/dev/null 2>&1; then
    # HTML
    echo "[정보] HTML 변환 중..."
    if pandoc "$MD_FILE" -o "$HTML_FILE" \
            --standalone --toc --toc-depth=2 \
            --metadata title="KISA 2026 As-is / To-be 보고서" \
            -V lang=ko 2>&1 | tail -5; then
        GENERATED+=("$HTML_FILE")
        echo "[정보] HTML 생성: $HTML_FILE"
    else
        echo "[경고] HTML 변환 실패"
    fi

    # DOCX
    echo "[정보] DOCX 변환 중..."
    if pandoc "$MD_FILE" -o "$DOCX_FILE" \
            --toc --toc-depth=2 2>&1 | tail -5; then
        GENERATED+=("$DOCX_FILE")
        echo "[정보] DOCX 생성: $DOCX_FILE"
    else
        echo "[경고] DOCX 변환 실패"
    fi

    # PDF
    if $CAN_PDF; then
        ensure_texlive_index

        # ----------------------------------------------------------------------
        # LaTeX 헤더 — pandoc 메타에 직접 넣으면 백슬래시가 markdown으로 해석되어
        # \\AtBeginDocument 등이 \textbackslash 로 변환됨. 별도 .tex 파일에 기록 후
        # --include-in-header 로 전달하면 그대로 preamble 에 삽입됨.
        # ----------------------------------------------------------------------
        cat > "$HEADER_TEX" << 'HDRTEX'
% ---- MNX KISA 보고서 커스텀 헤더 ----
\definecolor{mnxdark}{HTML}{1F2D3D}
\definecolor{mnxblue}{HTML}{0D6EFD}
\definecolor{mnxaccent}{HTML}{0EA5E9}
\definecolor{vulnred}{HTML}{C0392B}
\definecolor{goodgreen}{HTML}{15803D}
\definecolor{nagray}{HTML}{6B7280}
\definecolor{tblhead}{HTML}{E5EDF7}
\definecolor{codebg}{HTML}{F6F8FA}
\definecolor{coderule}{HTML}{D7DDE4}

% --- CJK 줄바꿈 — 긴 한글 문자열이 자간을 벌리지 않도록 ---
\usepackage{xeCJK}
\xeCJKsetup{CJKspace=true}
\XeTeXlinebreaklocale "ko"
\XeTeXlinebreakskip = 0pt plus 1pt minus 0.1pt
\XeTeXlinebreakpenalty = 0

% --- 긴 경로/URL 자동 줄바꿈 ---
\usepackage{fvextra}
\usepackage{mdframed}
\makeatletter
\AtBeginDocument{%
  \@ifundefined{Highlighting}%
    {\DefineVerbatimEnvironment{Highlighting}{Verbatim}{%
        breaklines=true,breakanywhere=true,commandchars=\\\{\},%
        fontsize=\small,xleftmargin=4pt}}%
    {\RecustomVerbatimEnvironment{Highlighting}{Verbatim}{%
        breaklines=true,breakanywhere=true,commandchars=\\\{\},%
        fontsize=\small,xleftmargin=4pt}}%
  \@ifundefined{Shaded}%
    {\newenvironment{Shaded}%
       {\begin{mdframed}[backgroundcolor=codebg,linecolor=coderule,linewidth=0.4pt,%
          innerleftmargin=6pt,innerrightmargin=6pt,innertopmargin=4pt,%
          innerbottommargin=4pt,skipabove=4pt,skipbelow=4pt]\small}%
       {\end{mdframed}}}%
    {\renewenvironment{Shaded}%
       {\begin{mdframed}[backgroundcolor=codebg,linecolor=coderule,linewidth=0.4pt,%
          innerleftmargin=6pt,innerrightmargin=6pt,innertopmargin=4pt,%
          innerbottommargin=4pt,skipabove=4pt,skipbelow=4pt]\small}%
       {\end{mdframed}}}%
  % verbatim (언어 미지정 코드블록) 도 줄바꿈 보강
  \RecustomVerbatimEnvironment{verbatim}{Verbatim}{%
    breaklines=true,breakanywhere=true,fontsize=\small,xleftmargin=4pt}%
}
\makeatother

% --- 표 디자인 ---
\usepackage{longtable,booktabs,array}
\renewcommand{\arraystretch}{1.25}
\setlength{\LTpre}{4pt}
\setlength{\LTpost}{6pt}
\setlength{\LTleft}{0pt}
\setlength{\LTright}{\fill}

% --- 섹션 헤더 컬러 + 룰 ---
\usepackage{titlesec}
\titleformat{\section}{\Large\bfseries\color{mnxdark}}{\thesection.}{0.6em}{}[{\color{mnxaccent}\titlerule[0.8pt]}]
\titleformat{\subsection}{\large\bfseries\color{mnxdark}}{\thesubsection}{0.5em}{}
\titleformat{\subsubsection}{\normalsize\bfseries\color{mnxblue}}{}{0pt}{}
\titlespacing*{\section}{0pt}{1.4ex plus 0.4ex minus 0.2ex}{1.0ex plus 0.2ex}
\titlespacing*{\subsection}{0pt}{1.0ex plus 0.3ex minus 0.2ex}{0.6ex plus 0.2ex}

% --- 페이지 헤더/푸터 ---
\usepackage{fancyhdr}
\pagestyle{fancy}
\fancyhf{}
\renewcommand{\headrulewidth}{0.4pt}
\renewcommand{\footrulewidth}{0pt}
\fancyhead[L]{\color{mnxdark}\small\textbf{KISA 2026 보안 점검 보고서}}
\fancyhead[R]{\color{mnxdark}\small __HOSTNAME__}
\fancyfoot[C]{\color{mnxdark}\small\thepage}

% --- 본문 줄바꿈 보강 ---
\setlength{\emergencystretch}{3em}
\sloppy

\usepackage{enumitem}
\setlist{nosep,leftmargin=*}
HDRTEX

        # 호스트명 치환 (heredoc 'HDRTEX' 인용으로 인해 변수 확장이 차단되므로 사후 치환)
        sed -i "s/__HOSTNAME__/${HOSTNAME_VAL}/g" "$HEADER_TEX"

        echo "[정보] PDF 변환 중 (xelatex)..."
        if pandoc "$MD_FILE" -o "$PDF_FILE" \
                --pdf-engine=xelatex \
                --toc --toc-depth=2 \
                --highlight-style=tango \
                --include-in-header="$HEADER_TEX" \
                -V lang=ko \
                -V CJKmainfont="Noto Sans CJK KR" \
                -V CJKmonofont="Noto Sans Mono CJK KR" \
                -V colorlinks=true \
                2> "${OUT_DIR}/${BASE_NAME}.pdf.log"; then
            GENERATED+=("$PDF_FILE")
            echo "[정보] PDF 생성: $PDF_FILE"
            rm -f "${OUT_DIR}/${BASE_NAME}.pdf.log" "$HEADER_TEX"
        else
            echo "[경고] PDF 변환 실패. 로그: ${OUT_DIR}/${BASE_NAME}.pdf.log"
            echo "       헤더 .tex 보존: $HEADER_TEX"
            echo "       HTML/DOCX 결과물은 정상 생성되었습니다."
        fi
    fi
fi

# ------------------------------------------------------------------------------
# 결과 요약
# ------------------------------------------------------------------------------
echo ""
echo "================================================================"
echo "  보고서 생성 완료"
echo "================================================================"
echo "  출력 디렉토리: $OUT_DIR/"
for F in "${GENERATED[@]}"; do
    SIZE=$(stat -c "%s" "$F" 2>/dev/null | awk '{printf "%.1fKB", $1/1024}')
    printf "    %-10s %s\n" "[$SIZE]" "$F"
done
echo "================================================================"

# 권장 다음 단계
echo ""
echo "  [확인 방법]"
[ -f "$PDF_FILE" ] && echo "    PDF  : evince $PDF_FILE  또는 운영 PC로 복사 후 열기"
[ -f "$HTML_FILE" ] && echo "    HTML : firefox $HTML_FILE  또는 브라우저로 열기"
[ -f "$DOCX_FILE" ] && echo "    DOCX : libreoffice $DOCX_FILE  또는 MS Word로 열기"
echo ""
