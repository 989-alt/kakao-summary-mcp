# kakao-summary 스킬 + 추출 엔진 개편 설계

날짜: 2026-05-27
상태: 승인됨 (브레인스토밍 완료)

## 배경 / 문제

PC카카오톡 '대화 내용 내보내기'를 자동화하는 `kakao-summary` 스킬이,
다른 창이 카톡 위에 떠 있을 때 추출에 전부 실패한다. 원인은 세 추출 tier가
모두 **카톡 창이 화면 맨 앞(포커스)**에 있어야 동작하기 때문이다:

- Tier 1 (Ctrl+S): `pyautogui` 전역 키 입력 → 포커스 필요
- Tier 2 (UIA): `click_input()` 물리 마우스 이동 + 전역 키 → 창이 보여야 함
- Tier 3 (템플릿): 화면 픽셀 매칭 → 가려지면 실패

또한 사용자 요구가 추가됐다: 방별 "항상/선택" 요약 구분, 링크 기반 식별,
날짜·시간 범위(기본 전일, 최대 7일) 요약.

## 목표 / 비목표

**목표**
- "준백그라운드" 추출: 카톡 대화창이 **열려만 있으면**(다른 창에 가려져도)
  마우스·키보드를 뺏지 않고 추출.
- 방별 `mode`(always|optional) + `link`(식별·메모용) 모델.
- 날짜 범위 요약: 기본 전일(어제), 최대 7일, 명시 시 임의 범위.

**비목표**
- 완전 헤드리스(트레이 최소화 상태) 추출. 로컬 DB 복호화는 약관·안정성 문제로 제외.
- 링크로 오픈채팅 자동 입장. 링크는 식별자·메모로만 사용.

## 설계

### 1. 방 등록 모델 (rooms.yaml)

```yaml
rooms:
  - name: "공부방"
    mode: always        # always | optional
    link: "https://open.kakao.com/o/EXAMPLE"
    enabled: true
```

- `mode: always` — "요약"이라고만 하면 자동 포함.
- `mode: optional` — 사용자가 이름/링크로 지목할 때만 포함.
- `link` — 식별·메모용. 추출엔 쓰지 않음. 기존 항목은 `mode` 누락 시 `always`로 간주(하위호환).

`common.py` 헬퍼:
- `room_entries(cfg)` → 정규화된 dict 리스트(name/mode/link/enabled).
- `always_rooms(cfg)` → enabled 且 mode==always 인 이름 리스트.
- `enabled_rooms(cfg, override)` → 기존 동작 유지(하위호환).

### 2. 최초 실행 셋업 흐름

스킬이 순서대로: ① 방 이름/링크 질문 → ② 방마다 always/optional 질문 →
③ `kakao_register_rooms` 호출. register_rooms는 `rooms`(이름)에 더해
선택적 `modes`(name→mode 매핑)와 `links`(name→link 매핑)를 받는다.

### 3. 요약 트리거 동작 (SKILL.md)

- "요약" / "카톡 요약" → `always` 방 전부, **전일** 범위 즉시 요약.
- "공부방 요약" / 링크 첨부 → 해당 방 추가 포함(optional·미등록도 일회성 처리).
- 범위 명시("지난 3일", "어제 오전", "5/20~5/25") → 그 범위. **최대 7일**, 초과 시 7일 클램프 + 고지.
- 기본은 즉시 진행(범위 질문 안 함).

### 4. 날짜·시간 범위 필터 (parser + common + server)

- `common.resolve_range(spec)` → `(start_date, end_date)` 반환.
  - 기본(None/"yesterday") → (어제, 어제).
  - "today" → (오늘, 오늘). "YYYY-MM-DD" → 단일일. "YYYY-MM-DD~YYYY-MM-DD" → 범위.
  - "지난 N일"/"last N days" → (오늘-N+1, 오늘) 형태로 해석은 스킬이 변환해 넘김.
  - start>end면 swap. 범위가 7일 초과면 end 기준 최근 7일로 클램프하고 사실을 반환값/로그로 표시.
- `parse_file(path, room, start_date=None, end_date=None)` — 범위 필터.
  기존 `target_date` 인자는 하위호환 위해 유지(주면 start=end=target).
- `kakao_sync_chats`에 `start_date`/`end_date`(또는 통합 `date` 유지) 추가.
  기본 동작을 **전일**로 바꾸되, 명시 입력 우선.
- 주의: 내보내기 .txt에 포함된 기간만 필터 가능. 없으면 빈 결과 → 고지.

### 5. 추출 엔진 = 하이브리드 3단계 (capture.py 재작성)

순서를 **백그라운드 우선**으로 재배치:

1. **UIA invoke (백그라운드)** — pywinauto `InvokePattern.invoke()`/`.invoke()`로
   메뉴·메뉴아이템 클릭(물리 마우스 이동 없음). 저장 다이얼로그는 핸들로 연결해
   Edit 컨트롤에 경로 `set_edit_text` + Save 버튼 invoke. 포커스/픽셀 불필요.
2. **포그라운드-그랩 폴백** — 1 실패 시 현재 포커스 창 HWND 저장 → 카톡 앞으로 →
   기존 Ctrl+S(shortcut) / click_input UIA → 끝나면 이전 창 복귀.
3. **템플릿** — 최후 수단(기존 유지).

`window.py`에 `remember_foreground()`/`restore_foreground(hwnd)` 추가.
전제: 카톡이 트레이로 최소화되면 안 됨(창이 열려 있어야 함).
`kakao_setup_check`가 "창이 트레이로 숨겨져 있음" 상태를 감지·고지.

### 6. 변경 파일

- `common.py` — resolve_range, room_entries, always_rooms.
- `parser/regex_parser.py` — parse_file 범위 필터.
- `extractor/capture.py` — 하이브리드 오케스트레이션.
- `extractor/uia_capture.py` — invoke 기반 백그라운드 경로 + 저장 다이얼로그 UIA 제어.
- `extractor/window.py` — 포커스 저장/복귀.
- `server.py` — sync_chats 범위 인자·기본 전일, register_rooms mode/link, setup_check 창상태.
- `config/rooms.example.yaml` — mode/link 예시.
- `.claude/skills/kakao-summary/SKILL.md` — 트리거·범위·셋업·준백그라운드 안내.

## 테스트 / 검증 전략

순수 로직(테스트 가능): resolve_range 경계(기본 전일·7일 클램프·swap·범위 파싱),
parse_file 범위 필터, register_rooms mode/link 병합, always/enabled 선택 로직.

하드웨어 의존(UI 자동화)은 단위테스트로 오케스트레이션 순서/폴백만 모킹 검증.
실제 추출은 환경에서만 가능.

**시뮬레이션(최종 검증)**: 예시 URL(`https://open.kakao.com/o/EXAMPLE`) 방을
등록 → 샘플 .txt를 raw 경로에 배치 → `kakao_sync_chats(skip_extract=true)`를
날짜 범위로 실행 → parse→index→search→get_by_ids 전 경로가 범위 필터까지
정확히 동작함을 확인. 임베더는 fake_embed로 패치(2GB 다운로드 회피).
전체 pytest 그린.

## 하위호환

- 기존 rooms.yaml(mode 없음)은 always로 간주.
- parse_file의 target_date, sync_chats의 date 인자 유지.
- enabled_rooms 시그니처 유지.
