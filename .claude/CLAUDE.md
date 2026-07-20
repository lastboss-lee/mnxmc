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