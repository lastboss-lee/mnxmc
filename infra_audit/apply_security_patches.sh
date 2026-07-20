#!/bin/bash
# ==============================================================================
# infra_audit / infra_remediate 패치 관리 + 롤백 통합 도구
# 버전 : 0.1.0 (골격 - P0-1 샘플 데이터만 포함)
# 대상 : /mnxmc/infra_audit/infra_audit.sh, infra_remediate.sh
# 기능 : --report  As-Is/To-Be 리포트 생성 (md/pdf/docx/html)
#        --apply   패치 적용 (P0|P1|P2|P3|all 또는 ID 직접 지정)
#        --rollback  세션 단위 롤백 (디렉토리 전체 복원)
#        --list    적용 세션 이력 조회
#        --verify  syntax check + dry-run 검증
# ==============================================================================

set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATCH_DIR="${SCRIPT_DIR}/.patches"
DEF_DIR="${PATCH_DIR}/definitions"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
TS_HUMAN="$(date '+%Y-%m-%d %H:%M:%S %Z')"

# 기존 조직 표준 docx 양식 (pandoc --reference-doc 으로 스타일 상속)
REFERENCE_DOCX="${REFERENCE_DOCX:-/mnxmc/tmp/20241205-audit-report-sample_v1.0.docx}"

if [ "$EUID" -ne 0 ]; then
    echo "[오류] root 권한으로 실행해야 합니다: sudo bash $0 ..."
    exit 1
fi

# ------------------------------------------------------------------------------
# 패치 ID 목록 (definitions/*.patch.sh 자동 로드)
# 현재는 P0-1 만 정의됨. 골격 검증 후 나머지 16건 추가 예정
# ------------------------------------------------------------------------------
declare -a ALL_PATCHES=("P0-1")

# 우선순위별 필터
get_patches_by_priority() {
    local PRIO="$1"
    local -a OUT=()
    for P in "${ALL_PATCHES[@]}"; do
        case "$PRIO" in
            P0|P1|P2|P3) [[ "$P" == ${PRIO}-* ]] && OUT+=("$P") ;;
            all)         OUT+=("$P") ;;
            *)           [[ "$P" == "$PRIO" ]] && OUT+=("$P") ;;
        esac
    done
    printf "%s\n" "${OUT[@]}"
}

# ------------------------------------------------------------------------------
# 환경 점검 (pandoc/xelatex/한글 폰트)
# ------------------------------------------------------------------------------
HAS_PANDOC=false
HAS_XELATEX=false
HAS_KOFONT=false
check_env() {
    command -v pandoc >/dev/null 2>&1 && HAS_PANDOC=true
    command -v xelatex >/dev/null 2>&1 && HAS_XELATEX=true
    fc-list :lang=ko 2>/dev/null | grep -qi "noto\|nanum\|malgun" && HAS_KOFONT=true
}

print_env_status() {
    echo "[환경] pandoc=$($HAS_PANDOC && echo OK || echo X)"
    echo "       xelatex=$($HAS_XELATEX && echo OK || echo X)"
    echo "       한글폰트=$($HAS_KOFONT && echo OK || echo X)"
    if ! $HAS_PANDOC; then
        echo "       [안내] pandoc 미설치 → .md 만 생성됨"
        echo "              설치: apt-get install -y pandoc texlive-xetex fonts-noto-cjk"
    fi
}

# ------------------------------------------------------------------------------
# 패치 정의 로드 (definitions/PATCH_ID.patch.sh)
# 각 .patch.sh 는 다음 변수/함수를 export 해야 함:
#   PATCH_ID, PATCH_TITLE, PATCH_PRIORITY, PATCH_FILE, PATCH_LINES,
#   PATCH_REASON, PATCH_IMPACT
#   asis_snippet()    AS-IS 현재 코드 출력
#   tobe_snippet()    TO-BE 변경 후 코드 출력
#   apply_change()    실제 적용 (sed/awk/patch)
#   verify_change()   적용 후 검증 (정상=0, 실패=1)
# ------------------------------------------------------------------------------
load_patch() {
    local PID="$1"
    local DEF="${DEF_DIR}/${PID}.patch.sh"
    if [ ! -f "$DEF" ]; then
        echo "[오류] 패치 정의 없음: $DEF" >&2
        return 1
    fi
    # shellcheck disable=SC1090
    source "$DEF"
}

# ------------------------------------------------------------------------------
# Markdown 리포트 생성 (A4 80자 폭)
# ------------------------------------------------------------------------------
gen_report_md() {
    local OUT="$1"; shift
    local -a PIDS=("$@")
    local HOST OS KERN
    HOST=$(hostname)
    OS=$(grep PRETTY_NAME /etc/os-release 2>/dev/null | cut -d'"' -f2)
    KERN=$(uname -r)

    {
    cat << HEADER
---
title: "MNX 보안 패치 As-Is / To-Be 리포트"
date: "${TS_HUMAN}"
geometry: a4paper,margin=2cm
mainfont: "Noto Sans CJK KR"
monofont: "Noto Sans Mono CJK KR"
fontsize: 10pt
---

# MNX 보안 패치 검토 리포트

| 항목       | 값                                  |
|------------|-------------------------------------|
| 생성 시각  | ${TS_HUMAN}                         |
| 호스트     | ${HOST}                             |
| OS         | ${OS}                               |
| 커널       | ${KERN}                             |
| 대상 패치  | ${#PIDS[@]} 건                       |
| 세션 ID    | ${TIMESTAMP}                         |

## 패치 요약

| ID    | 우선순위 | 대상 파일                | 제목                                |
|-------|----------|--------------------------|-------------------------------------|
HEADER

    for PID in "${PIDS[@]}"; do
        load_patch "$PID" || continue
        printf "| %-5s | %-8s | %-24s | %-35s |\n" \
            "$PATCH_ID" "$PATCH_PRIORITY" "$(basename "$PATCH_FILE")" "$PATCH_TITLE"
    done

    echo ""
    echo "---"
    echo ""

    for PID in "${PIDS[@]}"; do
        load_patch "$PID" || continue
        cat << ITEM_HEAD

## [${PATCH_ID}] ${PATCH_TITLE}

| 속성        | 값                                       |
|-------------|------------------------------------------|
| 대상 파일   | \`${PATCH_FILE}\`                        |
| 영향 라인   | ${PATCH_LINES}                           |
| 우선순위    | ${PATCH_PRIORITY}                        |
| 변경 분류   | ${PATCH_KIND:-수정}                      |

### 적용 사유

${PATCH_REASON}

### 예상 동작 변화

${PATCH_IMPACT}

### AS-IS (현재 코드)

\`\`\`bash
$(asis_snippet)
\`\`\`

### TO-BE (변경 후)

\`\`\`bash
$(tobe_snippet)
\`\`\`

### Unified Diff

\`\`\`diff
$(diff -u <(asis_snippet) <(tobe_snippet) | sed '1,2d' || true)
\`\`\`

### 적용 후 검증

\`\`\`bash
bash -n ${PATCH_FILE}
$(declare -f verify_change | sed -n '/^{/,/^}/p' | sed '1d;$d' | head -5)
\`\`\`

---
ITEM_HEAD
    done

    cat << FOOTER

## 롤백 안내

본 리포트의 패치를 적용한 후 문제가 발생하면 다음 명령으로 전체 복구:

\`\`\`bash
sudo bash ${SCRIPT_DIR}/apply_security_patches.sh --rollback ${TIMESTAMP}
\`\`\`

snapshot.tar.gz 는 \`${SCRIPT_DIR}/.patches/<세션>/snapshot.tar.gz\` 에 저장되며
\`/mnxmc/infra_audit/\` 디렉토리 전체와 권한/소유자/SHA256 메타데이터를 포함합니다.

FOOTER
    } > "$OUT"
}

# ------------------------------------------------------------------------------
# Markdown → PDF / DOCX / HTML 변환
# ------------------------------------------------------------------------------
convert_report() {
    local MD="$1"
    local BASE="${MD%.md}"

    if ! $HAS_PANDOC; then
        echo "[안내] pandoc 미설치 - .md 만 생성됨: $MD"
        echo "       변환 수동 명령:"
        echo "         pandoc $MD -o ${BASE}.pdf --pdf-engine=xelatex -V CJKmainfont='Noto Sans CJK KR'"
        echo "         pandoc $MD -o ${BASE}.docx"
        echo "         pandoc $MD -o ${BASE}.html --standalone"
        return 0
    fi

    # HTML (의존성 가장 적음)
    pandoc "$MD" -o "${BASE}.html" --standalone --metadata title="MNX 보안 패치 리포트" 2>/dev/null \
        && echo "[변환] HTML  → ${BASE}.html"

    # DOCX (기존 양식 스타일 상속)
    if [ -f "$REFERENCE_DOCX" ]; then
        pandoc "$MD" -o "${BASE}.docx" --reference-doc="$REFERENCE_DOCX" 2>/dev/null \
            && echo "[변환] DOCX  → ${BASE}.docx (reference: $(basename "$REFERENCE_DOCX"))"
    else
        pandoc "$MD" -o "${BASE}.docx" 2>/dev/null \
            && echo "[변환] DOCX  → ${BASE}.docx (기본 스타일)"
    fi

    # PDF (xelatex + 한글 폰트 필요)
    if $HAS_XELATEX && $HAS_KOFONT; then
        pandoc "$MD" -o "${BASE}.pdf" \
            --pdf-engine=xelatex \
            -V geometry:a4paper,margin=2cm \
            -V CJKmainfont="Noto Sans CJK KR" \
            -V monofont="Noto Sans Mono CJK KR" 2>/dev/null \
            && echo "[변환] PDF   → ${BASE}.pdf"
    else
        echo "[안내] PDF 변환 skip (xelatex=$HAS_XELATEX, 한글폰트=$HAS_KOFONT)"
    fi
}

# ------------------------------------------------------------------------------
# 스냅샷 백업 (디렉토리 전체 - 옵션 B)
# ------------------------------------------------------------------------------
backup_snapshot() {
    local SESSION_DIR="$1"
    local META="${SESSION_DIR}/.meta"
    mkdir -p "$META"

    # 파일 권한/소유자/inode/SHA256 메타데이터
    {
        echo "# Generated: ${TS_HUMAN}"
        echo "# Script   : $0"
        echo "# User     : $(whoami)"
        echo "# PWD      : $(pwd)"
        echo "# OS       : $(grep PRETTY_NAME /etc/os-release | cut -d'"' -f2)"
    } > "${META}/env.txt"

    find "${SCRIPT_DIR}" -maxdepth 1 -type f \
        \( -name "*.sh" -o -name "*.txt" -o -name "*.pdf" \) \
        -printf '%m %u:%g %i %p\n' > "${META}/file_perms.txt"

    sha256sum "${SCRIPT_DIR}"/*.sh "${SCRIPT_DIR}"/*.pdf 2>/dev/null > "${META}/sha256.txt"

    # 디렉토리 전체 tarball (.patches 자체는 제외하여 무한 백업 방지)
    tar -czf "${SESSION_DIR}/snapshot.tar.gz" \
        --exclude="${SCRIPT_DIR}/.patches" \
        -C "$(dirname "$SCRIPT_DIR")" "$(basename "$SCRIPT_DIR")" 2>/dev/null

    chmod 600 "${SESSION_DIR}/snapshot.tar.gz"
    chmod 700 "$SESSION_DIR"
    echo "[백업] snapshot.tar.gz ($(du -h "${SESSION_DIR}/snapshot.tar.gz" | cut -f1))"
}

# ------------------------------------------------------------------------------
# MANIFEST 작성
# ------------------------------------------------------------------------------
write_manifest() {
    local SESSION_DIR="$1"; shift
    local STATUS="$1"; shift
    local -a PIDS=("$@")
    {
        echo "# MANIFEST"
        echo "session_id    : ${TIMESTAMP}"
        echo "timestamp     : ${TS_HUMAN}"
        echo "user          : $(whoami)"
        echo "status        : ${STATUS}"
        echo "patches       : ${PIDS[*]}"
        echo "script_dir    : ${SCRIPT_DIR}"
        echo "snapshot_sha  : $(sha256sum "${SESSION_DIR}/snapshot.tar.gz" 2>/dev/null | awk '{print $1}')"
        echo "applied_files :"
        for PID in "${PIDS[@]}"; do
            load_patch "$PID" 2>/dev/null || continue
            echo "  - ${PATCH_ID} : ${PATCH_FILE}"
        done
    } >> "${SESSION_DIR}/MANIFEST.txt"
}

# ------------------------------------------------------------------------------
# Sub-command : --report (변경 없이 리포트만)
# ------------------------------------------------------------------------------
cmd_report() {
    local PRIO="${1:-all}"
    local -a PIDS
    mapfile -t PIDS < <(get_patches_by_priority "$PRIO")
    if [ ${#PIDS[@]} -eq 0 ]; then
        echo "[오류] 매칭되는 패치 없음: $PRIO"
        exit 1
    fi

    local OUT_DIR="${PATCH_DIR}/${TIMESTAMP}_report"
    mkdir -p "$OUT_DIR"
    chmod 700 "$OUT_DIR"

    local MD="${OUT_DIR}/report.md"
    echo "[생성] $MD (대상 패치: ${PIDS[*]})"
    gen_report_md "$MD" "${PIDS[@]}"
    chmod 600 "$MD"

    convert_report "$MD"

    echo ""
    echo "[완료] 리포트 디렉토리: $OUT_DIR"
    ls -la "$OUT_DIR"
}

# ------------------------------------------------------------------------------
# Sub-command : --apply (실제 적용 - 골격에서는 미구현, 안내만)
# ------------------------------------------------------------------------------
cmd_apply() {
    echo "[안내] 골격 버전에서는 --apply 미지원 (P0-1 샘플만 포함)"
    echo "       실제 적용 기능은 사용자 리포트 검토 후 구현 예정"
}

# ------------------------------------------------------------------------------
# Sub-command : --rollback (골격 - 안내만)
# ------------------------------------------------------------------------------
cmd_rollback() {
    echo "[안내] 롤백 절차 (정식 구현 예정):"
    echo "  1. ${PATCH_DIR}/<세션>/snapshot.tar.gz 검증 (SHA256)"
    echo "  2. ${SCRIPT_DIR} 현재 상태 임시 백업"
    echo "  3. snapshot.tar.gz 풀어서 디렉토리 전체 복원"
    echo "  4. 권한/소유자 .meta/file_perms.txt 기준으로 복원"
    echo "  5. MANIFEST 에 ROLLBACK 마커 append"
}

# ------------------------------------------------------------------------------
# Sub-command : --list
# ------------------------------------------------------------------------------
cmd_list() {
    if [ ! -d "$PATCH_DIR" ]; then
        echo "(적용 이력 없음)"
        return
    fi
    echo "[적용/리포트 세션 이력]"
    find "$PATCH_DIR" -maxdepth 1 -mindepth 1 -type d -printf "%f\n" 2>/dev/null \
        | sort | while read -r S; do
            local M="${PATCH_DIR}/${S}/MANIFEST.txt"
            if [ -f "$M" ]; then
                local ST PT
                ST=$(grep "^status" "$M" | cut -d: -f2 | tr -d ' ')
                PT=$(grep "^patches" "$M" | cut -d: -f2)
                printf "  %s  status=%s patches=%s\n" "$S" "${ST:-?}" "${PT:-?}"
            else
                printf "  %s  (MANIFEST 없음)\n" "$S"
            fi
        done
}

# ------------------------------------------------------------------------------
# Sub-command : --verify
# ------------------------------------------------------------------------------
cmd_verify() {
    echo "[검증] bash -n syntax check"
    for F in "${SCRIPT_DIR}/infra_audit.sh" "${SCRIPT_DIR}/infra_remediate.sh"; do
        if bash -n "$F" 2>/dev/null; then
            echo "  OK : $F"
        else
            echo "  FAIL: $F"
        fi
    done
}

# ------------------------------------------------------------------------------
# 사용법
# ------------------------------------------------------------------------------
usage() {
    cat << USAGE
사용법: sudo bash $0 <command> [args]

  --report  [PRIO|ID|all]  As-Is/To-Be 리포트 생성 (변경 없음, 기본=all)
  --apply   [PRIO|ID|all]  패치 적용 (현 골격에선 미구현)
  --rollback [SESSION_ID]  세션 단위 디렉토리 전체 복원
  --list                   적용/리포트 세션 이력 조회
  --verify                 대상 스크립트 syntax check
  --env                    환경(pandoc/xelatex/한글폰트) 점검

예시:
  sudo bash $0 --env
  sudo bash $0 --report P0
  sudo bash $0 --report P0-1
  sudo bash $0 --list

현재 정의된 패치: ${ALL_PATCHES[*]}
USAGE
}

# ==============================================================================
# Dispatcher
# ==============================================================================
check_env
case "${1:-}" in
    --report)   shift; cmd_report "${1:-all}" ;;
    --apply)    shift; cmd_apply "${1:-all}" ;;
    --rollback) shift; cmd_rollback "${1:-}" ;;
    --list)     cmd_list ;;
    --verify)   cmd_verify ;;
    --env)      print_env_status ;;
    -h|--help|"") usage ;;
    *)          echo "[오류] 알 수 없는 명령: $1"; usage; exit 1 ;;
esac
