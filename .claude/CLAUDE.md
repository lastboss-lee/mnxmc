# MNXMC v2.2.0 Project Guide

## 🤖 에이전트 시스템 로드
모든 요청은 아래 에이전트 정의를 최우선으로 참고하여 처리한다.
- **총괄 PM:** `agents/00-root-orchestrator.md`
- **개발/구현:** `agents/01-advanced-developer.md`
- **검증/리뷰:** `agents/code-reviewer.md`, `agents/tui-tester.md`, `agents/infra-validator.md`
- **특화 에이전트:** `agents/02-concurrency-validator.md` ~ `agents/06-production-hardening-agent.md`

## 📋 핵심 동작 규칙
1. **Root 우선:** 모든 사용자의 질문은 `00-root-orchestrator`가 먼저 분석하고 작업 계획을 세운다.
2. **한국어 응답:** 모든 에이전트는 반드시 한국어로 응답한다.
3. **환경 고려:** 모든 코드는 `/data`, Kafka, Elasticsearch 환경 및 10Gbps 네트워킹 성능을 고려해야 한다.

## 🛠 주요 명령어
- 에이전트 상태 확인: `현재 활성화된 에이전트 구성 보고해줘`
- 코드 리뷰 요청: `이 파일을 code-reviewer 절차에 따라 검토해줘`

## ✂️ 단순화(ponytail) 운영 원칙

MNXMC는 **오프라인 어플라이언스 + Textual TUI + 장기 유지보수** 환경이다.
일반 Python 프로젝트 기준의 단순화 제안을 그대로 적용하지 않고 아래 2단 티어로 처리한다.

### Tier A — 자동 적용 허용
- Dead code 제거 (caller 0 확인 필수)
- 중복 코드 통합
- Native/stdlib API 사용
- 문자열 파싱 제거
- 함수 축소(shrink)
- 사용되지 않는 실행 산출물·로그·임시 파일 제거

### Tier B — 항상 사용자 검토 후 적용
- Base class / ABC 삭제
- 모듈 삭제
- `requirements.txt` 변경
- 패키지 / 바이너리 삭제 (`packages/**`)
- 구조 변경
- 보안 관련 의존성 변경

### 티어 판정 규칙 (경계가 겹칠 때)
1. **보수 우선:** 하나의 변경이 두 티어에 걸치면 **항상 Tier B**.
   예) `modules/*.run()` 은 dead code(A)지만 `BaseModule` ABC 계약과 모듈 5개에
   걸치므로(B) → Tier B. dead code라는 이유로 자동 적용 금지.
2. **런타임 시스템 설정 파일은 Tier B:** `/etc/**` 를 읽거나 쓰는 파싱 코드
   (`suricata.yaml`, `config.ini` 등)는 "문자열 파싱 제거"(A) 대상이 아니다.
   콘솔 리포에 없는 엔진 런타임 파일이라 실제 배포본 형태를 검증할 수 없고,
   **쓰기 경로는 주석·포맷 보존을 위해 텍스트 레벨 치환을 유지한다**(YAML 파서 금지).
3. **백업·증적 파일은 Tier B:** `infra_audit/**/backup_*/`, `*.bak` 은 KISA 조치 전
   `/etc` 원본 스냅샷(롤백·감사 증적)이다. "실행 산출물"(A)로 취급 금지.
   Tier A 로 지울 수 있는 산출물은 리포트(`*_report_*`)·로그(`*.log`)·중복 사본뿐.
4. **오프라인 설치 자산은 감축 대상 아님:** `packages/pip/*.whl`, `packages/apt/*.deb`
   벤더링과 `requirements.txt` 의 transitive 핀은 중복이 아니라 **락파일**이다.
   에어갭 재빌드 재현성이 목적이므로 "중복 제거" 논리를 적용하지 않는다.
   중복 *사본*(동일 파일 이중 커밋, 구버전 deb)만 Tier B 로 제안한다.

### 검증 게이트 (필수)
`tests/` 와 CI가 없으므로 Tier A 라도 검증 없이 커밋하지 않는다.
- 최소: `python3.12 -m py_compile <변경파일>` + 변경 모듈 import 확인
- TUI 동작(포커스·키 입력·렌더)이 바뀌는 변경: `tui-tester` 절차 통과 후 적용
- Tier A 변경도 **되돌리기 쉬운 단위로 커밋 분리** (한 커밋 = 한 종류의 절단)

### 미룬 단순화 기록
Tier B 로 보류하거나 의도적으로 단순화를 포기한 지점은 해당 위치에 마커를 남긴다.
```python
# ponytail: <유지한 이유 / 천장>, upgrade: <재검토 트리거>
```