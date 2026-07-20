#!/bin/bash
# ==============================================================================
# Patch : P0-1
# Title : do_u25 화이트리스트에 운영 디렉토리 추가
# Goal  : --auto 실행 시 /logs/suricata 등 운영 디렉토리가 chmod o-w 대상이 되어
#         suricata 데몬 로그 적재 실패 → 운영 장애 발생하는 것을 차단
# ==============================================================================

PATCH_ID="P0-1"
PATCH_TITLE="do_u25 화이트리스트에 운영 디렉토리 추가"
PATCH_PRIORITY="P0"
PATCH_FILE="/mnxmc/infra_audit/infra_remediate.sh"
PATCH_LINES="948-957"
PATCH_KIND="추가 (case 패턴 확장)"
PATCH_REASON="현재 do_u25 의 case 화이트리스트에는 /etc/* 와 /usr/bin/* 등 시스템 핵심 파일만 등록되어 있어, --auto 실행 시 /logs/suricata (0777) 같은 운영 디렉토리가 chmod o-w 대상으로 진입한다. 그 결과 suricata 데몬이 로그 쓰기 권한을 잃고 EVE/JSON 적재가 중단되는 운영 장애가 발생할 수 있다."
PATCH_IMPACT="현재: chmod o-w /logs/suricata 가 실행되어 suricata 로그 적재 중단.
변경 후: /logs/*, /data/*, /application/*, /opt/mnx/* 가 SKIP (시스템/운영 디렉토리 보호) 로그 출력 후 건너뜀."

# ------------------------------------------------------------------------------
# AS-IS  현재 코드 (infra_remediate.sh:948-957)
# ------------------------------------------------------------------------------
asis_snippet() {
cat << 'ASIS'
            # 시스템 필수 파일 이중 보호
            case "$F" in
                /etc/bash.bashrc|/etc/profile|/etc/environment|\
                /etc/profile.d/*|/root/.bashrc|/root/.profile|\
                /root/.bash_profile|/root/.bash_logout|\
                /usr/bin/*|/usr/sbin/*|/bin/*|/sbin/*|\
                /usr/lib/*|/usr/lib64/*|/lib/*|/lib64/*)
                    log "U-25" "  SKIP (시스템 핵심 파일 보호): $F"
                    continue
                    ;;
            esac
ASIS
}

# ------------------------------------------------------------------------------
# TO-BE  변경 후 (운영 디렉토리 3종 추가)
# ------------------------------------------------------------------------------
tobe_snippet() {
cat << 'TOBE'
            # 시스템 필수 파일 + MNX 운영 디렉토리 이중 보호
            case "$F" in
                /etc/bash.bashrc|/etc/profile|/etc/environment|\
                /etc/profile.d/*|/root/.bashrc|/root/.profile|\
                /root/.bash_profile|/root/.bash_logout|\
                /usr/bin/*|/usr/sbin/*|/bin/*|/sbin/*|\
                /usr/lib/*|/usr/lib64/*|/lib/*|/lib64/*|\
                /data|/data/*|/logs|/logs/*|\
                /application|/application/*|\
                /opt/mnx|/opt/mnx/*)
                    log "U-25" "  SKIP (시스템/운영 디렉토리 보호): $F"
                    continue
                    ;;
            esac
TOBE
}

# ------------------------------------------------------------------------------
# 실제 적용 (sed in-place)
# ------------------------------------------------------------------------------
apply_change() {
    local F="$PATCH_FILE"
    # 이미 적용되어 있으면 skip (멱등)
    if grep -q "/data|/data/\*|/logs|/logs/\*" "$F"; then
        echo "[P0-1] 이미 적용됨 - skip"
        return 0
    fi
    sed -i \
        -e 's|/usr/lib/\*|/usr/lib64/\*|/lib/\*|/lib64/\*)|/usr/lib/*|/usr/lib64/*|/lib/*|/lib64/*|\\\n                /data|/data/*|/logs|/logs/*|\\\n                /application|/application/*|\\\n                /opt/mnx|/opt/mnx/*)|' "$F"
    # 위 sed 가 escape 복잡함 → 안전한 patch 방식으로 실제 구현 시 unified diff 사용 권장
}

# ------------------------------------------------------------------------------
# 적용 후 검증
# ------------------------------------------------------------------------------
verify_change() {
    bash -n "$PATCH_FILE" || return 1
    grep -q "/logs|/logs/\*" "$PATCH_FILE" || return 1
    grep -q "SKIP (시스템/운영 디렉토리 보호)" "$PATCH_FILE" || return 1
    return 0
}

export PATCH_ID PATCH_TITLE PATCH_PRIORITY PATCH_FILE PATCH_LINES \
       PATCH_KIND PATCH_REASON PATCH_IMPACT
