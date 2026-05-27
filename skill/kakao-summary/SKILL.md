---
name: kakao-summary
description: 카카오톡 오픈채팅방 대화를 요약하고, 특정 토픽의 원문 메시지를 그대로 보여준다. 트리거 — "카톡 요약", "오픈채팅 요약", "오늘 채팅 정리", "T1 원문", "T2 원문 보여줘", "~ 관련 대화 보여줘". "요약"이라고만 하면 mode=always 로 등록된 방을 전일(어제) 기준으로 모두 요약한다. 특정 방 이름이나 오픈채팅 링크를 함께 주면 그 방도 포함한다. 기간을 명시하면(예: "지난 3일", "5/20~5/25") 그 범위로, 최대 7일까지 요약한다. 동작 방식 — `kakao_summary_mcp` MCP 서버가 등록되어 있으면 그 도구를 사용한다.
---

# kakao-summary

PC카카오톡의 '대화 내용 내보내기'를 자동화해 대화 .txt를 받고, 로컬에서 파싱·임베딩·시맨틱 검색까지 처리합니다. 데이터는 사용자 PC에만 존재합니다.

## 전제: MCP 서버 등록 확인

`kakao_summary_mcp` MCP 서버가 등록되어 있다고 가정. 등록 여부 확인:
- 사용 가능한 도구에 `kakao_setup_check`, `kakao_register_rooms`, `kakao_sync_chats`, `kakao_get_messages_by_ids`, `kakao_search_messages` 다섯 개가 보이면 등록된 상태.
- 안 보이면 사용자에게 안내:
  ```
  pip install kakao-summary-mcp        # 또는 레포 클론 후: pip install -e .
  claude mcp add kakao-summary -- kakao-summary-mcp
  ```

## 추출 방식 (중요)

PC카톡(EVA 프레임워크)은 UIA 트리가 없고 포그라운드 강제 전환도 OS가 막으므로, 추출은 두 방식 중 하나로 한다(`kakao_sync_chats`의 `method`):

- **`method:"ocr"` (기본, 진짜 백그라운드)**: `PrintWindow`로 가려진 대화창을 캡처하고 포커스 없이 스크롤(`WM_MOUSEWHEEL`)하며 OCR. **마우스·키보드·포커스를 전혀 뺏지 않음.** OCR 엔진은 **Windows 내장 OCR(한국어 정확·고속, 모델 다운로드 없음)** 1순위, 언어팩 없으면 easyocr 폴백. 링크·이메일·시각까지 대체로 정확하나 일부 오인식 가능 → 요약엔 충분, 원문 정확 검색엔 `export` 권장. (OCR 의존성: `pip install -e ".[ocr]"`, Windows '한국어' OCR 언어팩 권장)
- **`method:"export"` (무손실, 포커스 필요)**: 네이티브 '대화 내용 내보내기' .txt. 정확하지만 추출 순간 카톡 창이 앞으로 와야 함.

**공통 전제**: 대상 방의 **PC카톡 대화창이 별도 창으로 열려 있어야** 한다(다른 창에 가려져도 OK, **트레이/최소화는 ❌** — 창 핸들이 사라짐). `kakao_setup_check`의 `kakao_window_minimized`가 true면 "카톡 창을 띄워두세요(가려져도 OK)"라고 안내한다.

## 첫 사용자 진단·셋업 흐름 (자동)

요약·검색 요청이 들어왔을 때, 먼저 환경을 검사하고 부족하면 채웁니다.

1. **`kakao_setup_check` 호출** (인자 없음). 응답의 `ready`가 `false`면 `next_steps`를 보고 분기:
   - `missing_deps`가 있으면 설치 명령 안내.
   - `kakao_running`이 false면 "PC카톡을 실행·로그인하고 알려주세요"로 멈춤.
   - `kakao_window_minimized`가 true면 "카톡 창을 띄워두세요(가려져도 OK)" 안내.
   - `always_rooms`/`enabled_rooms`가 비어있으면 **방 등록 인터뷰**(아래) 진행.

2. **방 등록 인터뷰** (최초 1회):
   - ① "어떤 오픈채팅방을 모니터링할까요? PC카톡에 표시되는 방 이름을 알려주세요. 오픈채팅 링크가 있으면 같이 주셔도 됩니다(식별·메모용)."
   - ② 받은 방마다 "이 방은 **항상** 요약할까요(요약이라고만 해도 자동 포함), 아니면 **지목할 때만** 요약할까요?" → `always`/`optional` 결정.
   - ③ **`kakao_register_rooms` 호출**:
     ```json
     {
       "rooms": ["공부방", "부동산방"],
       "modes": {"공부방": "always", "부동산방": "optional"},
       "links": {"공부방": "https://open.kakao.com/o/..."},
       "replace": false
     }
     ```
   - 링크는 추출에 쓰이지 않습니다(방 이름으로 추출). 식별·참조용으로만 저장.

3. **ready**가 되면 원래 요청(요약/검색) 처리로 진행.

## 흐름 A — 요약

### A-0. 대상 방·기간 결정

- **방**:
  - "요약" / "카톡 요약"이라고만 하면 → `rooms` 생략(서버가 `mode=always` 방 전체 사용).
  - 사용자가 방 이름이나 오픈채팅 링크를 지목하면 → `rooms`에 그 방을 명시(optional·미등록 방도 일회성 포함). 링크만 준 경우 등록된 방 중 해당 링크의 이름으로 매핑하고, 못 찾으면 사용자에게 방 이름을 확인.
- **기간** (기본 = **전일/어제**):
  - 기간 언급이 없으면 → 인자 생략(서버 기본 전일). 별도로 기간을 되묻지 않음.
  - 사용자가 기간을 명시하면 `range`로 전달: `"yesterday"`, `"YYYY-MM-DD"`, `"YYYY-MM-DD~YYYY-MM-DD"`, `"지난 3일"`, `"last 5 days"` 등.
  - **최대 7일**. 초과 입력은 서버가 가장 최근 7일로 클램프하고 응답 `clamped:true` + `notes`로 알려줌 → 사용자에게 그대로 고지.

### A-1. `kakao_sync_chats` 호출

```json
{ "range": "지난 3일", "rooms": ["공부방"] }
```
또는 그냥 전일·always 방이면:
```json
{ }
```
첫 실행 시 bge-m3 모델 약 2GB 다운로드. 사용자에게 미리 안내.

### A-2. 응답 처리

응답 필드: `date_start`, `date_end`, `clamped`, `notes`, `rooms_succeeded`, `rooms_failed`, `turns`.
- `clamped:true`거나 `notes`가 있으면 사용자에게 그대로 노출.
- `rooms_failed`에 항목이 있으면 사유를 그대로 노출(특히 트레이/창·템플릿 관련 setup 에러).
- `turns` 배열을 방별로 묶어 화제 단위 토픽 T1, T2, … 라벨링.
- 각 토픽에 해당 `turn_id` 5~20개 수집(대화 컨텍스트에 보관).

### A-3. 사용자 출력 형식

```
📅 2026-05-25 ~ 2026-05-27 카톡 요약 (세션: <session_id>)

### 공부방
T1. 모의고사 일정 (12 turns) — 6/3 합동, 결과는 단톡 공지
T2. 인강 추천 (4 turns) — …

💬 특정 토픽 원문은 "T1 원문" 또는 "전세 관련 대화"처럼 말씀해 주세요.
```

**중요**: 각 토픽 → `turn_id` 매핑은 현재 대화 컨텍스트에 보관. 후속 흐름 B에서 재사용.

## 흐름 B — 원문 조회

### B-1. 토픽 라벨 지정 ("T1 원문 보여줘")

직전 흐름 A에서 매핑한 T1의 turn_ids로:
```json
{ "turn_ids": ["공부방:20260526:t0003", "공부방:20260526:t0007"] }
```
→ `kakao_get_messages_by_ids`. 응답 `turns`를 시간순으로 출력:
```
[공부방 2026-05-26 09:15] 홍길동: ...
[공부방 2026-05-26 09:20] 김철수: ...
```

### B-2. 자유 질의 ("전세 사기 관련 대화")

```json
{ "query": "전세 사기", "room": "부동산방", "date": "2026-05-26", "top_k": 15 }
```
→ `kakao_search_messages`. room/date는 사용자가 명시했거나 흐름 A 컨텍스트에서 추론 가능할 때만 채움.

## 자주 발생하는 실패와 대응

- `rooms_failed`에 `'<방>' 채팅 창을 찾지 못했습니다` (OCR) → 그 방을 PC카톡에서 **별도 대화창으로 열어두기**(가려져도 OK, 트레이 ❌) 안내.
- `rooms_failed`에 `카카오톡 메인 창을 찾을 수 없습니다` (export) → 카톡 실행 + 창 띄우기 안내.
- `kakao_window_minimized:true` → "카톡 창을 띄워주세요(가려져도 OK)".
- `rooms_failed`에 `화면에서 'menu_btn.png'를 찾지 못했습니다`/`템플릿 이미지가 없습니다` → 백그라운드·포그라운드 tier가 모두 실패한 드문 경우. 템플릿 이미지 재캡처 안내(`~/.kakao-summary-mcp/templates/menu_btn.png`, `export_menu.png`). 진단 스샷은 `~/.kakao-summary-mcp/logs/`.
- 검색이 빈 결과 → 해당 기간·방에 대해 `kakao_sync_chats`가 먼저 실행됐는지 확인. 안 됐으면 sync 먼저 권유.
- 요청 기간의 일부 날짜가 비어있음 → 내보내기 .txt에 그 날짜 대화가 없을 수 있음(오래된 대화 미보존). 그대로 고지.

## 사용자 셋업 안내 (간소화)

```
1) pip install kakao-summary-mcp        # 또는 레포 클론 후: pip install -e .
2) claude mcp add kakao-summary -- kakao-summary-mcp
3) PC카톡 실행·로그인 (창은 띄워두기, 트레이 최소화 ❌)
4) 새 세션에서 "카톡 요약해줘" → 스킬이 방 등록(항상/선택, 링크)까지 자동 안내
```

평소엔 사용자 추가 작업 0개(백그라운드 추출). 모든 tier 실패 시에만 `kakao-summary-mcp-probe --dump-uia` 결과 공유와 템플릿 이미지 캡처 요청.
