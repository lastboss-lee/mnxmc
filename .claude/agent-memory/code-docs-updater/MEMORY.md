# MNXMC 프로젝트 문서화 메모리

## 프로젝트 식별

- 프로젝트명: MNXMC (MNX Appliance Management Console)
- 경로: `/mnt/d/mnxmc-dev/202602191000/`
- 언어: Python 3.12 + Textual TUI
- 버전 체계: v0001, v0002 ... (설치 아카이브 기준)

## 문서 파일 위치

| 파일 | 용도 |
|------|------|
| `/mnt/d/mnxmc-dev/202602191000/README.md` | 프로젝트 개요, 실행 방법, CHANGELOG |
| `/mnt/d/mnxmc-dev/202602191000/MNXMC_Technical_Specification.md` | 기술 명세서 (화면/모듈/위젯 상세) |
| `/mnt/d/mnxmc-dev/202602191000/docs/USER_MANUAL.md` | 사용자 매뉴얼 (화면별 사용 가이드, FAQ) |
| `/mnt/d/mnxmc-dev/202602191000/docs/ARCHITECTURE.md` | 아키텍처 문서 (비동기 패턴, 설계 결정) |

## 핵심 코드 패턴

### 비동기 UI 패턴 (표준)
Textual 단일 스레드 이벤트 루프를 블로킹하지 않기 위해 사용:
```
_async_refresh() → threading.Thread → _fetch_*() → app.call_from_thread() → _render_*()/apply_*()/after_*()
```

### DiskMonitor 공유 인스턴스
- `self.app.disk_monitor`로만 접근해야 함 (델타 상태 유지)
- 독립 인스턴스 생성 금지

### stale 방지 가드
```python
def _apply_detail(self, svc: str, output: str) -> None:
    if self._current_svc != svc:
        return  # 사용자가 다른 항목으로 이동 시 무시
```

## 문서 스타일 규칙

- 주요 설명: 한국어
- 코드 블록 언어 태그 필수
- 상태/컬럼 참조 표: `| 이름 | 타입 | 기본값 | 설명 |` 형식
- Textual markup 예시는 코드 블록 안에 표기
- CHANGELOG: `### [버전] — YYYY-MM-DD` + Added/Changed/Fixed 형식

## 모듈 구조 요약

- `app/screens/` - Textual Screen (각 화면)
- `app/widgets/` - CustomHeader, MenuList, TwoPanelLayout
- `modules/` - BaseModule 하위 데이터 수집 모듈
- `network_management/` - netplan 기반 네트워크 설정
- `utils/` - 인증, 헬퍼

## 갱신 주기 참조표

- CustomHeader 시계: 1초
- Dashboard/System/Performance: 1초
- Network 트래픽: 2초
- Log 파일: 3초
- Service/Kafka(전용)/Elasticsearch(전용): 5초
- Elasticsearch(인라인): 10초
