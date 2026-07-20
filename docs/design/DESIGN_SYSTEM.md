# MNXMC Design System — Enterprise Network Appliance TUI

> 대상: MNXMC(MNX Management Console) 상용 제품 UI 일관화
> 기준: "6개월 뒤 다른 개발자가 유지보수 가능한가" / 공통 컴포넌트 우선 설계
> 참고 철학: Cisco FMC · FortiManager · VMware ESXi · Palo Alto · Sophos · TrueNAS SCALE
> (철학만 참고, 복사하지 않음 — MNXMC 고유 디자인 시스템 구축)

---

## 1. 현재 UI 문제점 분석

| # | 문제 | 근거 | 영향 |
|---|------|------|------|
| P1 | **화면마다 2패널 CSS를 복붙** | 12개 화면이 좌측 25% ListView + 우측 패널 인라인 CSS 반복 | 톤 불일치, 유지보수 시 12곳 수정 |
| P2 | **공통 골격 부재** | Header/Sidebar/Footer가 화면마다 제각각(있거나 없거나) | 제품 일체감 결여 |
| P3 | **미사용 위젯 데드코드** | `MenuList`,`SimpleMenu`,`TwoPanelLayout`,`LeftPanel`,`RightPanel`,`MenuTitle` 전부 미참조 | 혼란, 코드량 증가 |
| P4 | **도달 불가 화면** | `ElasticsearchScreen`,`KafkaScreen`,`FirewallScreen` — 기능은 `logs.py`에 임베드 | 중복 구현 |
| P5 | **색상/간격 하드코딩** | `#0c0c0c`, `#1a1a1a` 등 화면별 리터럴 산재 | 테마 변경 불가, 일관성 없음 |
| P6 | **인증 클래스 3중 중복** | `AuthenticationManager`가 `utils/auth.py`·`login.py`·`service.py`에 각각 정의 | 로직 분기 위험 |
| P7 | **상태 표현 제각각** | 서비스/헬스 상태 아이콘·색상 규칙 화면마다 다름 | 색맹 접근성·일관성 저하 |
| P8 | **Config 화면이 JSON 뷰어 느낌** | `mnx_config.py`가 설정 페이지가 아닌 파일 편집기 UX | 엔터프라이즈 제품 기대치 미달 |

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

## 4. Component 정의 (`app/ui/widgets.py`, `app/ui/screen.py`)

| 컴포넌트 | 위치 | 설명 |
|----------|------|------|
| `AppHeader` | screen.py | Hostname/User/Time/Service/Alarm/Health 상시 표시 |
| `Sidebar` | screen.py | 고정폭 26, 카테고리+메뉴, 선택 강조, 스크롤 |
| `AppFooter` | screen.py | 기능키(F1/F3/F5/F7/F8/F10/ESC) 통일 |
| `BaseScreen` | screen.py | 4구획 골격 자동 구성. 화면은 본문만 선언 |
| `SectionTitle` | widgets.py | 섹션 제목 |
| `Card`/`StatusCard`/`MetricCard` | widgets.py | 카드 기반 콘텐츠 |
| `PropertyGrid` | widgets.py | key-value 속성 나열 |
| `MeterBar` | widgets.py | 임계값 색상 자동 미터 바 |
| `MessageBox` (+`info/warning/error/success_box`) | widgets.py | 통합 메시지 박스 |

> Dialog/Confirm/Toast/Spinner 등 잔여 컴포넌트는 Phase에 따라 순차 추가(§8).

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

- `App.CSS_PATH` 를 리스트로: `["app/ui/theme.tcss", "app/styles/theme.tcss"]`.
- 화면 = `BaseScreen` 상속 → `compose_content()` + `on_nav_selected()` 만 구현.
- 상태 표현은 `tokens.status_badge()` / `tokens.meter()` 로 단일화.
- 블로킹 제거: `system.py`/`dashboard.py` 의 매초 subprocess 를 스레드+`call_from_thread` 로 이관(다른 화면 패턴과 통일).

---

## 8. Migration Plan (기능 단위 · 각 commit 별 승인)

| Phase | 범위 | 위험 | 상태 |
|-------|------|------|------|
| **P1** | `app/ui/` 디자인 시스템 기반 + 본 문서 (**순수 추가**) | 없음(기존 미참조) | ✅ 본 작업 |
| P2 | `App` CSS_PATH 연결 + `Dashboard`/`System` 을 BaseScreen 로 이관 | 중 | 대기 |
| P3 | `Performance` 카드화 + `MeterBar` 통일 | 중 | 대기 |
| P4 | `Config` 설정페이지화 | 중 | 대기 |
| P5 | `Service`/`Network`/`Logs` 이관 | 중 | 대기 |
| P6 | 데드코드 제거(미사용 위젯/도달불가 화면), 인증 클래스 통합 | 중 | 대기 |
| P7 | `.gitignore`/`__pycache__` 정리, 잔여 전역 CSS 축소 | 하 | 대기 |

각 Phase는 독립 commit, `git diff` 리뷰 → 사용자 승인 후 진행. 기능 불변.

---

## 9. 우선순위

1. **P1 (기반)** — 공통 컴포넌트 먼저. 없으면 이후 전부 불가. ← 현재
2. **P2 (골격 연결)** — 제품 일체감이 가장 빨리 체감되는 지점.
3. **P3 (Performance)** — 사용 빈도 높고 카드화 효과 큼.
4. **P4 (Config)** — 엔터프라이즈 기대치 격차가 가장 큼.
5. **P5~P7** — 나머지 이관 및 정리.

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
