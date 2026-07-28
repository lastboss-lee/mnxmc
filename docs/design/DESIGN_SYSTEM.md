# MNXMC Design System — Enterprise Network Appliance TUI

> 대상: MNXMC(MNX Management Console) 상용 제품 UI 일관화
> 기준: "6개월 뒤 다른 개발자가 유지보수 가능한가" / 공통 컴포넌트 우선 설계
> 참고 철학: Cisco FMC · FortiManager · VMware ESXi · Palo Alto · Sophos · TrueNAS SCALE
> (철학만 참고, 복사하지 않음 — MNXMC 고유 디자인 시스템 구축)

> **구현 현황 (v2.3.1, 2026-07-28):** 본 설계는 `feature/refactor-ui` 브랜치에서
> **Phase 1~29로 전량 구현 완료**되었다. §1의 문제(P1~P8)는 모두 해소되었고,
> 아래 §8 Migration Plan은 실제 커밋 이력으로 갱신되었다. 최초 계획(P1~P7)에 더해
> 실전 튜닝(헤더 라이브 지시자·active-pane 포커스·Capture 에디터·Network 모달 등,
> Phase 8~27)과 Service Manager 서비스 목록 갱신·사이드바 긴 이름 줄바꿈(Phase 28),
> Capture 인터페이스 에디터 키보드 네비/None 확인 효과·suricata.yaml 동기화 뷰(Phase 29)가 추가되었다.

---

## 1. 현재 UI 문제점 분석 *(→ v2.3.0에서 전량 해소, "해결" 열 참고)*

| # | 문제 | 근거 | 영향 | 해결(Phase) |
|---|------|------|------|-------------|
| P1 | **화면마다 2패널 CSS를 복붙** | 12개 화면이 좌측 25% ListView + 우측 패널 인라인 CSS 반복 | 톤 불일치, 유지보수 시 12곳 수정 | ✅ `BaseScreen` 이관(P2~5,14) |
| P2 | **공통 골격 부재** | Header/Sidebar/Footer가 화면마다 제각각(있거나 없거나) | 제품 일체감 결여 | ✅ `AppShell`+4구획(P2) |
| P3 | **미사용 위젯 데드코드** | `MenuList`,`SimpleMenu`,`TwoPanelLayout`,`LeftPanel`,`RightPanel`,`MenuTitle` 전부 미참조 | 혼란, 코드량 증가 | ✅ 데드코드 제거(P6,13) |
| P4 | **도달 불가 화면** | `ElasticsearchScreen`,`KafkaScreen`,`FirewallScreen` — 기능은 `logs.py`에 임베드 | 중복 구현 | ✅ 화면 제거(P6) |
| P5 | **색상/간격 하드코딩** | `#0c0c0c`, `#1a1a1a` 등 화면별 리터럴 산재 | 테마 변경 불가, 일관성 없음 | ✅ `tokens.py`+`theme.tcss` 단일화(P1~) |
| P6 | **인증 클래스 3중 중복** | `AuthenticationManager`가 `utils/auth.py`·`login.py`·`service.py`에 각각 정의 | 로직 분기 위험 | ✅ 통합 + su fallback 차단(P6,12) |
| P7 | **상태 표현 제각각** | 서비스/헬스 상태 아이콘·색상 규칙 화면마다 다름 | 색맹 접근성·일관성 저하 | ✅ `status_badge`·라이브 헤더(P15~17) |
| P8 | **Config 화면이 JSON 뷰어 느낌** | `mnx_config.py`가 설정 페이지가 아닌 파일 편집기 UX | 엔터프라이즈 제품 기대치 미달 | ✅ 설정페이지화 + Capture 에디터(P4,10,21~23) |

---

## 2. 새로운 Design System 설계 원칙

1. **하나의 제품처럼** — 모든 화면 동일한 `Header / Sidebar / Content / Footer` 구조.
2. **공통 컴포넌트 우선** — 화면은 컴포넌트를 조립만 한다. 스타일은 화면에 두지 않는다.
3. **단일 소스** — 색상/간격/글리프는 `tokens.py`(Python) + `theme.tcss`(CSS) 한 쌍에서만 정의.
4. **접근성** — 상태는 색상 단독이 아닌 **(색상 + 글리프)** 로 표현(색맹 대응).
5. **키보드 온리** — F-Key / Arrow / Tab / ESC / Enter 만으로 전 기능 수행.
6. **기능 불변** — UI/UX만 개선, 백엔드·동작·성능은 유지 또는 개선.

---

## 3. Theme 정의 (`app/ui/tokens.py` + `app/ui/theme.tcss`)

### Color System (Terminal / Color-Blind Friendly)

| 역할 | 토큰 | Hex | 비고 |
|------|------|-----|------|
| Background | `BG` | `#0b0f14` | near-black |
| Surface | `SURFACE` | `#11161d` | 카드/패널 |
| Border | `BORDER` | `#2a3440` | |
| Text | `TEXT` | `#e6edf3` | |
| Text Muted | `TEXT_MUTED` | `#8b98a5` | 라벨 |
| **Primary** | `PRIMARY` | `#00aeef` | MNX 시그니처 시안 |
| Accent | `ACCENT` | `#33c9ff` | |
| Success ✔ | `SUCCESS` | `#3fb950` | |
| Info ℹ | `INFO` | `#58a6ff` | |
| Warning ▲ | `WARNING` | `#d29922` | |
| Critical ✖ | `CRITICAL` | `#f85149` | |
| Disabled ○ | `DISABLED` | `#5a6673` | |
| Hover | `HOVER` | `#1c2530` | |
| Selected | `SELECTED_BG/FG` | `#00aeef` / `#04141b` | |

> 상태색은 명도를 서로 다르게 배치 + 글리프 병기 → 적/녹 색맹도 구분 가능.

### Spacing Scale (`Space`)
`XS/SM=1`, `MD=2`, `LG=3`, `XL=4` · `SIDEBAR_WIDTH=26` · `HEADER_HEIGHT=3` · `FOOTER_HEIGHT=1`

### Typography / Glyph (`Glyph`)
상태: `✔ ▲ ✖ ℹ ○ ●` · 구분: `─ │ • › ▸` · 미터: `█ ░`

---

## 4. Component 정의 (`app/ui/widgets.py`, `app/ui/screen.py`, `app/ui/status.py`)

| 컴포넌트 | 위치 | 설명 |
|----------|------|------|
| `AppShell` | screen.py | 앱 최상위 컨테이너(Header/Sidebar/Content/Footer 조립) |
| `AppHeader` | screen.py | Hostname/User/Time + **라이브** Service/Alarm/Health 지시자(P17) |
| `Sidebar` | screen.py | 고정폭 26, 카테고리+메뉴, 선택 강조(`›` caret 통일), 스크롤 |
| `AppFooter` | screen.py | 기능키(F1/F3/F5/F7/F8/F10/ESC) 통일 + **active-pane 방향 지시자**(P24~25) |
| `BaseScreen` | screen.py | 4구획 골격 자동 구성. 화면은 본문만 선언. active-pane 포커스 지시(P24) |
| `SectionTitle` | widgets.py | 섹션 제목 |
| `Card`/`StatusCard`/`MetricCard` | widgets.py | 카드 기반 콘텐츠 |
| `PropertyGrid` | widgets.py | key-value 속성 나열 |
| `MeterBar` | widgets.py | 임계값 색상 자동 미터 바 |
| `MessageBox` (+`info/warning/error/success_box`) | widgets.py | 통합 메시지 박스 |
| `collect_service_status()` | status.py | 헤더 라이브 지시자용 서비스 상태 수집(캐시/force)(P17) |

> 라이브 헤더(P17)와 System/Dashboard 매초 수집은 스레드+`call_from_thread`로 오프로드(P11).
> 향후 Dialog/Confirm/Toast/Spinner 등은 필요 시 동일 패턴으로 확장.

---

## 5. Screen별 Wireframe (목표)

### 공통 골격
```
┌─────────────────────────────────────────────────────────────┐
│ MNX Appliance Management Console  │ mnx01                     │  ← Header(3)
│ ● sands │ 2026-07-20 14:03 │ ✔ SVC 11/11 │ ✖ ALARM 0 │ ✔ HEALTH│
├──────────────┬──────────────────────────────────────────────┤
│ SYSTEM       │  ▸ Hardware                                   │
│ › Hardware   │  ┌── Card ──────────┐ ┌── Card ──────────┐    │  Sidebar(26)
│ › OS         │  │ CPU   42%  ████░░ │ │ MEM  63%  █████░ │    │  + Content
│ › Storage    │  └───────────────────┘ └──────────────────┘   │
│ › Network    │                                               │
├──────────────┴──────────────────────────────────────────────┤
│  F1 Help   F5 Refresh   F7 Rescan   F8 Network   F10 Exit  ESC│  ← Footer(1)
└─────────────────────────────────────────────────────────────┘
```

### System Overview (Dashboard 느낌)
- 좌: **Health Summary**(서비스/디스크/파이프라인 종합 배지)
- 우: **System Information**(PropertyGrid)
- 하: CPU / Memory / Disk / Network / Quick Status (MetricCard 그리드)

### Performance
- CPU / Memory / Disk / Network / Top Process 를 **MetricCard**로 재구성.
- 모든 `MeterBar` 길이·정렬·간격 통일.

### Config (설정 페이지 느낌)
- JSON 뷰어 제거 → **Category → Option → Description → Current Value → Editable** 를 `PropertyGrid`+`StatusCard`로 표현.

---

## 6. Directory 구조 개선

```
app/
  ui/                 ← 신규: 디자인 시스템 (Phase 1)
    __init__.py
    tokens.py         ← 색상/간격/글리프/상태 단일 소스
    theme.tcss        ← Shell 레이아웃 + 컴포넌트 스타일
    widgets.py        ← 공통 컴포넌트
    screen.py         ← AppShell + BaseScreen
  screens/            ← 기존 화면 (Phase 2+ 에서 BaseScreen 로 순차 이관)
  widgets/            ← custom_header 만 유지, 미사용 위젯은 Phase 에서 제거
  styles/theme.tcss   ← 잔여 전역 스타일 (점진 이관 후 축소)
docs/design/
  DESIGN_SYSTEM.md    ← 본 문서
```

권장(별도 제안): `__pycache__/*.pyc` Git 추적 제거 + `.gitignore` 추가(리포 위생).

---

## 7. Textual 구조 개선

- `App.CSS_PATH` 를 리스트로 (구현: `app/main_app.py` — `["styles/theme.tcss", "ui/theme.tcss"]`).
- 화면 = `BaseScreen` 상속 → `compose_content()` + `on_nav_selected()` 만 구현.
- 상태 표현은 `tokens.status_badge()` / `tokens.meter()` 로 단일화.
- 블로킹 제거: `system.py`/`dashboard.py` 의 매초 subprocess 를 스레드+`call_from_thread` 로 이관(다른 화면 패턴과 통일).

---

## 8. Migration Plan — 실제 이력 (Phase 1~27, 각 commit 별 승인 완료)

> `feature/refactor-ui` 브랜치에서 각 Phase = 독립 commit, `git diff` 리뷰 → 승인 후 진행.
> 기능 불변 원칙 유지. 최초 계획(P1~P7)에 이어 실전 튜닝(P8~P27)이 추가되었다.

### 8.1 기반 이관 (Phase 1~14)

| Phase | 범위 | 상태 |
|-------|------|------|
| **1** | `app/ui/` 디자인 시스템 기반(tokens/theme/widgets/screen) + 본 문서 | ✅ |
| **2** | `Dashboard` → BaseScreen 이관 | ✅ |
| **3** | `Performance` → BaseScreen + 카드화 | ✅ |
| **4** | `MNX Config` → BaseScreen(설정페이지화 착수) | ✅ |
| **5a~5d** | `Service`/`Log Monitor`/`Network`/`System Overview` → BaseScreen | ✅ |
| **6** | 데드코드 제거(미사용 위젯 + 도달불가 화면), 인증 클래스 통합 | ✅ |
| **7** | `.gitignore` 추가 + 빌드/런타임 아티팩트 추적 해제 | ✅ |
| **8** | 카드 기반 Performance overview + `MeterBar` 통일 | ✅ |
| **9** | 카드 기반 System Overview | ✅ |
| **10** | Config 섹션 설명(settings-page description) | ✅ |
| **11** | System/Dashboard 매초 수집을 스레드로 오프로드(블로킹 제거) | ✅ |
| **12** | `utils/auth` su fallback root 우회 차단(보안) | ✅ |
| **13** | 이관 화면의 잔여(dead) shell CSS 제거 | ✅ |
| **14** | `Command Shell` → BaseScreen 이관 | ✅ |

### 8.2 일관성·기능 튜닝 (Phase 15~27)

| Phase | 범위 | 상태 |
|-------|------|------|
| **15** | 사이드바 하이라이트 통일 + Network 리스트 단일행 | ✅ |
| **16** | 사이드바 항목 caret(`›`) 전 화면 통일 | ✅ |
| **17** | 헤더 Service/Alarm/Health 지시자 **라이브화**(`status.py`) | ✅ |
| **18~20** | Network config 모달 디자인 시스템 재설계 + 입력/버튼 1행 고정 | ✅ |
| **21~23** | Capture 인터페이스 select+tag 배열 에디터 · Net 태그 칩 · None 칩 + config.ini 현재값 뷰 | ✅ |
| **24~25** | 전 화면 active-pane 포커스 지시자 + footer 방향 지시자 | ✅ |
| **26** | footer 가시성 복구(border-top가 유일 행을 삼키던 버그) | ✅ |
| **27** | pane divider 고정(포커스 시 이동하지 않도록) | ✅ |
| **28** | Service Manager 서비스 목록 최신화(12→15: `mnx_regression_api`·`mnx-thirdparty`·`elasticsearch` 래퍼 추가) + 사이드바 긴 이름 줄바꿈(폭 21칸 초과 시 `_`/`-`에서 2줄, 항목 높이 가변) | ✅ |
| **29** | Capture 인터페이스 에디터: 키보드 네비(←→ 칩 / ↑↓ 인터페이스 행 / Enter·Space 선택) + None(캡처 제외) 선택 시 `✓ None` 마커·토스트·상태줄 확인 효과 + 화면에 현재 suricata.yaml(af-packet/pcap) 인터페이스 뷰 추가. 저장 시 config.ini + suricata.yaml(af-packet cluster-id 99·98…, pcap) 동기화 | ✅ |

> 릴리스: **v2.3.0** — `/data/mnxmc-2.3.0.deb` (2026-07-23). 버전 문자열 전 파일 통일.
> 릴리스: **v2.3.1** — `/data/mnxmc-2.3.1.deb` (2026-07-28). Service Manager 서비스 목록 최신화 + 사이드바 긴 이름 줄바꿈(Phase 28), Capture 인터페이스 에디터 키보드 네비·None 확인 효과·suricata.yaml 동기화 뷰(Phase 29). 버전 문자열 전 파일 v2.3.1 통일.

---

## 9. 우선순위 *(당초 계획 — v2.3.0에서 전 항목 완료)*

1. ~~**P1 (기반)** — 공통 컴포넌트 먼저. 없으면 이후 전부 불가.~~ ✅
2. ~~**P2 (골격 연결)** — 제품 일체감이 가장 빨리 체감되는 지점.~~ ✅
3. ~~**P3 (Performance)** — 사용 빈도 높고 카드화 효과 큼.~~ ✅
4. ~~**P4 (Config)** — 엔터프라이즈 기대치 격차가 가장 큼.~~ ✅
5. ~~**P5~P7** — 나머지 이관 및 정리.~~ ✅ (+ P8~P27 실전 튜닝)

---

## 부록 — 컴포넌트 사용 예시

```python
from app.ui.screen import BaseScreen
from app.ui.widgets import SectionTitle, MetricCard, StatusCard

class SystemScreen(BaseScreen):
    SIDEBAR_TITLE = "SYSTEM"
    SIDEBAR_ITEMS = [("hw", "Hardware"), ("os", "OS"), ("storage", "Storage")]

    def compose_content(self):
        yield SectionTitle("Hardware")
        yield MetricCard("CPU", value="42%", percent=42.0)
        yield StatusCard("Capture Engine", state="ok", detail="active (3d)")

    def on_nav_selected(self, item_id: str) -> None:
        ...  # item_id 로 본문 갱신
```
