# kakao-summary-mcp

PC 카카오톡 오픈채팅방 하루치 대화를 자동으로 추출·요약하고, 특정 주제의 원문 메시지를 시맨틱 검색으로 들춰볼 수 있게 해주는 **MCP 서버**입니다.

- 카카오톡은 공식 메시지 API가 없으므로 PC카톡의 **'대화 내용 내보내기'** UI 자동화로 우회 수집합니다.
- 모든 데이터(원문 .txt, 임베딩 인덱스)는 **사용자 PC 로컬에만** 존재합니다.
- 임베딩은 `BAAI/bge-m3` (sentence-transformers), 벡터 DB는 ChromaDB(PersistentClient).

## 동작 환경 (필독)

| 항목 | 요구사항 |
|---|---|
| OS | **Windows 10/11** (macOS PC카톡 UI 다름, Linux 카톡 없음) |
| 의존성 | Python 3.10+, PC 카카오톡 로그인된 상태로 실행 중 |
| 디스크 | bge-m3 모델 약 2GB + 대화 인덱스 |
| 권한 | UI 자동화를 위해 다른 창이 PC카톡을 가리지 않아야 함 |

📌 추출은 두 가지 방식(`kakao_sync_chats`의 `method`)을 지원합니다.

- **`method:"ocr"` (기본 · 진짜 백그라운드)** — `PrintWindow`로 가려진 대화창을 캡처하고 포커스 없이 스크롤(`WM_MOUSEWHEEL`)하며 OCR. **마우스·키보드·포커스를 전혀 뺏지 않음.** OCR 엔진은 Windows 내장 OCR(한국어 정확·고속, 모델 다운로드 없음) 1순위, 언어팩이 없으면 easyocr 폴백. 일부 글자 오인식이 있을 수 있어 **요약엔 충분, 정확한 원문이 필요하면 `export` 권장**. (`pip install -e ".[ocr]"` + Windows '한국어' OCR 언어팩 권장)
- **`method:"export"` (무손실 · 포커스 필요)** — 네이티브 '대화 내용 내보내기' .txt. 정확하지만 추출 순간 카톡 창이 잠깐 앞으로 나옵니다. 메뉴 클릭은 3-tier fallback(① `Ctrl+S` 단축키 → ② UIA 메뉴 탐색 → ③ 사용자 캡처 템플릿 이미지)으로 자동화됩니다.

> **공통 전제**: 대상 방의 PC카톡 **대화창이 별도 창으로 열려 있어야** 합니다(다른 창에 가려져도 OK, **트레이/최소화는 ❌** — 창 핸들이 사라집니다).

## 설치

### Option A — 로컬 개발 설치 (권장: 현재 단계)
```powershell
git clone https://github.com/989-alt/kakao-summary-mcp.git
cd kakao-summary-mcp
pip install -e .
# 진짜 백그라운드 OCR 추출까지 쓰려면(권장):
pip install -e ".[ocr]"
```

### Option B — uvx로 zero-install 실행 (GitHub 직접)
```powershell
uvx --from git+https://github.com/989-alt/kakao-summary-mcp kakao-summary-mcp
```

> PyPI 배포는 아직 안 됨. `pip install kakao-summary-mcp` 는 곧 지원 예정.

## 첫 실행 전 셋업 (1줄로 끝남)

설치 + MCP 등록만 하면 끝입니다. 채팅방 등록은 첫 대화에서 LLM이 알아서 물어봅니다.

1. **설치 + MCP 등록**
   ```powershell
   pip install -e .
   claude mcp add kakao-summary -- kakao-summary-mcp
   ```

2. **PC카톡 실행 + 로그인**된 상태로 두기.

3. **새 Claude 세션에서 "오늘 카톡 요약해줘"** 하면 LLM이 자동으로:
   - `kakao_setup_check` 호출 → 환경 진단
   - 등록된 방이 없으면 "어떤 방을 모니터링할까요?" 물음
   - 답변을 받아 `kakao_register_rooms`로 자동 등록
   - `kakao_sync_chats`로 추출 진행

기본은 `method:"ocr"`(진짜 백그라운드)로 동작하며, 정확한 원문이 필요할 때만 `method:"export"`(무손실, 포커스 필요)를 씁니다. `export`의 메뉴 클릭은 `Ctrl+S` → UIA → 템플릿 이미지 3-tier로 자동화됩니다(위 "동작 환경" 참고).

진단이 필요하면:
```powershell
kakao-summary-mcp-probe              # 환경·UIA 빠른 점검
kakao-summary-mcp-probe --dump-uia   # 카톡 UIA 트리 dump (Tier 2 디버깅)
```

## MCP 클라이언트에 등록

### Claude Code
```powershell
claude mcp add kakao-summary -- kakao-summary-mcp
```
또는 `~/.claude/mcp.json`에 직접:
```json
{
  "mcpServers": {
    "kakao-summary": {
      "command": "kakao-summary-mcp"
    }
  }
}
```

### Claude Desktop
`%APPDATA%\Claude\claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "kakao-summary": {
      "command": "kakao-summary-mcp"
    }
  }
}
```

### Cursor / Zed
표준 MCP stdio 서버라 동일하게 `command: "kakao-summary-mcp"` 형태로 등록.

## Claude skill 설치 (선택, 권장)

이 레포의 `skill/kakao-summary/`에는 **Claude Code용 skill**이 함께 들어 있습니다. 설치하면 `/kakao-summary` 슬래시 명령과 "카톡 요약해줘" 같은 자연어 트리거로 위 MCP 도구들이 정해진 흐름(진단 → 방 등록 인터뷰 → 추출 → 토픽 요약 → 원문 드릴다운)대로 자동 호출됩니다. MCP만 등록해도 동작하지만, skill을 깔면 사용 흐름이 훨씬 매끄럽습니다.

```powershell
# Windows (Claude Code 사용자 skill 디렉터리로 복사)
xcopy /E /I skill\kakao-summary "$env:USERPROFILE\.claude\skills\kakao-summary"
```
```bash
# macOS / Linux
cp -r skill/kakao-summary ~/.claude/skills/kakao-summary
```

새 Claude 세션에서 `/kakao-summary` 또는 "어제 카톡 요약해줘"라고 입력하면 됩니다.

## 제공되는 도구 5개

| Tool | 용도 |
|---|---|
| `kakao_setup_check` | 환경 진단 (의존성·카톡 실행·UIA·rooms.yaml). 첫 사용 시 LLM이 자동 호출 |
| `kakao_register_rooms` | 사용자 자연어 응답을 받아 rooms.yaml에 채팅방 자동 등록 |
| `kakao_sync_chats` | 지정 방의 하루치 대화 추출 → 파싱 → bge-m3 인덱싱 → turn 배열 반환 |
| `kakao_get_messages_by_ids` | 특정 turn_id 리스트의 원문을 시간순 반환 (토픽 드릴다운용) |
| `kakao_search_messages` | 자연어 질의로 인덱스 시맨틱 검색 (room/date 필터) |

## 사용 예시 (LLM 대화)

```
User: 오늘 카톡방들 요약해줘

LLM: [kakao_sync_chats date=today]
     → session_id, 142 turns 받음
     → 토픽 추출 (T1, T2, …) 후 사용자에게 표시:

     📅 2026-05-26 카톡 요약

     ### 공부방
     T1. 모의고사 일정 (12 turns) — 6/3 합동, 발표는 단톡으로
     T2. 인강 추천 (4 turns) — …

     ### 부동산방
     T3. 전세 사기 사례 공유 (8 turns) — …

User: T3 원문 보여줘

LLM: [kakao_get_messages_by_ids turn_ids=[...T3에 매핑한 ids...]]
     → 시간순 원문 출력

User: 모의고사 관련된 대화만 다시 모아줘

LLM: [kakao_search_messages query="모의고사 일정" room="공부방"]
     → top-15 turn 출력
```

## 데이터 위치

기본 `%USERPROFILE%\.kakao-summary-mcp\` (환경변수 `KAKAO_SUMMARY_MCP_HOME`로 override):
```
~/.kakao-summary-mcp/
├─ rooms.yaml                       대상 방·모델 설정
├─ templates/                       UI 자동화 템플릿 PNG
├─ data/
│   ├─ raw/{room}/{YYYY-MM-DD}.txt  PC카톡 내보낸 원본
│   ├─ parsed/{room}/...jsonl       파싱된 메시지
│   ├─ chroma/                      ChromaDB PersistentClient
│   └─ sessions/sess_*.json         sync 세션 메타데이터
└─ logs/last_fail_*.png             자동화 실패 스크린샷
```

## 트러블슈팅

| 증상 | 원인 / 해결 |
|---|---|
| 모든 tier 실패 (단축키·UIA·템플릿) | `kakao-summary-mcp-probe`로 진단. PC카톡 실행/로그인 확인 |
| Tier 1 실패 (Ctrl+S 후 다이얼로그 안 뜸) | 다른 창이 포커스 차지 중. 카톡 채팅창 클릭 후 재시도 |
| Tier 2 실패 (UIA 메뉴 못 찾음) | `kakao-summary-mcp-probe --dump-uia`로 트리 dump 후 PR 환영 |
| Tier 3 사용 시 템플릿 누락 | `~/.kakao-summary-mcp/templates/`에 `menu_btn.png`·`export_menu.png` 캡처 |
| 검색이 빈 결과 | 인덱싱 안 됨. 먼저 `kakao_sync_chats` 실행 |
| 첫 sync에서 2GB 다운로드 | 정상 (bge-m3 모델). 한 번만 |

## ToS / 개인정보 주의

- **본인이 참여한 방의 본인 화면 로컬 저장**은 카카오 운영정책 위반이 아닙니다. (PC카톡 기본 내보내기 기능 활용)
- 수집된 원문/요약을 **타인에게 공유하면 PIPA(개인정보보호법) 동의 필요**. 외부 전송 기능을 의도적으로 넣지 않은 이유.
- 자동화 빈도가 과도하면 카카오 약관상 제재 대상이 될 수 있으니 하루 1~2회 권장.

## 라이선스

MIT
