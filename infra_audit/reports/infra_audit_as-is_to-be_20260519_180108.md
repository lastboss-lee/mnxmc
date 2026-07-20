---
title: "KISA 2026 기술적 취약점 분석·평가 — As-is / To-be 보고서"
subtitle: "Unix 서버 (Ubuntu 22.04) 67개 항목 전수"
date: "2026-05-19 18:01:08 KST"
geometry: a4paper,margin=2cm
mainfont: "Noto Sans CJK KR"
monofont: "Noto Sans Mono CJK KR"
fontsize: 10pt
header-includes:
  - \usepackage{longtable}
  - \usepackage{fancyhdr}
  - \pagestyle{fancy}
  - \fancyhead[L]{KISA 2026 보안 점검 보고서}
  - \fancyhead[R]{sands-test}
  - \fancyfoot[C]{\thepage}
---

\newpage

# 1. 개요

| 항목 | 값 |
|---|---|
| 점검 기준 | 2026 주요정보통신기반시설 기술적 취약점 분석·평가 방법 상세가이드 (KISA) |
| 대상 호스트 | sands-test |
| 운영체제 | Ubuntu 22.04.5 LTS |
| 커널 | 5.15.0-174-generic |
| 점검 범위 | U-01 ~ U-67 (Unix 서버 전체 67항목) |
| 생성 시각 | 2026-05-19 18:01:08 KST |
| Before 리포트 | `infra_audit_report_20260519_171719.txt` |
| After 리포트 | `infra_audit_report_20260519_171928.txt` |

\newpage

# 2. Executive Summary

## 2.1 점검 결과 요약 (Before vs After)

| 구분 | Before | After | 변화 |
|---|---:|---:|---:|
| 양호 | 27 | 34 | 7 |
| 취약 | 16 | 9 | -7 |
| N/A  | 24 | 24 | 0 |
| **합계** | **67** | **67** | — |

양호율 (N/A 제외): **Before 62% → After 79%**


## 2.2 항목별 상태 변화

| 분류 | 항목 ID | 건수 |
|---|---|---:|
| 해결 (취약 → 양호/N/A) | U-01 U-02 U-03 U-06 U-12 U-25 U-67  | 7 |
| 잔존 취약 | U-15 U-21 U-23 U-28 U-37 U-42 U-58 U-59 U-60  | 9 |
| 신규 발견 (regression) | (없음) | 0 |

## 2.3 최종 판정

> **잔존 취약 9건 — MANUAL 가이드에 따른 수동 조치 필요**

\newpage

# 3. 해결된 항목 (취약 → 양호/N/A)

조치 적용으로 취약 → 양호 또는 N/A로 전환된 항목입니다. As-is(조치 전), To-be(조치 후), 적용 명령을 항목별로 기록합니다.


### U-01 root 계정 원격 접속 제한

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [취약] |
| After  | [양호] |
| 상태   | **해결됨** |

**As-is (조치 전 점검 결과)**

```
PermitRootLogin 설정 없음 (Ubuntu 22.04 기본값: prohibit-password)
Ubuntu 22.04 기본값(prohibit-password)은 패스워드 root 로그인 차단이나
SSH 키 기반 root 로그인은 허용됩니다. 보안 강화를 위해 'no' 명시 권고.
```

**To-be (조치 후 재점검 결과)**

```
설정 확인: PermitRootLogin no
```

**적용 명령 / 변경 로그 (조치 로그 발췌)**

```
[2026-05-19 17:18:58][U-01] 조치 시작: PermitRootLogin no 설정
[2026-05-19 17:18:58][U-01] 완료: PermitRootLogin no 적용, SSH 재로드
```


### U-02 비밀번호 관리정책 설정

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [취약] |
| After  | [양호] |
| 상태   | **해결됨** |

**As-is (조치 전 점검 결과)**

```
/etc/security/pwquality.conf 파일 없음
[/etc/pam.d/common-password] pam_pwquality: 미설정
[/etc/login.defs] PASS_MAX_DAYS=99999, PASS_MIN_DAYS=0
[판정] pam_pwquality 복잡성 설정 미충족 (minlen>=8, dcredit/ucredit/lcredit/ocredit=-1 필요)
```

**To-be (조치 후 재점검 결과)**

```
[/etc/security/pwquality.conf] minlen=10, dcredit=-1, ucredit=-1, lcredit=-1, ocredit=-1
[/etc/pam.d/common-password] pam_pwquality: password	requisite			pam_pwquality.so retry=3
[/etc/login.defs] PASS_MAX_DAYS=90, PASS_MIN_DAYS=1
```

**적용 명령 / 변경 로그 (조치 로그 발췌)**

```
[2026-05-19 17:18:58][U-02] 조치 시작: pwquality + login.defs 설정
[2026-05-19 17:19:05][U-02] 완료: pwquality.conf minlen=10/복잡성, login.defs PASS_MAX_DAYS=90/PASS_MIN_DAYS=1
```


### U-03 계정 잠금 임계값 설정

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [취약] |
| After  | [양호] |
| 상태   | **해결됨** |

**As-is (조치 전 점검 결과)**

```
[/etc/security/faillock.conf] deny=미설정
[/etc/pam.d/common-auth] pam_faillock: 미설정
[판정] pam_faillock.so 설정 미비 또는 deny 값이 10 초과/미설정 (Ubuntu 22.04는 pam_faillock 사용)
```

**To-be (조치 후 재점검 결과)**

```
[/etc/security/faillock.conf] deny=5
[/etc/pam.d/common-auth] pam_faillock: auth	required				pam_faillock.so preauth silent
auth	[default=die]			pam_faillock.so authfail
```

**적용 명령 / 변경 로그 (조치 로그 발췌)**

```
[2026-05-19 17:19:05][U-03] 조치 시작: pam_faillock 설정
[2026-05-19 17:19:05][U-03] 완료: faillock.conf deny=5/unlock_time=600, common-auth 설정 완료
```


### U-06 사용자 계정 su 기능 제한

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [취약] |
| After  | [양호] |
| 상태   | **해결됨** |

**As-is (조치 전 점검 결과)**

```
[/etc/pam.d/su] wheel/group 제한: 미설정
wheel 그룹 멤버: 없음
sudo 그룹 멤버: sands
su 바이너리: -rwsr-xr-x 1 root root 55680 Mar  7 01:10 /usr/bin/su
```

**To-be (조치 후 재점검 결과)**

```
[/etc/pam.d/su] wheel/group 제한: auth required pam_wheel.so use_uid
wheel 그룹 멤버: sands
sudo 그룹 멤버: sands
su 바이너리: -rwsr-xr-x 1 root root 55680 Mar  7 01:10 /usr/bin/su
```

**적용 명령 / 변경 로그 (조치 로그 발췌)**

```
[2026-05-19 17:19:24][U-06] 조치 시작: su wheel 제한
[2026-05-19 17:19:24][U-06]   wheel 그룹 추가: sands
[2026-05-19 17:19:24][U-06] 완료: wheel 그룹 su 제한 설정
```


### U-12 세션 종료 시간 설정

| 속성 | 값 |
|---|---|
| 중요도 | 하 |
| Before | [취약] |
| After  | [양호] |
| 상태   | **해결됨** |

**As-is (조치 전 점검 결과)**

```
TMOUT 설정 파일: 미발견
TMOUT 값: 미설정 (600초 이하 권고)
```

**To-be (조치 후 재점검 결과)**

```
TMOUT 설정 파일: /etc/profile
TMOUT 값: 600 (600초 이하 권고)
```

**적용 명령 / 변경 로그 (조치 로그 발췌)**

```
[2026-05-19 17:19:05][U-12] 조치 시작: TMOUT=600 설정
[2026-05-19 17:19:05][U-12] 완료: TMOUT=600 설정 (/etc/profile)
```


### U-25 world writable 파일 점검

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [취약] |
| After  | [양호] |
| 상태   | **해결됨** |

**As-is (조치 전 점검 결과)**

```
world writable 파일 (운영/임시 디렉토리 제외, 최대 20개): /var/crash
/opt/scanengine/Update1/versions.id.512A26895407AEF4F2964BE772AF939A
/opt/scanengine/Update1/Plugins/emalware.543
/opt/scanengine/Update1/Plugins/emalware.i49
/opt/scanengine/Update1/Plugins/emalware.i23
/opt/scanengine/Update1/Plugins/emalware.348
/opt/scanengine/Update1/Plugins/sdx.ivd
/opt/scanengine/Update1/Plugins/emalware.073
/opt/scanengine/Update1/Plugins/emalware.285
/opt/scanengine/Update1/Plugins/e_spyw.i00
/opt/scanengine/Update1/Plugins/emalware.c07
/opt/scanengine/Update1/Plugins/emalware.i45
/opt/scanengine/Update1/Plugins/emalware.i77
/opt/scanengine/Update1/Plugins/e_spyw.i16
/opt/scanengine/Update1/Plugins/emalware.i86
/opt/scanengine/Update1/Plugins/gzip.xmd
/opt/scanengine/Update1/Plugins/emalware.387
/opt/scanengine/Update1/Plugins/emalware.224
/opt/scanengine/Update1/Plugins/emalware.231
/opt/scanengine/Update1/Plugins/emalware.424
검사 제외 경로: /proc /sys /dev /run /tmp /var/tmp /data /logs /application /opt/mnx /mnt /media /var/lib/docker /var/lib/containerd
```

**To-be (조치 후 재점검 결과)**

```
world writable 파일 (운영/임시 디렉토리 제외, 최대 20개): 없음
검사 제외 경로: /proc /sys /dev /run /tmp /var/tmp /data /logs /application /opt/mnx /mnt /media /var/lib/docker /var/lib/containerd
```

**적용 명령 / 변경 로그 (조치 로그 발췌)**

```
[2026-05-19 17:19:05][U-25] 조치 시작: world writable 파일 other-write 권한 제거
[2026-05-19 17:19:05][U-25]   chmod o-w: /var/crash
[2026-05-19 17:19:05][U-25]   chmod o-w: /opt/scanengine/Update1/versions.id.512A26895407AEF4F2964BE772AF939A
[2026-05-19 17:19:05][U-25]   chmod o-w: /opt/scanengine/Update1/Plugins/emalware.543
[2026-05-19 17:19:05][U-25]   chmod o-w: /opt/scanengine/Update1/Plugins/emalware.i49
[2026-05-19 17:19:05][U-25]   chmod o-w: /opt/scanengine/Update1/Plugins/emalware.i23
[2026-05-19 17:19:05][U-25]   chmod o-w: /opt/scanengine/Update1/Plugins/emalware.348
[2026-05-19 17:19:05][U-25]   chmod o-w: /opt/scanengine/Update1/Plugins/sdx.ivd
[2026-05-19 17:19:05][U-25]   chmod o-w: /opt/scanengine/Update1/Plugins/emalware.073
[2026-05-19 17:19:05][U-25]   chmod o-w: /opt/scanengine/Update1/Plugins/emalware.285
[2026-05-19 17:19:05][U-25]   chmod o-w: /opt/scanengine/Update1/Plugins/e_spyw.i00
[2026-05-19 17:19:05][U-25]   chmod o-w: /opt/scanengine/Update1/Plugins/emalware.c07
[2026-05-19 17:19:05][U-25]   chmod o-w: /opt/scanengine/Update1/Plugins/emalware.i45
[2026-05-19 17:19:05][U-25]   chmod o-w: /opt/scanengine/Update1/Plugins/emalware.i77
[2026-05-19 17:19:05][U-25]   chmod o-w: /opt/scanengine/Update1/Plugins/e_spyw.i16
```


### U-67 로그 디렉터리 소유자 및 권한

| 속성 | 값 |
|---|---|
| 중요도 | 중 |
| Before | [취약] |
| After  | [양호] |
| 상태   | **해결됨** |

**As-is (조치 전 점검 결과)**

```
/var/log: owner=root, perm=755
권한 이상 로그 파일: /var/log/lastlog: owner=root, perm=664
```

**To-be (조치 후 재점검 결과)**

```
/var/log: owner=root, perm=755
권한 이상 로그 파일: 없음
```

**적용 명령 / 변경 로그 (조치 로그 발췌)**

```
[2026-05-19 17:19:12][U-67] 조치 시작: /var/log 권한 설정
[2026-05-19 17:19:12][U-67] 완료: /var/log -> 755, wtmp 664, btmp 600, lastlog 644
```


\newpage

# 4. 잔존 취약 항목 (MANUAL 수동 조치 필요)

자동 조치 대상이 아니거나 운영 영향 검토 후 수동 적용이 필요한 항목입니다. 평가 기준과 권장 조치를 함께 기록합니다.


### U-15 파일 및 디렉터리 소유자 설정

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [취약] |
| After  | [취약] |
| 상태   | **잔존 (수동 조치 필요)** |

**As-is (조치 전 점검 결과)**

```
소유자/그룹 없는 파일 (최대 20개): /var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots/78/fs/var/lib/apt/lists/partial
/var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots/78/fs/var/lib/apt/lists/auxfiles
/var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots/78/fs/var/cache/apt/archives/partial
/var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots/62/fs/var/lib/apt/lists/partial
/var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots/62/fs/var/lib/apt/lists/auxfiles
/var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots/62/fs/var/cache/apt/archives/partial
```

**To-be (조치 후 재점검 결과)**

```
소유자/그룹 없는 파일 (최대 20개): /var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots/78/fs/var/lib/apt/lists/partial
/var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots/78/fs/var/lib/apt/lists/auxfiles
/var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots/78/fs/var/cache/apt/archives/partial
/var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots/62/fs/var/lib/apt/lists/partial
/var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots/62/fs/var/lib/apt/lists/auxfiles
/var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots/62/fs/var/cache/apt/archives/partial
```


### U-21 /etc/

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [취약] |
| After  | [취약] |
| 상태   | **잔존 (수동 조치 필요)** |

**As-is (조치 전 점검 결과)**

```
양호 파일: 없음
취약 파일: /etc/rsyslog.conf (owner=root, perm=644) /etc/rsyslog.d/20-ufw.conf (owner=root, perm=644) /etc/rsyslog.d/21-cloudinit.conf (owner=root, perm=644) /etc/rsyslog.d/50-default.conf (owner=root, perm=644)
```

**To-be (조치 후 재점검 결과)**

```
양호 파일: 없음
취약 파일: /etc/rsyslog.conf (owner=root, perm=644) /etc/rsyslog.d/20-ufw.conf (owner=root, perm=644) /etc/rsyslog.d/21-cloudinit.conf (owner=root, perm=644) /etc/rsyslog.d/50-default.conf (owner=root, perm=644)
```


### U-23 SUID/SGID 설정 파일 점검

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [취약] |
| After  | [취약] |
| 상태   | **잔존 (수동 조치 필요)** |

**As-is (조치 전 점검 결과)**

```
총 SUID/SGID 파일 수: 23
의심스러운 SUID/SGID 파일 (허용 목록 외): /usr/sbin/mount.nfs /usr/lib/mysql/plugin/auth_pam_tool_dir/auth_pam_tool
검사 제외 경로: /proc /sys /dev /run /tmp /var/tmp /data /logs /application /opt/mnx /mnt /media /var/lib/docker /var/lib/containerd
```

**To-be (조치 후 재점검 결과)**

```
총 SUID/SGID 파일 수: 23
의심스러운 SUID/SGID 파일 (허용 목록 외): /usr/sbin/mount.nfs /usr/lib/mysql/plugin/auth_pam_tool_dir/auth_pam_tool
검사 제외 경로: /proc /sys /dev /run /tmp /var/tmp /data /logs /application /opt/mnx /mnt /media /var/lib/docker /var/lib/containerd
```


### U-28 접속 IP 및 포트 제한

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [취약] |
| After  | [취약] |
| 상태   | **잔존 (수동 조치 필요)** |

**As-is (조치 전 점검 결과)**

```
UFW: Status: inactive
iptables INPUT 규칙 수: 0
TCP Wrapper - hosts.allow 규칙: 0, hosts.deny 규칙: 0
[판정] UFW/iptables 접근 제어 미설정 또는 규칙 없음
```

**To-be (조치 후 재점검 결과)**

```
UFW: Status: inactive
iptables INPUT 규칙 수: 0
TCP Wrapper - hosts.allow 규칙: 0, hosts.deny 규칙: 0
[판정] UFW/iptables 접근 제어 미설정 또는 규칙 없음
```


### U-37 crontab 설정파일 권한

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [취약] |
| After  | [취약] |
| 상태   | **잔존 (수동 조치 필요)** |

**As-is (조치 전 점검 결과)**

```
/usr/bin/crontab: owner=root, perm=2755
/etc/crontab: owner=root, perm=644
/etc/cron.d/: owner=root, perm=755
/etc/cron.daily/: owner=root, perm=755
/etc/cron.hourly/: owner=root, perm=755
/etc/cron.weekly/: owner=root, perm=755
/etc/cron.monthly/: owner=root, perm=755
```

**To-be (조치 후 재점검 결과)**

```
/usr/bin/crontab: owner=root, perm=2755
/etc/crontab: owner=root, perm=644
/etc/cron.d/: owner=root, perm=755
/etc/cron.daily/: owner=root, perm=755
/etc/cron.hourly/: owner=root, perm=755
/etc/cron.weekly/: owner=root, perm=755
/etc/cron.monthly/: owner=root, perm=755
```


### U-42 불필요한 RPC 서비스 비활성화

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [취약] |
| After  | [취약] |
| 상태   | **잔존 (수동 조치 필요)** |

**As-is (조치 전 점검 결과)**

```
활성화된 RPC 서비스: rpcbind (불필요한 경우 비활성화 권고)
```

**To-be (조치 후 재점검 결과)**

```
활성화된 RPC 서비스: rpcbind (불필요한 경우 비활성화 권고)
```


### U-58 불필요한 SNMP 서비스 점검

| 속성 | 값 |
|---|---|
| 중요도 | 중 |
| Before | [취약] |
| After  | [취약] |
| 상태   | **잔존 (수동 조치 필요)** |

**As-is (조치 전 점검 결과)**

```
snmpd 패키지: ii  snmpd          5.9.1+dfsg-1ubuntu2.9 amd64        SNMP (Simple Network Management Protocol) agents
snmpd 서비스 상태: active (SNMP 미사용 시 비활성화 필요)
```

**To-be (조치 후 재점검 결과)**

```
snmpd 패키지: ii  snmpd          5.9.1+dfsg-1ubuntu2.9 amd64        SNMP (Simple Network Management Protocol) agents
snmpd 서비스 상태: active (SNMP 미사용 시 비활성화 필요)
```


### U-59 안전한 SNMP 버전 사용

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [취약] |
| After  | [취약] |
| 상태   | **잔존 (수동 조치 필요)** |

**As-is (조치 전 점검 결과)**

```
SNMPv3 사용자: rouser authPrivUser authpriv -V systemonly
v1/v2 Community: rocommunity  public default -V systemonly
rocommunity6 public default -V systemonly (v1/v2 사용 중 또는 v3 미설정)
```

**To-be (조치 후 재점검 결과)**

```
SNMPv3 사용자: rouser authPrivUser authpriv -V systemonly
v1/v2 Community: rocommunity  public default -V systemonly
rocommunity6 public default -V systemonly (v1/v2 사용 중 또는 v3 미설정)
```


### U-60 SNMP Community String 복잡성

| 속성 | 값 |
|---|---|
| 중요도 | 중 |
| Before | [취약] |
| After  | [취약] |
| 상태   | **잔존 (수동 조치 필요)** |

**As-is (조치 전 점검 결과)**

```
Community String: public
public
취약 Community: public(기본값) public(기본값)
```

**To-be (조치 후 재점검 결과)**

```
Community String: public
public
취약 Community: public(기본값) public(기본값)
```


\newpage

# 5. 신규 발견 취약 항목 (Regression)

조치 후 새롭게 취약으로 전환된 항목입니다. 조치 부작용 가능성이 있어 즉시 재검토가 필요합니다.

_(신규 발견 항목 없음 — regression zero)_

\newpage

# 6. 양호 항목 (변화 없음)

조치 전후 모두 양호로 판정된 항목입니다. 현재 설정이 KISA 2026 기준을 충족합니다.


### U-04 비밀번호 파일 보호

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [양호] |
| After  | [양호] |
| 상태   | **양호 유지** |

**As-is (조치 전 점검 결과)**

```
/etc/shadow 파일: 존재
/etc/passwd 샘플 (첫 3행): root:x:...
daemon:x:...
bin:x:...
shadow 비밀번호 사용 중, 모든 계정 두 번째 필드='x'
```

**To-be (조치 후 재점검 결과)**

```
/etc/shadow 파일: 존재
/etc/passwd 샘플 (첫 3행): root:x:...
daemon:x:...
bin:x:...
shadow 비밀번호 사용 중, 모든 계정 두 번째 필드='x'
```


### U-05 root 이외의 UID=0 금지

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [양호] |
| After  | [양호] |
| 상태   | **양호 유지** |

**As-is (조치 전 점검 결과)**

```
UID=0인 계정 목록: root(UID=0)
root 외에 UID=0인 계정 없음
```

**To-be (조치 후 재점검 결과)**

```
UID=0인 계정 목록: root(UID=0)
root 외에 UID=0인 계정 없음
```


### U-07 불필요한 계정 제거

| 속성 | 값 |
|---|---|
| 중요도 | 하 |
| Before | [양호] |
| After  | [양호] |
| 상태   | **양호 유지** |

**As-is (조치 전 점검 결과)**

```
점검 대상 계정: games news uucp lp irc gnats pcap
로그인 가능 불필요 계정: 없음
비활성화(nologin) 처리 계정: games (shell=/usr/sbin/nologin) news (shell=/usr/sbin/nologin) uucp (shell=/usr/sbin/nologin) lp (shell=/usr/sbin/nologin) irc (shell=/usr/sbin/nologin) gnats (shell=/usr/sbin/nologin)
```

**To-be (조치 후 재점검 결과)**

```
점검 대상 계정: games news uucp lp irc gnats pcap
로그인 가능 불필요 계정: 없음
비활성화(nologin) 처리 계정: games (shell=/usr/sbin/nologin) news (shell=/usr/sbin/nologin) uucp (shell=/usr/sbin/nologin) lp (shell=/usr/sbin/nologin) irc (shell=/usr/sbin/nologin) gnats (shell=/usr/sbin/nologin)
```


### U-08 관리자 그룹 최소 계정

| 속성 | 값 |
|---|---|
| 중요도 | 중 |
| Before | [양호] |
| After  | [양호] |
| 상태   | **양호 유지** |

**As-is (조치 전 점검 결과)**

```
sudo 그룹: sands
wheel 그룹: 없음
adm 그룹: syslog,sands
[안내] 위 그룹 구성원이 최소화되어 있는지 운영자가 직접 확인 필요
```

**To-be (조치 후 재점검 결과)**

```
sudo 그룹: sands
wheel 그룹: sands
adm 그룹: syslog,sands
[안내] 위 그룹 구성원이 최소화되어 있는지 운영자가 직접 확인 필요
```


### U-09 계정이 존재하지 않는 GID 금지

| 속성 | 값 |
|---|---|
| 중요도 | 하 |
| Before | [양호] |
| After  | [양호] |
| 상태   | **양호 유지** |

**As-is (조치 전 점검 결과)**

```
고아 GID (그룹 미존재) 계정: 없음
```

**To-be (조치 후 재점검 결과)**

```
고아 GID (그룹 미존재) 계정: 없음
```


### U-10 동일한 UID 금지

| 속성 | 값 |
|---|---|
| 중요도 | 중 |
| Before | [양호] |
| After  | [양호] |
| 상태   | **양호 유지** |

**As-is (조치 전 점검 결과)**

```
중복 UID 발견: 없음
```

**To-be (조치 후 재점검 결과)**

```
중복 UID 발견: 없음
```


### U-11 사용자 Shell 점검

| 속성 | 값 |
|---|---|
| 중요도 | 하 |
| Before | [양호] |
| After  | [양호] |
| 상태   | **양호 유지** |

**As-is (조치 전 점검 결과)**

```
로그인 가능 쉘을 가진 시스템 계정(UID<1000): 없음
```

**To-be (조치 후 재점검 결과)**

```
로그인 가능 쉘을 가진 시스템 계정(UID<1000): 없음
```


### U-13 안전한 비밀번호 암호화 알고리즘

| 속성 | 값 |
|---|---|
| 중요도 | 중 |
| Before | [양호] |
| After  | [양호] |
| 상태   | **양호 유지** |

**As-is (조치 전 점검 결과)**

```
/etc/login.defs ENCRYPT_METHOD: SHA512
/etc/pam.d/common-password 해시: yescrypt
/etc/shadow 실제 해시 접두사: $y$j9 → yescrypt (Ubuntu 22.04 기본, SHA-512 이상 수준)
```

**To-be (조치 후 재점검 결과)**

```
/etc/login.defs ENCRYPT_METHOD: SHA512
/etc/pam.d/common-password 해시: yescrypt
/etc/shadow 실제 해시 접두사: $y$j9 → yescrypt (Ubuntu 22.04 기본, SHA-512 이상 수준)
```


### U-14 root PATH 디렉터리 권한 설정

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [양호] |
| After  | [양호] |
| 상태   | **양호 유지** |

**As-is (조치 전 점검 결과)**

```
root PATH: /usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/games:/usr/local/games:/snap/bin
'.' 포함 여부: 미발견
```

**To-be (조치 후 재점검 결과)**

```
root PATH: /usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/games:/usr/local/games:/snap/bin
'.' 포함 여부: 미발견
```


### U-16 /etc/passwd 소유자 및 권한

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [양호] |
| After  | [양호] |
| 상태   | **양호 유지** |

**As-is (조치 전 점검 결과)**

```
파일: /etc/passwd | 소유자: root | 권한: 644 (644 이하, root 소유 필요)
```

**To-be (조치 후 재점검 결과)**

```
파일: /etc/passwd | 소유자: root | 권한: 644 (644 이하, root 소유 필요)
```


### U-17 시스템 시작 스크립트 권한 설정

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [양호] |
| After  | [양호] |
| 상태   | **양호 유지** |

**As-is (조치 전 점검 결과)**

```
/etc/init.d 디렉터리 권한 이상 스크립트: 없음 (정상)
```

**To-be (조치 후 재점검 결과)**

```
/etc/init.d 디렉터리 권한 이상 스크립트: 없음 (정상)
```


### U-18 /etc/shadow 소유자 및 권한

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [양호] |
| After  | [양호] |
| 상태   | **양호 유지** |

**As-is (조치 전 점검 결과)**

```
파일: /etc/shadow | 소유자: root | 그룹: shadow | 권한: 640 (400 이하 권고, Ubuntu는 640/root:shadow 허용)
```

**To-be (조치 후 재점검 결과)**

```
파일: /etc/shadow | 소유자: root | 그룹: shadow | 권한: 640 (400 이하 권고, Ubuntu는 640/root:shadow 허용)
```


### U-19 /etc/hosts 소유자 및 권한

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [양호] |
| After  | [양호] |
| 상태   | **양호 유지** |

**As-is (조치 전 점검 결과)**

```
파일: /etc/hosts | 소유자: root | 권한: 644 (644 이하, root 소유 필요)
```

**To-be (조치 후 재점검 결과)**

```
파일: /etc/hosts | 소유자: root | 권한: 644 (644 이하, root 소유 필요)
```


### U-22 /etc/services 소유자 및 권한

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [양호] |
| After  | [양호] |
| 상태   | **양호 유지** |

**As-is (조치 전 점검 결과)**

```
파일: /etc/services | 소유자: root | 권한: 644 (644 이하, root/bin/sys 소유 필요)
```

**To-be (조치 후 재점검 결과)**

```
파일: /etc/services | 소유자: root | 권한: 644 (644 이하, root/bin/sys 소유 필요)
```


### U-24 사용자 환경변수 파일 소유자 및 권한

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [양호] |
| After  | [양호] |
| 상태   | **양호 유지** |

**As-is (조치 전 점검 결과)**

```
점검 파일 수: 15
취약 항목: 없음
[조치 주의] chmod o-w 사용할 것 — chmod 644/600 사용 시 실행권한 손상으로 bash 초기화 실패
```

**To-be (조치 후 재점검 결과)**

```
점검 파일 수: 15
취약 항목: 없음
[조치 주의] chmod o-w 사용할 것 — chmod 644/600 사용 시 실행권한 손상으로 bash 초기화 실패
```


### U-26 /dev 불법 device 파일 점검

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [양호] |
| After  | [양호] |
| 상태   | **양호 유지** |

**As-is (조치 전 점검 결과)**

```
/dev 내 일반 파일(fake device): 없음
```

**To-be (조치 후 재점검 결과)**

```
/dev 내 일반 파일(fake device): 없음
```


### U-27 .rhosts, hosts.equiv 사용 금지

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [양호] |
| After  | [양호] |
| 상태   | **양호 유지** |

**As-is (조치 전 점검 결과)**

```
/etc/hosts.equiv: 파일 없음 (양호)
/root/.rhosts: 파일 없음 (양호)
```

**To-be (조치 후 재점검 결과)**

```
/etc/hosts.equiv: 파일 없음 (양호)
/root/.rhosts: 파일 없음 (양호)
```


### U-30 UMASK 설정 관리

| 속성 | 값 |
|---|---|
| 중요도 | 중 |
| Before | [양호] |
| After  | [양호] |
| 상태   | **양호 유지** |

**As-is (조치 전 점검 결과)**

```
UMASK 설정 파일: /etc/login.defs
UMASK 값: 022 (022 이상 권고)
```

**To-be (조치 후 재점검 결과)**

```
UMASK 설정 파일: /etc/login.defs
UMASK 값: 022 (022 이상 권고)
```


### U-31 홈 디렉토리 소유자 및 권한

| 속성 | 값 |
|---|---|
| 중요도 | 중 |
| Before | [양호] |
| After  | [양호] |
| 상태   | **양호 유지** |

**As-is (조치 전 점검 결과)**

```
홈 디렉토리 소유자/권한 이상: 없음
```

**To-be (조치 후 재점검 결과)**

```
홈 디렉토리 소유자/권한 이상: 없음
```


### U-32 홈 디렉토리 존재 여부

| 속성 | 값 |
|---|---|
| 중요도 | 중 |
| Before | [양호] |
| After  | [양호] |
| 상태   | **양호 유지** |

**As-is (조치 전 점검 결과)**

```
홈 디렉토리 미존재 계정: 없음
```

**To-be (조치 후 재점검 결과)**

```
홈 디렉토리 미존재 계정: 없음
```


### U-33 숨겨진 파일 및 디렉토리 점검

| 속성 | 값 |
|---|---|
| 중요도 | 하 |
| Before | [양호] |
| After  | [양호] |
| 상태   | **양호 유지** |

**As-is (조치 전 점검 결과)**

```
편집기 스왑 파일 (.swp/.swo): 없음
기타 숨김 파일 (참고용, 취약 판정 제외): /etc/elasticsearch-node-2/.elasticsearch.keystore.initial_md5sum
/etc/cron.weekly/.placeholder
/etc/sensors.d/.placeholder
/etc/elasticsearch/.elasticsearch.keystore.initial_md5sum
/etc/cron.hourly/.placeholder
/etc/cron.monthly/.placeholder
/etc/cron.daily/.placeholder
/etc/cron.d/.placeholder
/etc/skel/.bashrc
/etc/skel/.bash_logout
/etc/skel/.profile
/etc/elasticsearch-node-1/.elasticsearch.keystore.initial_md5sum
/etc/.pwd.lock
/usr/src/linux-headers-5.15.0-177-generic/.config
/usr/src/linux-headers-5.15.0-177-generic/.missing-syscalls.d
/usr/src/linux-headers-5.15.0-177-generic/.gitignore
/usr/src/nvidia-535.288.01/.nvidia-uvm.o.cmd
/usr/src/nvidia-535.288.01/.Module.symvers.cmd
/usr/src/nvidia-535.288.01/.nvidia-peermem.mod.o.cmd
/usr/src/nvidia-535.288.01/.nvidia.mod.o.cmd
[안내] 스왑 파일은 편집 중 비정상 종료 시 생성됨 — 직접 삭제 가능
```

**To-be (조치 후 재점검 결과)**

```
편집기 스왑 파일 (.swp/.swo): 없음
기타 숨김 파일 (참고용, 취약 판정 제외): /etc/elasticsearch-node-2/.elasticsearch.keystore.initial_md5sum
/etc/cron.weekly/.placeholder
/etc/sensors.d/.placeholder
/etc/elasticsearch/.elasticsearch.keystore.initial_md5sum
/etc/cron.hourly/.placeholder
/etc/cron.monthly/.placeholder
/etc/cron.daily/.placeholder
/etc/cron.d/.placeholder
/etc/skel/.bashrc
/etc/skel/.bash_logout
/etc/skel/.profile
/etc/elasticsearch-node-1/.elasticsearch.keystore.initial_md5sum
/etc/.pwd.lock
/usr/src/linux-headers-5.15.0-177-generic/.config
/usr/src/linux-headers-5.15.0-177-generic/.missing-syscalls.d
/usr/src/linux-headers-5.15.0-177-generic/.gitignore
/usr/src/nvidia-535.288.01/.nvidia-uvm.o.cmd
/usr/src/nvidia-535.288.01/.Module.symvers.cmd
/usr/src/nvidia-535.288.01/.nvidia-peermem.mod.o.cmd
/usr/src/nvidia-535.288.01/.nvidia.mod.o.cmd
[안내] 스왑 파일은 편집 중 비정상 종료 시 생성됨 — 직접 삭제 가능
```


### U-61 SNMP Access Control 설정

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [양호] |
| After  | [양호] |
| 상태   | **양호 유지** |

**As-is (조치 전 점검 결과)**

```
SNMP 접근 제어 설정: agentaddress  127.0.0.1,[::1]
view   systemonly  included   .1.3.6.1.2.1.1
view   systemonly  included   .1.3.6.1.2.1.25.1
```

**To-be (조치 후 재점검 결과)**

```
SNMP 접근 제어 설정: agentaddress  127.0.0.1,[::1]
view   systemonly  included   .1.3.6.1.2.1.1
view   systemonly  included   .1.3.6.1.2.1.25.1
```


### U-62 로그인 시 경고 메시지 설정

| 속성 | 값 |
|---|---|
| 중요도 | 하 |
| Before | [양호] |
| After  | [양호] |
| 상태   | **양호 유지** |

**As-is (조치 전 점검 결과)**

```
/etc/issue: ************************************************************************
*                      SANDS LAB Inc. NDR SYSTEM                       *
/etc/issue.net: ************************************************************************
*                      SANDS LAB Inc. NDR SYSTEM                       *
SSH Banner: Banner /etc/issue.net
```

**To-be (조치 후 재점검 결과)**

```
/etc/issue: ************************************************************************
*                      SANDS LAB Inc. NDR SYSTEM                       *
/etc/issue.net: ************************************************************************
*                      SANDS LAB Inc. NDR SYSTEM                       *
SSH Banner: Banner /etc/issue.net
```


### U-63 sudo 명령어 접근 관리

| 속성 | 값 |
|---|---|
| 중요도 | 중 |
| Before | [양호] |
| After  | [양호] |
| 상태   | **양호 유지** |

**As-is (조치 전 점검 결과)**

```
/etc/sudoers: owner=root, perm=440 (640 이하, root 소유 필요)
위험 sudo 규칙(NOPASSWD 등): 
```

**To-be (조치 후 재점검 결과)**

```
/etc/sudoers: owner=root, perm=440 (640 이하, root 소유 필요)
위험 sudo 규칙(NOPASSWD 등): 
```


### U-64 최신 보안 패치 적용

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [양호] |
| After  | [양호] |
| 상태   | **양호 유지** |

**As-is (조치 전 점검 결과)**

```
업그레이드 가능한 패키지 수: 5
보안 업데이트 대기 수: 0
apt 마지막 업데이트: 2026-05-14 15:55:37
현재 커널: 5.15.0-177-generic
보안 업데이트 패키지(상위 10개):
없음
[안내] 일반 업데이트 5개 대기 중 (보안 업데이트 없음 확인됨)
```

**To-be (조치 후 재점검 결과)**

```
업그레이드 가능한 패키지 수: 5
보안 업데이트 대기 수: 0
apt 마지막 업데이트: 2026-05-14 15:55:37
현재 커널: 5.15.0-177-generic
보안 업데이트 패키지(상위 10개):
없음
[안내] 일반 업데이트 5개 대기 중 (보안 업데이트 없음 확인됨)
```


### U-65 NTP 및 시각 동기화 설정

| 속성 | 값 |
|---|---|
| 중요도 | 중 |
| Before | [양호] |
| After  | [양호] |
| 상태   | **양호 유지** |

**As-is (조치 전 점검 결과)**

```
systemd-timesyncd: 활성
timedatectl:                 Time zone: Asia/Seoul (KST, +0900)
System clock synchronized: yes
NTP service: active
```

**To-be (조치 후 재점검 결과)**

```
systemd-timesyncd: 활성
timedatectl:                 Time zone: Asia/Seoul (KST, +0900)
System clock synchronized: yes
NTP service: active
```


### U-66 정책에 따른 시스템 로깅 설정

| 속성 | 값 |
|---|---|
| 중요도 | 중 |
| Before | [양호] |
| After  | [양호] |
| 상태   | **양호 유지** |

**As-is (조치 전 점검 결과)**

```
rsyslog: 활성
/var/log/syslog: 4.5M, 최종수정=2026-05-19 17:18:18
/var/log/auth.log: 1.7M, 최종수정=2026-05-19 17:18:06
/var/log/kern.log: 120K, 최종수정=2026-05-19 16:57:23
/var/log/mail.log: 미존재
/etc/rsyslog.conf 주요 설정: module(load="imuxsock") # provides support for local system logging
module(load="imklog" permitnonkernelfacility="on")
$ActionFileDefaultTemplate RSYSLOG_TraditionalFileFormat
$RepeatedMsgReduction on
$FileOwner syslog
$FileGroup adm
$FileCreateMode 0640
$DirCreateMode 0755
$Umask 0022
$PrivDropToUser syslog
```

**To-be (조치 후 재점검 결과)**

```
rsyslog: 활성
/var/log/syslog: 4.7M, 최종수정=2026-05-19 17:20:31
/var/log/auth.log: 1.7M, 최종수정=2026-05-19 17:20:12
/var/log/kern.log: 120K, 최종수정=2026-05-19 16:57:23
/var/log/mail.log: 미존재
/etc/rsyslog.conf 주요 설정: module(load="imuxsock") # provides support for local system logging
module(load="imklog" permitnonkernelfacility="on")
$ActionFileDefaultTemplate RSYSLOG_TraditionalFileFormat
$RepeatedMsgReduction on
$FileOwner syslog
$FileGroup adm
$FileCreateMode 0640
$DirCreateMode 0755
$Umask 0022
$PrivDropToUser syslog
```


\newpage

# 7. N/A 항목 (해당 없음)

서비스 미구동 / 미설치 등으로 점검 대상이 아닌 항목입니다.


### U-20 /etc/

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [N/A] |
| After  | [N/A] |
| 상태   | **해당 없음** |

**As-is (조치 전 점검 결과)**

```
inetd/xinetd 미설치 (관련 설정 파일 없음)
```

**To-be (조치 후 재점검 결과)**

```
inetd/xinetd 미설치 (관련 설정 파일 없음)
```


### U-29 hosts.lpd 파일 소유자 및 권한

| 속성 | 값 |
|---|---|
| 중요도 | 하 |
| Before | [N/A] |
| After  | [N/A] |
| 상태   | **해당 없음** |

**As-is (조치 전 점검 결과)**

```
/etc/hosts.lpd 파일 없음 (양호)
```

**To-be (조치 후 재점검 결과)**

```
/etc/hosts.lpd 파일 없음 (양호)
```


### U-34 Finger 서비스 비활성화

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [N/A] |
| After  | [N/A] |
| 상태   | **해당 없음** |

**As-is (조치 전 점검 결과)**

```
finger 패키지: 미설치
finger 서비스 상태: not-installed
```

**To-be (조치 후 재점검 결과)**

```
finger 패키지: 미설치
finger 서비스 상태: not-installed
```


### U-35 공유 서비스 익명 접근 제한

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [N/A] |
| After  | [N/A] |
| 상태   | **해당 없음** |

**As-is (조치 전 점검 결과)**

```
Samba 미설치
```

**To-be (조치 후 재점검 결과)**

```
Samba 미설치
```


### U-36 r 계열 서비스 비활성화

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [N/A] |
| After  | [N/A] |
| 상태   | **해당 없음** |

**As-is (조치 전 점검 결과)**

```
r 계열 서비스 패키지: 미설치
활성화된 r 계열 서비스: 없음
```

**To-be (조치 후 재점검 결과)**

```
r 계열 서비스 패키지: 미설치
활성화된 r 계열 서비스: 없음
```


### U-38 DoS 취약 서비스 비활성화

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [N/A] |
| After  | [N/A] |
| 상태   | **해당 없음** |

**As-is (조치 전 점검 결과)**

```
활성화된 DoS 취약 서비스: 없음 (해당 서비스 미설치/비활성)
```

**To-be (조치 후 재점검 결과)**

```
활성화된 DoS 취약 서비스: 없음 (해당 서비스 미설치/비활성)
```


### U-39 불필요한 NFS 서비스 비활성화

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [N/A] |
| After  | [N/A] |
| 상태   | **해당 없음** |

**As-is (조치 전 점검 결과)**

```
nfs-server 상태: not-installed
nfs-kernel-server 상태: not-installed (NFS 서비스 비활성화)
```

**To-be (조치 후 재점검 결과)**

```
nfs-server 상태: not-installed
nfs-kernel-server 상태: not-installed (NFS 서비스 비활성화)
```


### U-40 NFS 접근 통제

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [N/A] |
| After  | [N/A] |
| 상태   | **해당 없음** |

**As-is (조치 전 점검 결과)**

```
/etc/exports 없음 (NFS 미사용)
```

**To-be (조치 후 재점검 결과)**

```
/etc/exports 없음 (NFS 미사용)
```


### U-41 불필요한 automountd 제거

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [N/A] |
| After  | [N/A] |
| 상태   | **해당 없음** |

**As-is (조치 전 점검 결과)**

```
autofs 서비스 상태: not-installed (autofs 비활성화 상태)
```

**To-be (조치 후 재점검 결과)**

```
autofs 서비스 상태: not-installed (autofs 비활성화 상태)
```


### U-43 NIS/NIS+ 서비스 점검

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [N/A] |
| After  | [N/A] |
| 상태   | **해당 없음** |

**As-is (조치 전 점검 결과)**

```
NIS 패키지: 미설치
활성화된 NIS 서비스: 없음 (NIS 비활성화 상태)
```

**To-be (조치 후 재점검 결과)**

```
NIS 패키지: 미설치
활성화된 NIS 서비스: 없음 (NIS 비활성화 상태)
```


### U-44 tftp, talk 서비스 비활성화

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [N/A] |
| After  | [N/A] |
| 상태   | **해당 없음** |

**As-is (조치 전 점검 결과)**

```
tftp 패키지: 미설치, talk 패키지: 미설치
활성화된 서비스: 없음 (서비스 비활성화 상태)
```

**To-be (조치 후 재점검 결과)**

```
tftp 패키지: 미설치, talk 패키지: 미설치
활성화된 서비스: 없음 (서비스 비활성화 상태)
```


### U-45 메일 서비스 버전 점검

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [N/A] |
| After  | [N/A] |
| 상태   | **해당 없음** |

**As-is (조치 전 점검 결과)**

```
활성화된 메일 서비스: 없음
버전 정보: N/A (메일 서비스 미사용)
```

**To-be (조치 후 재점검 결과)**

```
활성화된 메일 서비스: 없음
버전 정보: N/A (메일 서비스 미사용)
```


### U-46 일반 사용자의 메일 서비스 실행 방지

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [N/A] |
| After  | [N/A] |
| 상태   | **해당 없음** |

**As-is (조치 전 점검 결과)**

```
메일 서비스 프로세스 실행 계정: 메일 서비스 미실행
```

**To-be (조치 후 재점검 결과)**

```
메일 서비스 프로세스 실행 계정: 메일 서비스 미실행
```


### U-47 스팸 메일 릴레이 제한

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [N/A] |
| After  | [N/A] |
| 상태   | **해당 없음** |

**As-is (조치 전 점검 결과)**

```
메일 서비스(postfix) 비활성화 상태
```

**To-be (조치 후 재점검 결과)**

```
메일 서비스(postfix) 비활성화 상태
```


### U-48 SMTP expn, vrfy 명령어 제한

| 속성 | 값 |
|---|---|
| 중요도 | 중 |
| Before | [N/A] |
| After  | [N/A] |
| 상태   | **해당 없음** |

**As-is (조치 전 점검 결과)**

```
메일 서비스(postfix) 비활성화 상태
```

**To-be (조치 후 재점검 결과)**

```
메일 서비스(postfix) 비활성화 상태
```


### U-49 DNS 보안 버전 패치

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [N/A] |
| After  | [N/A] |
| 상태   | **해당 없음** |

**As-is (조치 전 점검 결과)**

```
DNS 서비스(named/bind9) 비활성화 상태
```

**To-be (조치 후 재점검 결과)**

```
DNS 서비스(named/bind9) 비활성화 상태
```


### U-50 DNS Zone Transfer 설정

| 속성 | 값 |
|---|---|
| 중요도 | 상 |
| Before | [N/A] |
| After  | [N/A] |
| 상태   | **해당 없음** |

**As-is (조치 전 점검 결과)**

```
DNS 서비스(bind9) 비활성화 상태
```

**To-be (조치 후 재점검 결과)**

```
DNS 서비스(bind9) 비활성화 상태
```


### U-51 DNS 동적 업데이트 설정 금지

| 속성 | 값 |
|---|---|
| 중요도 | 중 |
| Before | [N/A] |
| After  | [N/A] |
| 상태   | **해당 없음** |

**As-is (조치 전 점검 결과)**

```
DNS 서비스(bind9) 비활성화 상태
```

**To-be (조치 후 재점검 결과)**

```
DNS 서비스(bind9) 비활성화 상태
```


### U-52 Telnet 서비스 비활성화

| 속성 | 값 |
|---|---|
| 중요도 | 중 |
| Before | [N/A] |
| After  | [N/A] |
| 상태   | **해당 없음** |

**As-is (조치 전 점검 결과)**

```
telnet 서비스: not-installed, telnetd: not-installed
inetd 기반 telnet: 없음
TCP 23번 포트 Listen: 없음 (Telnet 비활성화)
```

**To-be (조치 후 재점검 결과)**

```
telnet 서비스: not-installed, telnetd: not-installed
inetd 기반 telnet: 없음
TCP 23번 포트 Listen: 없음 (Telnet 비활성화)
```


### U-53 FTP 서비스 정보 노출 제한

| 속성 | 값 |
|---|---|
| 중요도 | 하 |
| Before | [N/A] |
| After  | [N/A] |
| 상태   | **해당 없음** |

**As-is (조치 전 점검 결과)**

```
FTP 서비스(vsftpd/proftpd) 비활성화 상태
```

**To-be (조치 후 재점검 결과)**

```
FTP 서비스(vsftpd/proftpd) 비활성화 상태
```


### U-54 암호화되지 않은 FTP 비활성화

| 속성 | 값 |
|---|---|
| 중요도 | 중 |
| Before | [N/A] |
| After  | [N/A] |
| 상태   | **해당 없음** |

**As-is (조치 전 점검 결과)**

```
vsftpd 상태: not-installed
TCP 21번 포트 Listen: 없음 (FTP 비활성화 상태)
```

**To-be (조치 후 재점검 결과)**

```
vsftpd 상태: not-installed
TCP 21번 포트 Listen: 없음 (FTP 비활성화 상태)
```


### U-55 FTP 계정 Shell 제한

| 속성 | 값 |
|---|---|
| 중요도 | 중 |
| Before | [N/A] |
| After  | [N/A] |
| 상태   | **해당 없음** |

**As-is (조치 전 점검 결과)**

```
FTP 서비스 미설치
```

**To-be (조치 후 재점검 결과)**

```
FTP 서비스 미설치
```


### U-56 FTP 서비스 접근 제어 설정

| 속성 | 값 |
|---|---|
| 중요도 | 하 |
| Before | [N/A] |
| After  | [N/A] |
| 상태   | **해당 없음** |

**As-is (조치 전 점검 결과)**

```
FTP 서비스 비활성화 상태
```

**To-be (조치 후 재점검 결과)**

```
FTP 서비스 비활성화 상태
```


### U-57 Ftpusers 파일 설정

| 속성 | 값 |
|---|---|
| 중요도 | 중 |
| Before | [N/A] |
| After  | [N/A] |
| 상태   | **해당 없음** |

**As-is (조치 전 점검 결과)**

```
FTP 서비스 비활성화 상태
```

**To-be (조치 후 재점검 결과)**

```
FTP 서비스 비활성화 상태
```


\newpage

# 8. 부록

## 8.1 예외 디렉토리/파일 정책

KISA 2026 가이드의 find 기반 점검(U-23 SUID/SGID, U-25 world-writable 등)에서 다음 경로는 점검 대상에서 제외되었습니다.

```
   /proc /sys /dev /run /tmp /var/tmp /data /logs /application /opt/mnx /mnt /media /var/lib/docker /var/lib/containerd
```

**사유:**

- `/proc, /sys, /dev, /run` — Linux 가상 파일시스템 (수정 불가)
- `/tmp, /var/tmp` — 정상적으로 world-writable + sticky bit 운영 디렉토리
- `/data, /logs, /application, /opt/mnx` — MNX 운영 데이터·로그 디렉토리. suricata/mnxcapture 등 데몬이 다른 UID로 로그를 적재하기 위해 0775/0777 권한이 정상 동작에 필요
- `/mnt, /media, /var/lib/docker, /var/lib/containerd` — 외부 마운트 / 컨테이너 레이어 (호스트 점검 범위 밖)

## 8.2 백업 / 로그 위치

| 종류 | 경로 |
|---|---|
| Before 리포트 | `/mnxmc/infra_audit/tmp/infra_audit_report_20260519_171719.txt` |
| After 리포트 | `/mnxmc/infra_audit/tmp/infra_audit_report_20260519_171928.txt` |
| Final 비교 리포트 | `/mnxmc/infra_audit/tmp/infra_remediate_final_20260519_171848.txt` |
| 조치 로그 | `/mnxmc/infra_audit/tmp/infra_remediate_20260519_171848.log` |
| 항목별 상세 리포트 | `/mnxmc/infra_audit/tmp/infra_remediate_report_20260519_172309.txt` |
| 설정 파일 백업 | `/mnxmc/infra_audit/tmp/backup_20260519_171848/` |

## 8.3 점검 도구 버전

| 도구 | 버전 |
|---|---|
| infra_audit.sh | 2.0.0 (2026-03-26) |
| infra_remediate.sh | 3.0.0 (2026-03-26) |
| generate_pdf_report.sh | 1.0.0 (2026-05-19) |
| pandoc | 2.9.2.1 |
| xelatex | 2022/dev/Debian) |

---

*본 보고서는 자동 생성되었습니다. 조치 명령 적용 전 반드시 운영 환경 영향을 검토하시기 바랍니다.*
