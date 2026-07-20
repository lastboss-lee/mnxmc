#!/bin/bash
set -e

PCAP="$1"
PPS_LIST=(250000 320000 650000 950000)
GBPS_TARGETS=(1 2 3 5)

if [ -z "$PCAP" ] || [ ! -f "$PCAP" ]; then
  echo "Usage: $0 <pcap_file>"
  exit 1
fi

echo "===================================================="
echo "[ PCAP Bandwidth / PPS Calculator ]"
echo "PCAP File : $PCAP"
echo "===================================================="

# 평균 패킷 크기 계산
AVG_PKT=$(tcpdump -r "$PCAP" -n -q 2>/dev/null | \
awk '{sum+=$NF; cnt++} END {if(cnt>0) printf "%.2f", sum/cnt; else print 0}')

if [ "$AVG_PKT" = "0" ]; then
  echo "[ERROR] Failed to calculate average packet size"
  exit 1
fi

echo
echo "▶ Average Packet Size"
echo "  - ${AVG_PKT} bytes"
echo

# PPS → Gbps 계산
echo "▶ PPS → Estimated Gbps (per port)"
printf "%-12s %-12s\n" "PPS" "Gbps"
echo "-----------------------------"

for pps in "${PPS_LIST[@]}"; do
  gbps=$(awk -v p="$pps" -v s="$AVG_PKT" \
    'BEGIN { printf "%.2f", (p*s*8)/1e9 }')
  printf "%-12s %-12s\n" "$pps" "$gbps"
done

echo

# Gbps → PPS 역산
echo "▶ Target Gbps → Required PPS (per port)"
printf "%-12s %-12s\n" "Gbps" "Required PPS"
echo "-----------------------------"

for g in "${GBPS_TARGETS[@]}"; do
  req_pps=$(awk -v g="$g" -v s="$AVG_PKT" \
    'BEGIN { printf "%d", (g*1e9)/(s*8) }')
  printf "%-12s %-12s\n" "$g" "$req_pps"
done

echo
echo "===================================================="
echo "NOTE:"
echo "- Gbps values are per-port"
echo "- tcpreplay practical limit ≈ 900k~1M PPS per process"
echo "- For higher Gbps, use multi tcpreplay or DPDK"
echo "===================================================="

