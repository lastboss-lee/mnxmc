---
name: RAID 감지 로직 (install_packages.sh [5/5])
description: install_packages.sh의 RAID 감지 방식과 raid.cfg 생성 규칙
type: project
---

install_packages.sh [5/5] 단계에서 RAID 감지 로직이 변경되었다 (2026-03-17 기준).

**변경 내용:**
- 기존: 바이너리 파일 존재 여부만으로 RAID_TYPE 결정 (storcli64 있으면 megaraid)
- 현재: lspci 하드웨어 감지 → perccli64 실제 통신 확인 우선 → storcli64 확인 → 바이너리 폴백

**RAID_TYPE 값:**
- `megaraid`: MegaRAID 컨트롤러, RAID_CLI = storcli64 경로
- `dell_perc`: Dell PERC 컨트롤러, RAID_CLI = perccli64 경로
- `none`: lspci에서 RAID 컨트롤러 미감지 — raid.cfg 생성 안 함
- `unknown`: lspci에서 감지됐으나 CLI 없음 — raid.cfg 생성 안 함

**raid.cfg 생성 조건:** RAID_TYPE이 megaraid 또는 dell_perc일 때만 /mnxmc/raid.cfg 생성.

**CLI 경로 우선순위 (perccli):** /usr/local/bin/perccli64 → /opt/MegaRAID/perccli/perccli64 → PATH
**CLI 경로 우선순위 (storcli):** /usr/local/bin/storcli64 → /opt/MegaRAID/storcli/storcli64 → PATH

**Why:** 과거에는 바이너리 존재만으로 판단하여 실제 컨트롤러가 없는 환경에서 오탐이 발생했다.
**How to apply:** RAID 관련 문서 작성 시 이 감지 흐름을 기준으로 기술한다.
