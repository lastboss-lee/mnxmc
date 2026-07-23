================================================================================
  MNXMC (MNX Management Console) 설치 및 운영 가이드
  버전: 2.3.0
  작성: SANDS LAB Inc.
  최종 업데이트: 2026-07-23
================================================================================

  v2.3.0 변경 내역 (2026-07-23)
  --------------------------------
   1) UI 디자인 시스템 리팩토링 (Phase 1~27)
      - app/ui/ 공통 컴포넌트(tokens/theme/widgets/screen) 기반 도입,
        7개 화면(Dashboard/System/Performance/Config/Service/Network/
        Log Monitor/Command Shell)을 공통 BaseScreen 4구획 골격으로 통일
      - 카드 기반 System/Performance overview + MeterBar 임계값 색상 통일
      - 헤더 Service/Alarm/Health 지시자 라이브화(app/ui/status.py)
      - Config 설정페이지화 + Capture 인터페이스 태그 배열 에디터
      - Network config 모달 재설계, active-pane 포커스/방향 지시자
   2) 안정성/보안
      - System/Dashboard 매초 수집을 스레드로 오프로드(블로킹 제거)
      - utils/auth su fallback root 우회 차단
   3) 데드코드 제거(미사용 위젯·도달불가 화면), 버전 문자열 전 파일 2.3.0 통일
      - 설계 문서: docs/design/DESIGN_SYSTEM.md 참고

  v2.2.0 변경 내역 (2026-06-04)
  --------------------------------
   1) Service Manager Elasticsearch 노드 분할
      - 단일 ES 항목을 elasticsearch-node-1 / elasticsearch-node-2 로 분할 관리
   2) 콘솔 버전 문자열 통일

  v2.1.4 변경 내역 (2026-05-15)
  --------------------------------
   1) graidctl 출력 ANSI 색상 escape 제거
      - graidctl이 stdout에 \x1b[0;32m 형태의 ANSI 색상 코드를 포함해
        출력함을 확인. Rich/Static 위젯이 이를 렌더하면서 마크업 충돌이
        발생하여 Disk Info 화면 갱신이 실패하던 문제 해결
      - `_ANSI_RE` 정규식으로 strip 후 `_rich_escape` 적용

  v2.1.3 변경 내역 (2026-05-15)
  --------------------------------
   1) graidctl 출력 Rich 마크업 안전망
      - _run_graidctl 출력 라인을 rich.markup.escape() 처리 →
        graidctl 박스 테이블에 포함된 잠재 토큰이 Rich 마크업으로
        오인되어 위젯 update 시 예외가 나는 케이스 차단
   2) Disk Info 진입 시 예외 격리
      - _update_info의 disk 분기에 별도 try/except 추가 →
        렌더 예외 발생 시 우측 패널에 traceback이 직접 표시되어
        후속 진단 가능

  v2.1.2 변경 내역 (2026-05-15)
  --------------------------------
   1) install_packages.sh RAID 자동 감지 보강
      - graidctl probe 분기 추가 (`graidctl version` 정상 종료 확인)
      - 응답 시 raid.cfg 자동 생성: RAID_TYPE=graid, RAID_CLI=/usr/bin/graidctl
      - 검증 단계에 graidctl 항목 추가
   2) v2.1.1 누락 보완 — install_packages.sh 만 다시 돌려도 GRAID 시스템이
      raid.cfg 자동 생성/감지되도록 정정

  v2.1.1 변경 내역 (2026-05-15)
  --------------------------------
   1) ServiceScreen 권한 패치
      - sands 계정으로 TUI를 직접 실행해도 systemctl 제어가 동작하도록
        non-root 환경에서 `sudo -n /usr/bin/systemctl ...` 자동 분기 적용
      - root 실행 시에는 기존과 동일하게 systemctl 직접 호출
   2) GRAID SupremeRAID (graidctl) 지원 추가
      - /usr/bin/graidctl 자동 감지 및 raid.cfg RAID_TYPE=graid 지원
      - System > Storage Overview > Disk Info 에서 DG/VD/PD 목록 조회
      - sudoers.d/mnxmc 에 /usr/bin/graidctl NOPASSWD 등록

목차
  1. 개요
  2. 사전 요구사항
  3. deb 패키지 설치
  4. install_packages.sh 단계별 설명
  5. 보안 취약점 점검 및 조치 (infra_audit)
  6. 운영 참고사항


================================================================================
1. 개요
================================================================================

MNXMC는 MNX NDR 시스템을 운영하는 Ubuntu 서버에서 사용하는 TUI 기반
관리 콘솔입니다.

  - SSH 접속 시 자동으로 콘솔 진입
  - TTY1(물리 콘솔)에서도 자동 실행
  - 네트워크 인터페이스, Elasticsearch, Kafka, UFW 방화벽,
    서비스 상태, 디스크 성능, 시스템 전원 등 주요 설정을 GUI 없이 관리
  - 주요정보통신기반시설 기술적 취약점(U-01~U-67) 점검 및 자동 조치 지원


================================================================================
2. 사전 요구사항
================================================================================

  - OS : Ubuntu 22.04 LTS (x86_64)
  - 권한 : root 또는 sudo 권한 보유 계정
  - 인터넷 : 불필요 (오프라인 설치 패키지 포함)
  - 필수 계정 : sands (없으면 useradd -m sands 생성 후 진행)


================================================================================
3. deb 패키지 설치
================================================================================

  [1단계] 패키지 파일 전송
  -------------------------
  scp 또는 USB 등을 통해 서버에 deb 파일을 복사합니다.

    scp mnxmc-2.1.4.deb sands@<서버IP>:~

  [2단계] deb 설치
  -----------------
  /mnxmc 디렉터리에 소스 및 오프라인 패키지를 압축 해제합니다.

    sudo dpkg -i mnxmc-2.1.4.deb

  설치 후 안내 메시지:
    ============================================================
      MNXMC 파일 설치 완료: /mnxmc
      다음 명령으로 패키지 및 환경을 설치하세요:
        sudo bash /mnxmc/packages/install_packages.sh
    ============================================================

  [3단계] 환경 구성 스크립트 실행
  ---------------------------------
    sudo bash /mnxmc/packages/install_packages.sh

  ※ 이후 단계 4에서 각 단계를 설명합니다.


================================================================================
4. install_packages.sh 단계별 설명
================================================================================

  스크립트 경로: /mnxmc/packages/install_packages.sh
  실행 권한    : root 필수

  ------------------------------------------------------------------------------
  [0/0] Timezone 설정  ← 사전 설정 (설치 시작 전 항상 적용)
  ------------------------------------------------------------------------------
  시스템 타임존을 KST (Korea Standard Time, UTC+9) 로 설정합니다.

    timedatectl set-timezone Asia/Seoul

    - 이미 Asia/Seoul 로 설정된 경우 skip
    - timedatectl 실패 시 /etc/localtime 심볼릭 링크 + /etc/timezone 직접 설정
      (fallback)

  ※ 로그 타임스탬프 및 시스템 시간 표시가 KST 기준으로 통일됩니다.

  ------------------------------------------------------------------------------
  [1/13] apt 패키지 설치
  ------------------------------------------------------------------------------
  /mnxmc/packages/apt/ 폴더의 .deb 파일을 오프라인으로 설치합니다.
  python3.12, smartmontools, ethtool, dmidecode, curl 등 포함.

    - 이미 동일 버전 이상이 설치된 패키지는 자동 skip
    - 의존성 순서 오류 발생 시 최대 3회 재시도
    - 네트워크 없이 동작 (apt source 비활성화)

  ------------------------------------------------------------------------------
  [2/13] pip 패키지 설치
  ------------------------------------------------------------------------------
  /mnxmc/packages/pip/ 폴더의 .whl 파일을 오프라인으로 설치합니다.
  textual, rich, requests 포함.

    - python3.12 기준 설치
    - PEP 668 환경(Ubuntu 23.04+) 자동 대응

  ------------------------------------------------------------------------------
  [3/13] StorCLI 설치
  ------------------------------------------------------------------------------
  LSI/MegaRAID 컨트롤러 관리 도구를 설치합니다.

    설치 경로: /opt/MegaRAID/storcli/storcli64
    링크 생성: /usr/local/bin/storcli64

  ------------------------------------------------------------------------------
  [4/13] PercCLI 설치
  ------------------------------------------------------------------------------
  Dell PERC H3xx/H7xx 계열 RAID 컨트롤러 관리 도구를 설치합니다.

    설치 경로: /opt/MegaRAID/perccli/
    링크 생성: /usr/local/bin/perccli, /usr/local/bin/perccli64

  ------------------------------------------------------------------------------
  [5/13] sudoers 설정
  ------------------------------------------------------------------------------
  MNXMC가 sands 계정으로 시스템 명령을 패스워드 없이 실행하도록 허용합니다.

    설치 경로: /etc/sudoers.d/mnxmc
    권한      : 440 (root 전용 읽기)
    소스 파일: /mnxmc/packages/sudoers_mnxmc

    - 기존 파일과 내용이 동일하면 skip (재실행 안전)
    - visudo -c 로 문법 검증 후 적용. 오류 시 자동 삭제

  허용 명령어 (NOPASSWD) 전체 목록:
  ┌─────────────────────────────────────────────────────────────────────────┐
  │ 하드웨어 정보 조회                                                       │
  │   /usr/sbin/dmidecode                  메모리·BIOS 정보 조회            │
  │   /usr/local/bin/storcli64             MegaRAID RAID 상태 조회          │
  │   /usr/local/bin/perccli64             Dell PERC RAID 상태 조회         │
  │   /opt/MegaRAID/perccli/perccli64      PERC CLI 직접 경로               │
  │   /usr/bin/graidctl                    GRAID SupremeRAID DG/VD/PD 조회 │
  │   /usr/sbin/smartctl                   디스크 S.M.A.R.T 조회            │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ 네트워크 설정                                                             │
  │   /usr/sbin/ip                         인터페이스 모드 설정 (promisc)   │
  │   /usr/sbin/netplan                    netplan 설정 적용                 │
  │   /usr/sbin/ethtool                    인터페이스 드라이버 정보 조회     │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ 서비스 제어 (ServiceScreen 비밀번호 인증 후 실행)                        │
  │   /usr/bin/systemctl                   MNX 11개 서비스 제어              │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ 방화벽 (UFW)                                                             │
  │   /usr/sbin/ufw, /usr/bin/ufw          UFW 방화벽 규칙 관리              │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ 설정 파일 쓰기 (경로 고정 — 임의 경로 쓰기 불가)                        │
  │   /usr/bin/tee /opt/mnx/etc/config.ini           캡처 설정               │
  │   /usr/bin/tee /opt/mnx/etc/mnx_config.json      서비스 설정             │
  │   /usr/bin/tee /opt/mnx/etc/mnxmc_console.json   콘솔 세션 정책          │
  │   /usr/bin/tee /opt/service_control/settings.json 서비스 컨트롤 설정     │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ Suricata 설정 (캡처 인터페이스 동기화)                                   │
  │   /usr/bin/tee /etc/suricata/suricata.yaml   af-packet/pcap 동기화     │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ SSH 세션 정책                                                            │
  │   /usr/bin/tee /etc/ssh/sshd_config.d/mnxmc.conf SSH idle/세션 정책     │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ 네트워크 설정 파일 쓰기                                                  │
  │   /usr/bin/tee /etc/netplan/70-netplan-set.yaml  netplan 설정            │
  │   /usr/bin/tee /etc/netplan/50-cloud-init.yaml   cloud-init netplan     │
  │   /usr/bin/tee /etc/systemd/system/promisc-*.service  promisc 서비스    │
  │   /usr/bin/rm -f /etc/systemd/system/promisc-*.service  promisc 제거    │
  │   /usr/bin/chmod 600 /etc/netplan/*              netplan 권한 설정       │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ Disk Perf Test (경로 고정 — 지정 경로 외 실행 불가)                     │
  │   /usr/bin/fio                         fio I/O 성능 측정                  │
  │   /usr/bin/install -d -m 755           테스트 디렉토리 생성               │
  │     /application/.fio_perf_tmp                                           │
  │     /data/.fio_perf_tmp                                                  │
  │     /pipeline/.fio_perf_tmp                                              │
  │   /usr/bin/rm -rf                      테스트 디렉토리 정리               │
  │     /application/.fio_perf_tmp                                           │
  │     /data/.fio_perf_tmp                                                  │
  │     /pipeline/.fio_perf_tmp                                              │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ System Power Control                                                     │
  │   /sbin/reboot, /usr/sbin/reboot       시스템 재부팅                     │
  │   /sbin/shutdown -h now                시스템 종료                       │
  │   /usr/sbin/shutdown -h now            (Ubuntu 20.04+ canonical 경로)   │
  └─────────────────────────────────────────────────────────────────────────┘

  sudoers만 단독 재적용이 필요한 경우:
    sudo bash /mnxmc/packages/apply_sudoers.sh

  ------------------------------------------------------------------------------
  [6/13] getty@tty1 서비스 설정
  ------------------------------------------------------------------------------
  물리 콘솔(TTY1)에서 부팅 완료 후 MNXMC가 자동 실행되도록 설정합니다.

    /etc/systemd/system/getty@tty1.service.d/override.conf

    ExecStart=/usr/bin/python3.12 /mnxmc/main-login.py
    User=root

  ------------------------------------------------------------------------------
  [7/13] bash.bashrc SSH 진입 제어
  ------------------------------------------------------------------------------
  SSH로 접속한 sands 계정이 대화형 터미널 세션일 때 MNXMC를 자동 실행합니다.

    /etc/bash.bashrc 에 조건 블록 추가:
      - SSH_CONNECTION 환경변수 확인
      - SSH_TTY 확인 (터미널 세션만 적용)
      - MNXMC_DONE 플래그로 중복 실행 방지

  ※ 이미 설정된 경우 skip.

  ------------------------------------------------------------------------------
  [8/13] 심볼릭 링크 생성
  ------------------------------------------------------------------------------
  /data/tools/ 의 운영 스크립트를 /usr/local/bin/ 에 링크합니다.

    mnx_check_index, mnx_check_kafka, mnx_check_slowlog,
    mnx_all_start_service, mnx_all_stop_service,
    mnx_status_check

  ※ 파일이 없는 경우 WARN 출력 후 skip (비 MNX 서버 정상).

  ------------------------------------------------------------------------------
  [9/13] /root/.bashrc 설정
  ------------------------------------------------------------------------------
  root 계정 환경 설정을 적용합니다.

    - LS_COLORS (컬러 파일 목록)
    - HISTTIMEFORMAT (명령 이력 타임스탬프)
    - alias mnxmon (Arkime 실시간 패킷 모니터링)

  ------------------------------------------------------------------------------
  [10/13] /home/sands/.bashrc 설정
  ------------------------------------------------------------------------------
  sands 계정 환경 설정을 적용합니다. (root와 동일 내용)

  ------------------------------------------------------------------------------
  [11/13] systemd-networkd-wait-online 비활성화
  ------------------------------------------------------------------------------
  네트워크 대기로 인한 부팅 지연을 방지합니다.

    systemctl disable systemd-networkd-wait-online.service
    systemctl mask    systemd-networkd-wait-online.service

  ------------------------------------------------------------------------------
  [12/13] cloud-init 네트워크 설정 비활성화
  ------------------------------------------------------------------------------
  VM 환경에서 cloud-init이 네트워크 설정을 덮어쓰는 것을 방지합니다.

    /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg

  ※ cloud-init 미설치 시 skip.

  ------------------------------------------------------------------------------
  [13/13] 로그인 경고 배너 설정
  ------------------------------------------------------------------------------
  SSH 및 콘솔 로그인 시 SANDS LAB 보안 경고 배너를 표시합니다.

    /etc/issue.net  : SSH 배너
    /etc/issue      : 로컬 콘솔 배너
    /etc/ssh/sshd_config : Banner 항목 추가/갱신

  ------------------------------------------------------------------------------
  [검증] 설치 완료 후 자동 확인
  ------------------------------------------------------------------------------
  스크립트 완료 시 다음 항목을 자동 점검합니다.

    timezone (Asia/Seoul KST)
    python3.12, pip, textual, rich, requests
    curl, ethtool, dmidecode, smartctl
    storcli64, perccli64, perccli 링크
    raid.cfg (RAID 컨트롤러 자동 감지)


================================================================================
5. 보안 취약점 점검 및 조치 (infra_audit)
================================================================================

  스크립트 위치: /mnxmc/infra_audit/
    - infra_audit.sh      : 취약점 점검 (보고서 생성)
    - infra_remediate.sh  : 취약점 조치

  점검 기준: 2026년판 KISA 주요정보통신기반시설 기술적 취약점 분석·평가
             상세가이드 (U-01 ~ U-67, 총 67개 항목)

  ------------------------------------------------------------------------------
  [STEP 1] 취약점 점검 실행
  ------------------------------------------------------------------------------

    cd /mnxmc/infra_audit
    sudo bash infra_audit.sh

  완료 시 보고서 파일이 생성됩니다:
    infra_audit_report_YYYYMMDD_HHMMSS.txt

  점검 결과 요약 예시:
    총 점검: 67개  |  양호: 52  |  취약: 12  |  N/A: 3

  ------------------------------------------------------------------------------
  [STEP 2] 취약점 조치 실행
  ------------------------------------------------------------------------------

  조치 항목 분류:
  ┌─────────┬──────────────────────────────────────────────────────────────┐
  │  AUTO   │ 서비스 영향 없이 자동 적용 가능                              │
  │  SEMI   │ 운영 영향 있음, 실행 전 확인 요청                            │
  │  MANUAL │ 정책 판단 필요, 가이드 안내만 제공 (자동 조치 없음)          │
  │  SKIP   │ 양호 또는 N/A (조치 불필요)                                  │
  └─────────┴──────────────────────────────────────────────────────────────┘

  AUTO 항목 목록:
    U-01  root 계정 원격 접속 제한
    U-02  비밀번호 관리정책 설정
    U-03  계정 잠금 임계값 설정
    U-12  세션 종료 시간 설정 (TMOUT)
    U-14  root PATH에 현재 디렉터리 포함 금지
    U-25  world writable 파일 권한 제거
    U-64  최신 보안 패치 적용 ← Suricata 설정 보호 처리 포함
    U-67  로그 디렉터리 소유자 및 권한 설정

  SEMI 항목 목록:
    U-06  사용자 계정 su 기능 제한
    U-07  불필요한 계정 shell 비활성화
    U-33  숨겨진 파일 (.swp) 점검 및 제거
    U-62  로그인 경고 메시지 설정

  조치 실행 방법:

  (1) 대화형 모드 (권장)
  ----------------------
    sudo bash infra_remediate.sh

    - 취약 항목 목록을 번호로 표시
    - 처리할 항목을 선택 후 실행

    선택 옵션:
      all      모든 취약 항목 처리
               (AUTO 자동, SEMI 확인 후 적용, MANUAL 가이드 출력)
      auto     AUTO 항목만 자동 적용
      1,3,5    번호 선택 (쉼표 구분)
      report   전체 항목 현황 리포트 출력 (U-01~U-67 상태 일람)
      q        종료

  (2) 자동 모드 (AUTO 항목 일괄 처리)
  ------------------------------------
    sudo bash infra_remediate.sh --auto

    - AUTO 항목만 확인 없이 즉시 적용
    - CI/CD 또는 초기 서버 구성 시 사용

  (3) 미리보기 모드 (실제 변경 없음)
  ------------------------------------
    sudo bash infra_remediate.sh --dry-run

    - 조치될 명령어를 출력만 하고 실제 적용하지 않음
    - 사전 검토 시 사용

  (4) 특정 보고서 파일 지정
  --------------------------
    sudo bash infra_remediate.sh infra_audit_report_20260401_120000.txt

    - 보고서 파일 미지정 시 최신 파일 자동 선택

  ------------------------------------------------------------------------------
  U-64 (최신 보안 패치 적용) 특이사항
  ------------------------------------------------------------------------------

  MNX 운영 환경에서 apt-get upgrade 실행 시 Suricata 패키지 업그레이드로 인해
  /etc/suricata/ 설정파일이 덮어써지는 충돌이 발생할 수 있습니다.

  조치 스크립트는 다음 순서로 이를 방지합니다:

    1. apt-mark hold suricata      Suricata 업그레이드 잠금
    2. apt-get upgrade             나머지 패키지만 업데이트
                                   (--force-confold: 기존 설정 유지)
    3. apt-mark unhold suricata    잠금 해제

  추가 보호 패키지가 필요한 경우 infra_remediate.sh 의 HOLD_PKGS 변수에 추가:
    HOLD_PKGS="suricata 추가패키지명"

  ------------------------------------------------------------------------------
  조치 결과 로그
  ------------------------------------------------------------------------------

  조치 실행 후 로그 파일이 자동 생성됩니다:
    infra_audit/infra_remediate_YYYYMMDD_HHMMSS.log

  백업 디렉터리 (조치 전 원본 파일 보관):
    infra_audit/backup_YYYYMMDD_HHMMSS/


================================================================================
6. 운영 참고사항
================================================================================

  [RAID 설정]
  -----------
  install_packages.sh 완료 후 raid.cfg가 자동 생성됩니다.
  컨트롤러가 감지되지 않으면 수동으로 생성합니다:

    # MegaRAID/LSI
    echo "RAID_TYPE=megaraid"  > /mnxmc/raid.cfg
    echo "RAID_CLI=/usr/local/bin/storcli64" >> /mnxmc/raid.cfg

    # Dell PERC
    echo "RAID_TYPE=dell_perc" > /mnxmc/raid.cfg
    echo "RAID_CLI=/usr/local/bin/perccli64" >> /mnxmc/raid.cfg

    # GRAID SupremeRAID
    echo "RAID_TYPE=graid"     > /mnxmc/raid.cfg
    echo "RAID_CLI=/usr/bin/graidctl" >> /mnxmc/raid.cfg

  ※ raid.cfg 미설정 시 storcli64 / perccli64 / graidctl 순서로 자동 감지.
    graidctl 은 `graidctl version` 정상 응답 시 채택됩니다.

  [MNX 설정 파일 위치]
  ---------------------
    /opt/mnx/etc/config.ini            캡처 인터페이스 설정 (INI)
    /opt/mnx/etc/mnx_config.json       ES, DPI, PCAP 등 서비스 설정 (JSON)
    /opt/mnx/etc/mnxmc_console.json    콘솔 세션 정책 (JSON)
    /opt/service_control/settings.json 서비스 컨트롤 설정 (JSON)

  MNXMC 콘솔 → MNX Config 메뉴에서 직접 편집 가능.
  저장 시 sudo tee 를 통해 root 소유 파일에 자동 반영.

  ※ config.ini에 EUC-KR 등 non-UTF-8 주석이 포함된 경우에도 저장이
    정상 동작합니다 (surrogateescape 방식으로 원본 바이트 보존).

  [Suricata 인터페이스 동기화]
  ----------------------------
  Capture Config > Interfaces 에서 인터페이스를 변경 저장하면
  /etc/suricata/suricata.yaml 의 af-packet 및 pcap 섹션이 자동 동기화됩니다.

    - af-packet: cluster-id 99부터 인터페이스 순서대로 감소 할당
    - pcap: 인터페이스 목록 교체 (첫 번째 항목의 주석 블록 보존)
    - '- interface: default' 블록은 항상 보존
    - 변경 전 백업: /opt/mnx/etc/suricata.yaml.bak

  ※ suricata.yaml 미존재 시 동기화가 skip 되며 config.ini 저장은 정상 완료.
  ※ 동기화 후 Suricata 서비스 재시작은 별도 수행:
    sudo systemctl restart suricata

  [SSH 세션 타임아웃]
  --------------------
  MNXMC 콘솔 세션 정책(기본 15분)과 SSH ClientAlive 설정이 연동됩니다.
  MNXMC → MNXMC Console → Session Policy 에서 변경 가능.

  [UFW 방화벽]
  ------------
  MNXMC → Security 메뉴에서 관리합니다.
  변경사항은 큐(Queue)에 쌓은 후 Apply UFW (Ctrl+S) 로 일괄 적용합니다.
  Clear Pending (ESC) 으로 적용 전 취소 가능.

  [Power Control (시스템 전원)]
  ------------------------------
  MNXMC → MNX Config → Power Control 에서 시스템 재부팅 또는 종료를 수행합니다.

    1. Reboot 또는 Shutdown 버튼 클릭
    2. 하단 Confirm: 입력란에 YES 입력 후 Enter
       (YES 외 다른 값 입력 시 취소됨, 대소문자 구분)
    3. 1.5초 후 즉시 실행 (SSH 세션 및 서비스 연결 끊어짐)

  ※ 실행 전 반드시 현재 작업을 저장하고 서비스 상태를 확인하십시오.
  ※ sudoers 에 /sbin/reboot, /usr/sbin/reboot, /sbin/shutdown, /usr/sbin/shutdown
     NOPASSWD 항목이 등록되어 있어야 정상 동작합니다.

  [sudoers 재적용]
  ----------------
  sudoers 설정이 누락되거나 초기화된 경우 단독 재적용:

    sudo bash /mnxmc/packages/apply_sudoers.sh

  정상 적용 여부 확인:

    sudo -l -U sands | grep -E "reboot|shutdown|fio|tee"

  [Timezone 확인]
  ---------------
    timedatectl show --property=Timezone --value
    # 출력: Asia/Seoul

  [MNXMC 수동 실행]
  ------------------
  SSH 자동 실행 없이 직접 실행하려면:

    cd /mnxmc
    python3.12 main.py

================================================================================
  END OF DOCUMENT
================================================================================
