#!/bin/bash
set -uo pipefail

############################################
# CONFIG - 인터페이스 중복 허용 (v18)
############################################
# 같은 인터페이스에 여러 PCAP을 다른 설정으로 전송 가능
# 배열 인덱스가 일치해야 함
#
# 예시 1: 기존 방식 (인터페이스당 1개 PCAP)
#   IFACES=("eno12399" "eno12409")
#   PCAPS=("/path/to/a.pcap" "/path/to/b.pcap")
#   TARGET_MBPS=(4500 4500)
#   REPLAY_COUNT=(10 10)
#
# 예시 2: 확장 방식 (한 인터페이스에 여러 PCAP)
#   IFACES=("eno12399" "eno12399" "eno12399" "eno12409")
#   PCAPS=("/path/file1.pcap" "/path/file2.pcap" "/path/file3.pcap" "/path/file4.pcap")
#   TARGET_MBPS=(500 2000 2000 4500)
#   REPLAY_COUNT=(2 4 4 10)
#   → eno12399: 3개 PCAP, 총 10개 프로세스, 목표 4500 Mbps
#   → eno12409: 1개 PCAP, 총 10개 프로세스, 목표 4500 Mbps

IFACES=("eno12399" "eno12399" "eno12409" "eno12409" "eno12409")
PCAPS=(
  "/home/sands/download/file_download.pcap"
  "/home/sands/download/bigFlows.pcap"
  "/home/sands/download/file_download.pcap"
  "/home/sands/download/dk-8fj8b44-250401-00034969.pcap"
  "/home/sands/download/http-simple-get.pcap"
)
TARGET_MBPS=(6000 3000 5000 2000 2000)
REPLAY_COUNT=(6 5 6 3 3)           # 각 항목별 프로세스 수 (배열)
RATE_CORRECTIONS=(1.0 1.0 1.0 1.0 1.0)
USE_UNIQUE_IP=("no" "no" "no" "no" "no")

REFRESH_INTERVAL=1

# Screen 세션 이름 접두사
SCREEN_PREFIX="rstreplay"

# 속도 제어 모드 (RATE_MODE)
# "pps" = --pps 옵션 (권장, 정확한 제어)
# "mbps" = --mbps 옵션 (대략적 제어)
RATE_MODE="pps"

# CPU Affinity 설정 (빈 배열 = 자동 할당)
CPU_CORES=()

# PPS 참조 테이블용 Gbps 목표값
GBPS_REFS=(1 5 8 10)

############################################
# AUTO_RESTART 설정
############################################
AUTO_RESTART_ENABLED="yes"
AUTO_RESTART_THRESHOLD=7     # 15% 이상 오차 시 감지
AUTO_RESTART_DURATION=300      # 5분 지속 시 재시작
MAX_UPTIME_SECONDS=43200       # 12시간 후 강제 재시작 (0=비활성화)

############################################
# COLORS (ANSI Escape Codes)
############################################
C_CYAN='\033[1;36m'
C_GREEN='\033[1;32m'
C_YELLOW='\033[1;33m'
C_RED='\033[1;31m'
C_GRAY='\033[0;37m'
C_WHITE='\033[1;37m'
C_RESET='\033[0m'

############################################
# FUNCTIONS
############################################

# 세션 이름: prefix_interface_jobidx_procnum
get_session_name() {
    local iface="$1"
    local job_idx="$2"
    local proc_num="$3"
    echo "${SCREEN_PREFIX}_${iface}_j${job_idx}_${proc_num}"
}

get_session_pattern() {
    echo "${SCREEN_PREFIX}_"
}

calc_avg_pkt() {
    local pcap="$1"
    if command -v capinfos &>/dev/null; then
        capinfos -z "$pcap" 2>/dev/null | awk '/Average packet size:/ {print $4}'
    else
        tcpdump -r "$pcap" -n -q 2>/dev/null | \
            awk '{sum+=$NF; cnt++} END {if(cnt>0) printf "%.2f", sum/cnt; else print "0.00"}'
    fi
}

format_number() {
    local num="$1"
    num=${num%%.*}
    printf "%'d" "$num" 2>/dev/null || printf "%d" "$num"
}

format_pps_short() {
    local pps="$1"
    pps=${pps%%.*}
    if ((pps >= 1000000)); then
        printf "%.1fM" "$(echo "scale=1; $pps / 1000000" | bc)"
    elif ((pps >= 1000)); then
        printf "%.0fK" "$(echo "scale=0; $pps / 1000" | bc)"
    else
        printf "%d" "$pps"
    fi
}

format_duration() {
    local secs="$1"
    printf "%02d:%02d:%02d" $((secs/3600)) $((secs%3600/60)) $((secs%60))
}

calc_required_pps() {
    local gbps="$1"
    local avg_pkt="$2"
    echo "scale=0; ($gbps * 1000000000) / ($avg_pkt * 8)" | bc
}

kill_all_replay() {
    local pattern
    pattern=$(get_session_pattern)
    echo "[INFO] Stopping all replay sessions (${pattern}*)..."
    
    for session in $(screen -ls 2>/dev/null | awk "/${pattern}/ {print \$1}"); do
        screen -X -S "$session" quit 2>/dev/null || true
    done
    pkill -9 tcpreplay 2>/dev/null || true
    sleep 1
}

read_stat() {
    local file="$1"
    local default="$2"
    [[ -r "$file" ]] && cat "$file" 2>/dev/null || echo "$default"
}

pl() {
    printf "%b" "$1"
    tput el 2>/dev/null
    printf "\n"
}

get_tcpreplay_cpu() {
    ps -C tcpreplay -o %cpu= 2>/dev/null | awk '{sum+=$1} END {printf "%.1f", sum}' || echo "0.0"
}

get_softnet_drops() {
    awk '{sum += strtonum("0x"$2)} END {print sum}' /proc/net/softnet_stat 2>/dev/null || echo "0"
}

get_softnet_squeeze() {
    awk '{sum += strtonum("0x"$3)} END {print sum}' /proc/net/softnet_stat 2>/dev/null || echo "0"
}

get_tx_errors() {
    read_stat "/sys/class/net/$1/statistics/tx_errors" 0
}

get_tx_dropped() {
    read_stat "/sys/class/net/$1/statistics/tx_dropped" 0
}

############################################
# 고유 인터페이스 목록 추출
############################################
get_unique_ifaces() {
    printf '%s\n' "${IFACES[@]}" | sort -u
}

############################################
# START REPLAY FUNCTION
############################################
start_replay_sessions() {
    echo "[INFO] Disabling NIC offloads..."
    for iface in $(get_unique_ifaces); do
        ethtool -K "$iface" gro off lro off tso off gso off rx off tx off 2>/dev/null || true
    done

    kill_all_replay

    echo "[INFO] Starting tcpreplay sessions with CPU affinity (mode: ${RATE_MODE})..."
    local cpu_idx=0
    local started_count=0
    
    for idx in "${!IFACES[@]}"; do
        local iface="${IFACES[$idx]}"
        local pcap="${PCAPS[$idx]}"
        local pcap_name="${pcap##*/}"
        local total_mbps="${TARGET_MBPS[$idx]}"
        local count="${REPLAY_COUNT[$idx]}"
        local req_pps_adj="${REQ_PPS_ADJ_ARR[$idx]}"
        local correction="${RATE_CORRECTIONS[$idx]}"
        local use_unique="${USE_UNIQUE_IP[$idx]}"
        local rate_opt rate_unit per_rate unique_opt
        
        if [[ "$RATE_MODE" == "pps" ]]; then
            per_rate=$(( req_pps_adj / count ))
            rate_opt="--pps=$per_rate"
            rate_unit="PPS"
        else
            per_rate=$(echo "scale=0; ($total_mbps * $correction) / $count" | bc | cut -d'.' -f1)
            rate_opt="--mbps=$per_rate"
            rate_unit="Mbps"
        fi
        
        if [[ "$use_unique" == "yes" ]]; then
            unique_opt="--unique-ip"
        else
            unique_opt=""
        fi
        
        echo "  [Job $idx] $iface ← $pcap_name (${count}개, $total_mbps Mbps)"
        
        for n in $(seq 1 "$count"); do
            local session_name
            session_name=$(get_session_name "$iface" "$idx" "$n")
            local cpu_core="${CPU_CORES[$cpu_idx]}"
            
            if screen -dmS "$session_name" taskset -c "$cpu_core" tcpreplay \
                $rate_opt -i "$iface" -l 0 $unique_opt "$pcap"; then
                echo "    Started: $session_name ($per_rate $rate_unit) → CPU $cpu_core"
                ((started_count++))
            else
                echo "    [WARN] Failed to start: $session_name"
            fi
            ((cpu_idx++))
            sleep 0.1
        done
    done
    
    echo "[INFO] Started $started_count / $TOTAL_REPLAY tcpreplay processes"
    sleep 2
    
    local running_procs
    running_procs=$(pgrep -x tcpreplay 2>/dev/null | wc -l || echo 0)
    echo "[INFO] Running tcpreplay processes: $running_procs"
}

############################################
# PRECHECK
############################################
[[ "$EUID" -ne 0 ]] && { echo "[ERROR] run as root"; exit 1; }

for cmd in tcpreplay tcpdump screen ethtool bc taskset; do
    command -v "$cmd" &>/dev/null || { echo "[ERROR] $cmd not found"; exit 1; }
done

# 배열 길이 검증
arr_len=${#IFACES[@]}
[[ ${#PCAPS[@]} -ne $arr_len ]] && { echo "[ERROR] PCAPS array length mismatch"; exit 1; }
[[ ${#TARGET_MBPS[@]} -ne $arr_len ]] && { echo "[ERROR] TARGET_MBPS array length mismatch"; exit 1; }
[[ ${#REPLAY_COUNT[@]} -ne $arr_len ]] && { echo "[ERROR] REPLAY_COUNT array length mismatch"; exit 1; }
[[ ${#RATE_CORRECTIONS[@]} -ne $arr_len ]] && { echo "[ERROR] RATE_CORRECTIONS array length mismatch"; exit 1; }
[[ ${#USE_UNIQUE_IP[@]} -ne $arr_len ]] && { echo "[ERROR] USE_UNIQUE_IP array length mismatch"; exit 1; }

for pcap in "${PCAPS[@]}"; do
    [[ -f "$pcap" ]] || { echo "[ERROR] PCAP not found: $pcap"; exit 1; }
done

for iface in $(get_unique_ifaces); do
    [[ -d "/sys/class/net/$iface" ]] || { echo "[ERROR] Interface not found: $iface"; exit 1; }
done

if [[ "$RATE_MODE" != "mbps" && "$RATE_MODE" != "pps" ]]; then
    echo "[ERROR] RATE_MODE must be 'mbps' or 'pps'"
    exit 1
fi

############################################
# 총 프로세스 수 계산
############################################
TOTAL_REPLAY=0
for cnt in "${REPLAY_COUNT[@]}"; do
    ((TOTAL_REPLAY += cnt))
done

############################################
# 인터페이스별 합산 정보 계산
############################################
declare -A IFACE_TARGET_MBPS    # 인터페이스별 총 목표 Mbps
declare -A IFACE_TOTAL_PROCS    # 인터페이스별 총 프로세스 수
declare -A IFACE_REQ_PPS        # 인터페이스별 총 필요 PPS
declare -A IFACE_RATIO          # 인터페이스별 달성률 (권장값 계산용)
declare -A IFACE_ACTUAL_MBPS    # 인터페이스별 실제 Mbps

for iface in $(get_unique_ifaces); do
    IFACE_TARGET_MBPS[$iface]=0
    IFACE_TOTAL_PROCS[$iface]=0
    IFACE_REQ_PPS[$iface]=0
done

############################################
# MODE SELECTION
############################################
running_count=$(pgrep -x tcpreplay 2>/dev/null | wc -l || echo 0)

echo ""
echo "=========================================="
echo "  tcpreplay Console v18 - Mode Selection"
echo "=========================================="
echo "  현재 실행 중인 tcpreplay: ${running_count}개"
echo ""
echo "  [1] 신규 시작 (Start New)"
echo "      - 기존 tcpreplay 모두 종료"
echo "      - 새로운 replay 세션 시작"
echo ""
echo "  [2] 모니터링 (Monitor Only)"
echo "      - 기존 tcpreplay 유지"
echo "      - 콘솔 모니터링만 실행"
echo ""
echo "  [q] 종료 (Quit)"
echo ""
echo "=========================================="

while true; do
    read -rp "선택 [1/2/q]: " mode_choice
    case "$mode_choice" in
        1)
            RUN_MODE="start"
            echo "[INFO] 신규 시작 모드 선택"
            break
            ;;
        2)
            RUN_MODE="monitor"
            echo "[INFO] 모니터링 모드 선택"
            if [[ $running_count -eq 0 ]]; then
                echo "[WARN] 실행 중인 tcpreplay가 없습니다!"
                read -rp "계속하시겠습니까? [y/N]: " cont
                [[ "$cont" != "y" && "$cont" != "Y" ]] && exit 0
            fi
            break
            ;;
        q|Q)
            echo "[INFO] 종료"
            exit 0
            ;;
        *)
            echo "[ERROR] 잘못된 선택. 1, 2, 또는 q를 입력하세요."
            ;;
    esac
done

echo ""

TOTAL_CPUS=$(nproc)

echo "[INFO] System has $TOTAL_CPUS CPU cores"
echo "[INFO] Total jobs: ${#IFACES[@]}, Total processes: $TOTAL_REPLAY"
echo "[INFO] Screen prefix: ${SCREEN_PREFIX}"
echo "[INFO] Rate mode: ${RATE_MODE}"
echo "[INFO] Auto-restart: ${AUTO_RESTART_ENABLED} (threshold: ${AUTO_RESTART_THRESHOLD}%, duration: ${AUTO_RESTART_DURATION}s)"
[[ $MAX_UPTIME_SECONDS -gt 0 ]] && echo "[INFO] Max uptime: $(format_duration $MAX_UPTIME_SECONDS)"

if [[ ${#CPU_CORES[@]} -eq 0 ]]; then
    start_core=$((TOTAL_CPUS - TOTAL_REPLAY))
    ((start_core < 0)) && start_core=0
    for i in $(seq 0 $((TOTAL_REPLAY - 1))); do
        CPU_CORES+=($((start_core + i)))
    done
    echo "[INFO] Auto-assigned CPU cores: ${CPU_CORES[*]}"
else
    echo "[INFO] Using specified CPU cores: ${CPU_CORES[*]}"
fi

# START_TS 설정
if [[ "$RUN_MODE" == "monitor" ]]; then
    oldest_session_time=$(screen -ls 2>/dev/null | grep "${SCREEN_PREFIX}_" | \
        awk -F'[()]' '{print $2}' | head -1)
    
    if [[ -n "$oldest_session_time" ]]; then
        START_TS=$(date -d "$oldest_session_time" +%s 2>/dev/null || date +%s)
        echo "[INFO] Session start time: $oldest_session_time"
    else
        START_TS=$(date +%s)
    fi
else
    START_TS=$(date +%s)
fi

############################################
# TTY STATE MANAGEMENT
############################################
TTY_STATE=$(stty -g 2>/dev/null || echo "")
CURSOR_HIDDEN=false

cleanup() {
    clear 2>/dev/null || true
    [[ "$CURSOR_HIDDEN" == true ]] && tput cnorm 2>/dev/null
    if [[ -n "$TTY_STATE" ]]; then
        stty "$TTY_STATE" 2>/dev/null
    else
        stty sane 2>/dev/null
    fi
    tput sgr0 2>/dev/null
}

trap cleanup EXIT
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM

############################################
# PRE-CALC AVG PACKET SIZE & REQ_PPS
############################################
echo "[INFO] Calculating average packet sizes..."
AVG_PKT_SIZES=()
REQ_PPS_ARR=()
REQ_PPS_ADJ_ARR=()
declare -A PPS_REF_TABLE

for idx in "${!IFACES[@]}"; do
    iface="${IFACES[$idx]}"
    pcap="${PCAPS[$idx]}"
    pcap_name="${pcap##*/}"
    avg=$(calc_avg_pkt "$pcap")
    AVG_PKT_SIZES+=("${avg:-0.00}")
    
    target="${TARGET_MBPS[$idx]}"
    correction="${RATE_CORRECTIONS[$idx]}"
    count="${REPLAY_COUNT[$idx]}"
    
    if (( $(echo "$avg > 0" | bc -l) )); then
        req_pps=$(echo "scale=0; $target * 1000000 / ($avg * 8)" | bc)
        req_pps_adj=$(echo "scale=0; ($req_pps * $correction) / 1" | bc)
    else
        req_pps=0
        req_pps_adj=0
    fi
    REQ_PPS_ARR+=("$req_pps")
    REQ_PPS_ADJ_ARR+=("$req_pps_adj")
    
    # 인터페이스별 합산
    IFACE_TARGET_MBPS[$iface]=$((${IFACE_TARGET_MBPS[$iface]} + target))
    IFACE_TOTAL_PROCS[$iface]=$((${IFACE_TOTAL_PROCS[$iface]} + count))
    IFACE_REQ_PPS[$iface]=$((${IFACE_REQ_PPS[$iface]} + req_pps))
    
    # PPS 참조 테이블 (첫 번째 항목만)
    if [[ -z "${PPS_REF_TABLE[$iface]:-}" ]]; then
        pps_ref=""
        for g in "${GBPS_REFS[@]}"; do
            needed=$(calc_required_pps "$g" "$avg")
            formatted=$(format_pps_short "$needed")
            [[ -n "$pps_ref" ]] && pps_ref+=" | "
            pps_ref+="${g}G→${formatted}"
        done
        PPS_REF_TABLE[$iface]="$pps_ref"
    fi
    
    printf "  [Job %d] %s ← %s\n" "$idx" "$iface" "$pcap_name"
    printf "          %s bytes, %d Mbps × %.2f = %d Mbps, %d procs\n" \
        "${AVG_PKT_SIZES[$idx]}" "$target" "$correction" \
        "$(echo "$target * $correction" | bc | cut -d'.' -f1)" "$count"
    printf "          → %s PPS (adj: %s PPS)\n" \
        "$(format_number $req_pps)" "$(format_number $req_pps_adj)"
done

echo ""
echo "[INFO] Interface Summary:"
for iface in $(get_unique_ifaces); do
    echo "  $iface: ${IFACE_TOTAL_PROCS[$iface]} procs, ${IFACE_TARGET_MBPS[$iface]} Mbps target"
done

############################################
# START MODE: START REPLAY
############################################
if [[ "$RUN_MODE" == "start" ]]; then
    start_replay_sessions
fi

############################################
# INITIAL STAT VALUES
############################################
declare -A TXP_PREV TXB_PREV TXP_NOW TXB_NOW
declare -A TX_ERR_PREV TX_ERR_NOW TX_DROP_PREV TX_DROP_NOW

for iface in $(get_unique_ifaces); do
    TXP_PREV[$iface]=$(read_stat "/sys/class/net/$iface/statistics/tx_packets" 0)
    TXB_PREV[$iface]=$(read_stat "/sys/class/net/$iface/statistics/tx_bytes" 0)
    TX_ERR_PREV[$iface]=$(get_tx_errors "$iface")
    TX_DROP_PREV[$iface]=$(get_tx_dropped "$iface")
done

SOFTNET_DROP_PREV=$(get_softnet_drops)
SOFTNET_SQUEEZE_PREV=$(get_softnet_squeeze)

PREV_MEASURE_TS=$(date +%s.%N)

sleep "$REFRESH_INTERVAL"

############################################
# AUTO_RESTART STATE VARIABLES
############################################
DRIFT_DETECTED=false
DRIFT_START_TIME=0
RESTART_COUNT=0

############################################
# UNIQUE INTERFACES ARRAY
############################################
UNIQUE_IFACES=($(get_unique_ifaces))

############################################
# MAIN LOOP
############################################
clear
tput civis 2>/dev/null && CURSOR_HIDDEN=true

while true; do
    tput cup 0 0 2>/dev/null

    # 키 입력 처리
    if read -rsn1 -t "$REFRESH_INTERVAL" key 2>/dev/null; then
        case "$key" in
            q|Q)
                if [[ "$RUN_MODE" == "start" ]]; then
                    kill_all_replay
                    echo "[INFO] Replay stopped by user"
                else
                    echo "[INFO] Exiting monitor mode (replay continues)"
                fi
                exit 0
                ;;
            s|S)
                if [[ "$RUN_MODE" == "monitor" ]]; then
                    kill_all_replay
                    echo "[INFO] Replay stopped by user"
                    exit 0
                fi
                ;;
        esac
    fi

    # 현재 시간 측정
    CURR_MEASURE_TS=$(date +%s.%N)
    ACTUAL_INTERVAL=$(echo "$CURR_MEASURE_TS - $PREV_MEASURE_TS" | bc)

    # 통계 수집
    for iface in "${UNIQUE_IFACES[@]}"; do
        TXP_NOW[$iface]=$(read_stat "/sys/class/net/$iface/statistics/tx_packets" 0)
        TXB_NOW[$iface]=$(read_stat "/sys/class/net/$iface/statistics/tx_bytes" 0)
        TX_ERR_NOW[$iface]=$(get_tx_errors "$iface")
        TX_DROP_NOW[$iface]=$(get_tx_dropped "$iface")
    done

    SOFTNET_DROP_NOW=$(get_softnet_drops)
    SOFTNET_SQUEEZE_NOW=$(get_softnet_squeeze)
    SOFTNET_DROP_DELTA=$((SOFTNET_DROP_NOW - SOFTNET_DROP_PREV))
    SOFTNET_SQUEEZE_DELTA=$((SOFTNET_SQUEEZE_NOW - SOFTNET_SQUEEZE_PREV))
    ((SOFTNET_DROP_DELTA < 0)) && SOFTNET_DROP_DELTA=0
    ((SOFTNET_SQUEEZE_DELTA < 0)) && SOFTNET_SQUEEZE_DELTA=0

    TCPREPLAY_CPU=$(get_tcpreplay_cpu)
    total_procs=$(pgrep -x tcpreplay 2>/dev/null | wc -l || echo 0)

    now_ts=$(date +%s)
    elapsed=$((now_ts - START_TS))
    elapsed_fmt=$(format_duration $elapsed)

    # MAX_UPTIME 체크
    max_uptime_status=""
    if [[ $MAX_UPTIME_SECONDS -gt 0 ]]; then
        remaining=$((MAX_UPTIME_SECONDS - elapsed))
        if ((remaining <= 0)); then
            pl ""
            pl "${C_YELLOW}[AUTO] MAX_UPTIME ($(format_duration $MAX_UPTIME_SECONDS)) reached. Auto-restarting...${C_RESET}"
            start_replay_sessions
            START_TS=$(date +%s)
            RESTART_COUNT=$((RESTART_COUNT + 1))
            DRIFT_DETECTED=false
            DRIFT_START_TIME=0
            
            for iface in "${UNIQUE_IFACES[@]}"; do
                TXP_PREV[$iface]=$(read_stat "/sys/class/net/$iface/statistics/tx_packets" 0)
                TXB_PREV[$iface]=$(read_stat "/sys/class/net/$iface/statistics/tx_bytes" 0)
            done
            PREV_MEASURE_TS=$(date +%s.%N)
            sleep "$REFRESH_INTERVAL"
            continue
        elif ((remaining <= 600)); then
            max_uptime_status=" | ${C_YELLOW}Restart in $(format_duration $remaining)${C_RESET}"
        fi
    fi

    # 모드 표시
    if [[ "$RUN_MODE" == "start" ]]; then
        mode_label="Start (신규 시작)"
    else
        mode_label="Monitor (모니터링)"
    fi

    # 헤더 출력
    pl "${C_CYAN}================================= Replay Control Console v18 =================================${C_RESET}"
    pl " Time    : $(date '+%Y-%m-%d %H:%M:%S')"
    
    restart_info=""
    [[ $RESTART_COUNT -gt 0 ]] && restart_info=" (restarts: $RESTART_COUNT)"
    pl " Uptime  : ${elapsed_fmt}${restart_info}  [${mode_label}]${max_uptime_status}"
    
    pl " Procs   : $total_procs tcpreplay (CPU: ${TCPREPLAY_CPU}%)"
    pl " Jobs    : ${#IFACES[@]} jobs, ${#UNIQUE_IFACES[@]} interfaces"
    [[ "$RATE_MODE" == "pps" ]] && pl " Mode    : ${C_GREEN}pps${C_RESET} (정확한 PPS 제어)" || pl " Mode    : ${C_YELLOW}mbps${C_RESET} (대략적 Mbps 제어)"
    
    # AUTO_RESTART 상태 표시
    if [[ "$AUTO_RESTART_ENABLED" == "yes" ]]; then
        if [[ "$DRIFT_DETECTED" == true ]]; then
            drift_elapsed=$((now_ts - DRIFT_START_TIME))
            drift_remaining=$((AUTO_RESTART_DURATION - drift_elapsed))
            pl " Auto    : ${C_RED}⚠ Drift detected${C_RESET} - restart in $(format_duration $drift_remaining)"
        else
            pl " Auto    : ${C_GREEN}OK${C_RESET} (threshold: ${AUTO_RESTART_THRESHOLD}%, duration: ${AUTO_RESTART_DURATION}s)"
        fi
    fi
    
    pl "----------------------------------------------------------------------------------"
    pl " Job Configuration:"
    for idx in "${!IFACES[@]}"; do
        pcap_name="${PCAPS[$idx]##*/}"
        pl "  $(printf '[%d] %-10s ← %-30s %4d Mbps × %2d procs' \
            "$idx" "${IFACES[$idx]}" "$pcap_name" "${TARGET_MBPS[$idx]}" "${REPLAY_COUNT[$idx]}")"
    done
    pl "----------------------------------------------------------------------------------"
    if [[ "$RUN_MODE" == "start" ]]; then
        pl " Control : ${C_YELLOW}Q${C_RESET} = STOP replay    ${C_YELLOW}Ctrl+C${C_RESET} = Exit console only"
    else
        pl " Control : ${C_YELLOW}Q${C_RESET} = Exit (replay 유지)    ${C_YELLOW}S${C_RESET} = STOP replay    ${C_YELLOW}Ctrl+C${C_RESET} = Exit"
    fi
    pl "${C_CYAN}==================================================================================${C_RESET}"
    pl "$(printf "${C_WHITE}%-12s %14s %10s %18s %6s %14s %-10s${C_RESET}" 'IFACE' 'PPS' 'Mbps' 'TX_PKTS' 'PROC' 'TARGET_MBPS' 'STATUS')"
    pl "----------------------------------------------------------------------------------"

    total_pps=0
    total_mbps_val="0.00"
    declare -a DIAG_LINES=()
    max_error_pct=0

    for iface in "${UNIQUE_IFACES[@]}"; do
        target_mbps="${IFACE_TARGET_MBPS[$iface]}"
        req_pps="${IFACE_REQ_PPS[$iface]}"
        expected_procs="${IFACE_TOTAL_PROCS[$iface]}"

        txp_prev=${TXP_PREV[$iface]}
        txb_prev=${TXB_PREV[$iface]}
        txp_now=${TXP_NOW[$iface]}
        txb_now=${TXB_NOW[$iface]}

        delta_pkts=$((txp_now - txp_prev))
        delta_bytes=$((txb_now - txb_prev))
        ((delta_pkts < 0)) && delta_pkts=0
        ((delta_bytes < 0)) && delta_bytes=0

        pps=$(echo "scale=0; $delta_pkts / $ACTUAL_INTERVAL" | bc)
        total_pps=$((total_pps + pps))
        
        if ((delta_bytes > 0)); then
            mbps=$(printf "%.2f" "$(echo "scale=4; $delta_bytes * 8 / $ACTUAL_INTERVAL / 1000000" | bc)")
            total_mbps_val=$(printf "%.2f" "$(echo "scale=4; $total_mbps_val + $mbps" | bc)")
        else
            mbps="0.00"
        fi

        proc_cnt=$(pgrep -a tcpreplay 2>/dev/null | grep -c -- "-i $iface" || echo 0)
        tx_err_delta=$((TX_ERR_NOW[$iface] - TX_ERR_PREV[$iface]))
        tx_drop_delta=$((TX_DROP_NOW[$iface] - TX_DROP_PREV[$iface]))

        # STATUS 계산
        ((target_mbps > 0)) && mbps_ratio=$(echo "scale=4; $mbps / $target_mbps" | bc) || mbps_ratio="0"
        ((req_pps > 0)) && pps_ratio=$(echo "scale=4; $pps / $req_pps" | bc) || pps_ratio="0"
        mbps_pct=$(printf "%.1f" "$(echo "scale=2; $mbps_ratio * 100" | bc)")
        pps_pct=$(printf "%.1f" "$(echo "scale=2; $pps_ratio * 100" | bc)")

        error_pct=$(printf "%.1f" "$(echo "scale=2; ($mbps_pct - 100)" | bc)")
        error_pct_abs=${error_pct#-}
        
        if (( $(echo "$error_pct_abs > $max_error_pct" | bc -l) )); then
            max_error_pct=$error_pct_abs
        fi

        if (( $(echo "$mbps_ratio >= 0.95" | bc -l) )); then
            status="OK"; status_color="${C_GREEN}"; mbps_color="${C_GREEN}"
        elif (( $(echo "$pps_ratio >= 0.90" | bc -l) )); then
            status="PPS_MAX"; status_color="${C_RED}"; mbps_color="${C_YELLOW}"
        else
            status="BOTTLENECK"; status_color="${C_YELLOW}"
            (( $(echo "$mbps_ratio >= 0.70" | bc -l) )) && mbps_color="${C_YELLOW}" || mbps_color="${C_RED}"
        fi

        pl "$(printf '%-12s %14s %b%10s%b %18s %6d %14s %b%-10s%b' \
            "$iface" "$(format_number $pps)" "$mbps_color" "$mbps" "$C_RESET" \
            "$(format_number $txp_now)" "$proc_cnt" "$(format_number $target_mbps)" "$status_color" "$status" "$C_RESET")"

        # DIAG
        if [[ "$status" == "OK" ]]; then
            DIAG_LINES+=("${C_GREEN}[DIAG] $iface: $status${C_RESET} (Mbps: ${mbps_pct}%, PPS: ${pps_pct}%)")
        elif [[ "$status" == "PPS_MAX" ]]; then
            DIAG_LINES+=("${C_RED}[DIAG] $iface: $status${C_RESET} (Mbps: ${mbps_pct}%, PPS: ${pps_pct}%)")
        else
            DIAG_LINES+=("${C_YELLOW}[DIAG] $iface: $status${C_RESET} (Mbps: ${mbps_pct}%, PPS: ${pps_pct}%)")
        fi
        
        DIAG_LINES+=("  ├─ Mbps: ${mbps} / ${target_mbps} (${mbps_pct}%)")
        DIAG_LINES+=("  ├─ PPS: $(format_number $pps) / $(format_number $req_pps) (${pps_pct}%)")
        DIAG_LINES+=("  ├─ Procs: ${proc_cnt} / ${expected_procs}")
        
        (( $(echo "$TCPREPLAY_CPU > 90" | bc -l) )) && \
            DIAG_LINES+=("  ├─ CPU: ${TCPREPLAY_CPU}% ⚠ 포화") || \
            DIAG_LINES+=("  ├─ CPU: ${TCPREPLAY_CPU}% ✓")
        
        ((tx_err_delta > 0)) && \
            DIAG_LINES+=("  ├─ tx_errors: +${tx_err_delta} ⚠") || \
            DIAG_LINES+=("  ├─ tx_errors: +${tx_err_delta} ✓")
        
        ((tx_drop_delta > 0)) && \
            DIAG_LINES+=("  ├─ tx_dropped: +${tx_drop_delta} ⚠") || \
            DIAG_LINES+=("  ├─ tx_dropped: +${tx_drop_delta} ✓")
        
        # 인터페이스별 달성률 저장 (Job 권장값 계산용)
        if (( $(echo "$target_mbps > 0" | bc -l) )); then
            IFACE_ACTUAL_MBPS[$iface]="$mbps"
            IFACE_RATIO[$iface]=$(echo "scale=4; $target_mbps / $mbps" | bc)
        else
            IFACE_RATIO[$iface]="1.0"
        fi
        
        # Job별 권장값 계산 및 출력
        DIAG_LINES+=("  └─ [RECOMMEND] Job 설정:")
        for job_idx in "${!IFACES[@]}"; do
            if [[ "${IFACES[$job_idx]}" == "$iface" ]]; then
                job_target="${TARGET_MBPS[$job_idx]}"
                job_procs="${REPLAY_COUNT[$job_idx]}"
                pcap_name="${PCAPS[$job_idx]##*/}"
                ratio="${IFACE_RATIO[$iface]}"
                
                # 권장 TARGET_MBPS 계산 (안정적 운영 기준)
                recommend_mbps=$(printf "%.0f" "$(echo "scale=2; $job_target * $ratio" | bc)")
                # 50 단위로 반올림
                recommend_mbps=$(( (recommend_mbps + 25) / 50 * 50 ))
                
                diff=$((job_target - recommend_mbps))
                diff_abs=${diff#-}
                
                if (( diff_abs <= 100 )); then
                    # 차이가 100 이하면 유지
                    DIAG_LINES+=("      [${job_idx}] ${pcap_name}: ${C_GREEN}${job_target} → 유지${C_RESET}")
                elif (( recommend_mbps > job_target )); then
                    # 여유 있음 - 증가 가능
                    DIAG_LINES+=("      [${job_idx}] ${pcap_name}: ${C_CYAN}${job_target} → ${recommend_mbps}${C_RESET} (↑ 증가 가능)")
                else
                    # 초과 - 감소 권장
                    DIAG_LINES+=("      [${job_idx}] ${pcap_name}: ${C_YELLOW}${job_target} → ${recommend_mbps}${C_RESET} (↓ 안정화)")
                fi
            fi
        done

        TXP_PREV[$iface]=$txp_now
        TXB_PREV[$iface]=$txb_now
        TX_ERR_PREV[$iface]=${TX_ERR_NOW[$iface]}
        TX_DROP_PREV[$iface]=${TX_DROP_NOW[$iface]}
    done
    
    # RECOMMEND CONFIG 출력
    pl ""
    DIAG_LINES+=("")
    DIAG_LINES+=("${C_CYAN}[RECOMMEND CONFIG]${C_RESET}")
    
    # 권장 TARGET_MBPS 배열 생성
    recommend_config="TARGET_MBPS=("
    for job_idx in "${!IFACES[@]}"; do
        iface_tmp="${IFACES[$job_idx]}"
        job_target="${TARGET_MBPS[$job_idx]}"
        ratio="${IFACE_RATIO[$iface_tmp]:-1.0}"
        recommend_mbps=$(printf "%.0f" "$(echo "scale=2; $job_target * $ratio" | bc)")
        recommend_mbps=$(( (recommend_mbps + 25) / 50 * 50 ))
        [[ $job_idx -gt 0 ]] && recommend_config+=" "
        recommend_config+="$recommend_mbps"
    done
    recommend_config+=")"
    DIAG_LINES+=("  $recommend_config")

    SOFTNET_DROP_PREV=$SOFTNET_DROP_NOW
    SOFTNET_SQUEEZE_PREV=$SOFTNET_SQUEEZE_NOW
    PREV_MEASURE_TS=$CURR_MEASURE_TS

    pl "----------------------------------------------------------------------------------"
    pl "$(printf "${C_WHITE}%-12s %14s %10s${C_RESET}" 'TOTAL' "$(format_number $total_pps)" "$total_mbps_val")"
    pl "${C_CYAN}==================================================================================${C_RESET}"
    
    ((total_procs > 0)) && {
        if [[ "$RUN_MODE" == "start" ]]; then
            pl "${C_GREEN}[STATUS]${C_RESET} Replay running | Press Q to STOP"
        else
            pl "${C_GREEN}[STATUS]${C_RESET} Replay running | Q=Exit, S=STOP"
        fi
    } || pl "${C_RED}[STATUS]${C_RESET} No replay process detected!"
    
    pl "===================================================================================="

    for line in "${DIAG_LINES[@]}"; do
        pl "$line"
    done

    ############################################
    # AUTO_RESTART 로직
    ############################################
    if [[ "$AUTO_RESTART_ENABLED" == "yes" && $total_procs -gt 0 ]]; then
        if (( $(echo "$max_error_pct > $AUTO_RESTART_THRESHOLD" | bc -l) )); then
            if [[ "$DRIFT_DETECTED" == false ]]; then
                DRIFT_DETECTED=true
                DRIFT_START_TIME=$now_ts
                pl ""
                pl "${C_YELLOW}[AUTO] Drift detected (${max_error_pct}% > ${AUTO_RESTART_THRESHOLD}%). Monitoring...${C_RESET}"
            else
                drift_elapsed=$((now_ts - DRIFT_START_TIME))
                if ((drift_elapsed >= AUTO_RESTART_DURATION)); then
                    pl ""
                    pl "${C_RED}[AUTO] Drift persisted for ${drift_elapsed}s. Auto-restarting...${C_RESET}"
                    start_replay_sessions
                    START_TS=$(date +%s)
                    RESTART_COUNT=$((RESTART_COUNT + 1))
                    DRIFT_DETECTED=false
                    DRIFT_START_TIME=0
                    
                    for iface in "${UNIQUE_IFACES[@]}"; do
                        TXP_PREV[$iface]=$(read_stat "/sys/class/net/$iface/statistics/tx_packets" 0)
                        TXB_PREV[$iface]=$(read_stat "/sys/class/net/$iface/statistics/tx_bytes" 0)
                    done
                    PREV_MEASURE_TS=$(date +%s.%N)
                    sleep "$REFRESH_INTERVAL"
                    continue
                fi
            fi
        else
            if [[ "$DRIFT_DETECTED" == true ]]; then
                pl ""
                pl "${C_GREEN}[AUTO] Drift resolved. Counter reset.${C_RESET}"
            fi
            DRIFT_DETECTED=false
            DRIFT_START_TIME=0
        fi
    fi

    # 잔상 제거
    for _ in {1..3}; do
        pl ""
    done
done
