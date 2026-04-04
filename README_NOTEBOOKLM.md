# NotebookLM JSON 추출 가이드

이 문서는 PDF를 바로 파싱하기 어려운 경우, NotebookLM에게 Quizlet 앱용 JSON을 추출하도록 요청하는 방법을 정리한 가이드입니다.

목표는 다음과 같습니다.

1. PDF의 구조를 먼저 파악한다.
2. 섹션 또는 챕터 단위로 문제를 구조화 JSON으로 뽑는다.
3. 정답이 섹션 끝 표나 파일 마지막 answer key에 있는 경우에도 question과 정확히 매핑한다.
4. 애매한 항목은 억지로 채우지 않고 `needs_review: true` 로 남긴다.

## 추천 워크플로우

한 번에 PDF 전체를 처리하지 말고, 가능하면 PDF 1개씩, 그리고 챕터 또는 섹션 단위로 나눠서 요청하는 것을 권장합니다.

권장 순서:

1. NotebookLM에 PDF 1개만 업로드합니다.
2. 아래 `구조 파악 프롬프트`로 문제 페이지, 정답 페이지, 섹션 구조를 먼저 확인합니다.
3. 아래 `JSON 추출 프롬프트`로 챕터 또는 섹션 하나만 추출합니다.
4. 아래 `검증 프롬프트`로 누락, 중복, 정답 매핑 오류 가능성을 다시 점검합니다.
5. 결과 JSON을 파일로 저장한 뒤 Codex에게 전달합니다.

## 꼭 지켜야 할 요청 방식

NotebookLM에 요청할 때 아래 규칙을 항상 같이 넣어주세요.

- 반드시 JSON만 출력해달라고 요청합니다.
- 설명, 요약, 마크다운 코드블록은 빼달라고 요청합니다.
- 정답이 불명확하면 추측하지 말고 `needs_review: true` 로 남기게 합니다.
- 문제 아닌 텍스트는 question으로 만들지 말라고 요청합니다.
- 가능하면 처리 범위를 챕터 또는 페이지 범위로 명시합니다.

## 1. 구조 파악 프롬프트

먼저 아래 프롬프트로 PDF 구조를 파악합니다.

```text
이 PDF를 Quizlet용 JSON으로 바꾸기 전에 구조를 먼저 분석해줘.

다음 항목만 간단명료하게 정리해:
1. 실제 문제 시작 페이지와 종료 페이지
2. 정답이 있는 페이지 범위
3. 섹션/챕터 제목 목록
4. 문항 번호가 섹션마다 1부터 다시 시작하는지, 전체 파일에서 연속인지
5. 문제 유형이 무엇인지
   - multiple_choice
   - true_false
   - short_answer
   - multi_select
6. 정답이 어떤 형식으로 제시되는지
   - 문제 바로 아래
   - 섹션 끝 표
   - 파일 마지막 answer key
   - 기타
7. JSON 추출 시 주의해야 할 페이지나 블록이 있는지
   - 목차
   - 해설만 있는 페이지
   - 문제 아닌 장식/머리말/꼬리말
   - OCR이 심하게 깨진 페이지

반드시 PDF 내용만 근거로 답하고, 추측은 하지 마.
```

## 2. JSON 추출 프롬프트

아래 프롬프트는 실제 Quizlet용 JSON을 추출할 때 사용합니다.

이 프롬프트는 PDF 전체가 아니라, 한 섹션 또는 한 챕터씩 나눠서 쓰는 것이 좋습니다.

```text
이 PDF에서 Quizlet 앱용 JSON을 만들어줘.

중요 규칙:
- 반드시 JSON만 출력해. 설명, 마크다운, 코드블록 없이 raw JSON만 출력해.
- PDF에 실제로 있는 내용만 추출해. 추측해서 채우지 마.
- 정답이 명확하지 않으면 answer는 null로 두고 needs_review를 true로 해.
- 문제 아닌 텍스트, 장식, 머리말, 꼬리말, 페이지번호, 답안표 자체는 question으로 만들지 마.
- 원문은 최대한 보존하되, 띄어쓰기/OCR이 약간 깨진 경우 읽을 수 있는 수준으로만 최소 정리해.
- 해설이 없으면 explanation은 null.
- 문제 유형은 반드시 아래 4개 중 하나만 사용:
  - "multiple_choice"
  - "true_false"
  - "short_answer"
  - "multi_select"
- 객관식은 choices를 순서대로 넣고, answer는 choice_indices 배열로 넣어.
- O/X는 choices를 ["O", "X"]로 넣고 answer는 {"choice_indices": [1]} 또는 {"choice_indices": [2]} 형식으로 넣어.
- 단답형은 choices를 빈 배열로 두고 answer_text에 정답 문자열을 넣어.
- 복수정답 객관식은 "multi_select"로 두고 answer.choice_indices에 여러 개 넣어.
- 정답이 섹션 끝 표나 파일 마지막 answer key에 있으면 반드시 해당 정답과 매핑해.
- 문항 번호가 섹션마다 다시 시작하면 section_title과 local_number로 구분해.
- question_id는 section slug와 local number를 조합해서 고유하게 만들어.
- source_pages는 반드시 넣어.

출력 JSON 스키마는 정확히 아래 형태를 따라:
{
  "schema_version": "1.0",
  "deck_title": "string",
  "source_pdf": "string",
  "section_title": "string",
  "questions": [
    {
      "question_id": "string",
      "local_number": "string",
      "source_pages": [1],
      "question_kind": "multiple_choice",
      "stem": "string",
      "choices": [
        { "index": 1, "label": "①", "text": "string" }
      ],
      "answer": {
        "choice_indices": [1]
      },
      "answer_text": null,
      "explanation": null,
      "needs_review": false,
      "review_reason": null
    }
  ]
}

추가 규칙:
- multiple_choice: answer.choice_indices는 반드시 길이 1
- multi_select: answer.choice_indices는 길이 2 이상 가능
- true_false: choices는 반드시 O/X만 사용
- short_answer: choices는 반드시 []
- 정답이 없거나 불명확하면:
  - "answer": null
  - "answer_text": null
  - "needs_review": true
  - "review_reason": "answer_unclear"

이번 요청 범위:
- 섹션/챕터: [여기에 챕터명 또는 페이지 범위]
- 문제 페이지: [예: 4-15]
- 정답 페이지: [예: 121-122]

이 범위만 처리해서 JSON만 출력해.
```

## 3. 검증 프롬프트

JSON을 한번 뽑은 뒤, 아래 프롬프트로 누락과 오류를 다시 점검합니다.

```text
방금 만든 JSON을 PDF와 대조해서 검증해줘.

다음 항목만 점검해:
1. 문항 누락 여부
2. 문항 번호 중복 여부
3. question_kind 잘못 분류 여부
4. choices 개수 이상 여부
5. 정답 누락 여부
6. answer key와 question 매핑 오류 가능성
7. 문제 아닌 텍스트가 question으로 들어간 항목

출력 형식:
- JSON만 출력
{
  "section_title": "string",
  "expected_question_count": 0,
  "json_question_count": 0,
  "missing_numbers": [],
  "duplicate_numbers": [],
  "suspect_items": [
    {
      "question_id": "string",
      "reason": "string"
    }
  ]
}
```

## 바로 복붙해서 쓰는 요청 예시

### 예시 1: 파일 마지막 answer key를 사용하는 챕터형 PDF

```text
이 PDF의 Chapter 1만 Quizlet용 JSON으로 뽑아줘.
문제는 p.4-15이고, 정답은 p.121의 Chapter 1 answer key를 사용해.
위 JSON 스키마를 정확히 따르고, 반드시 JSON만 출력해.
정답이 불명확하면 추측하지 말고 needs_review=true로 남겨줘.
문제 아닌 텍스트는 절대 question으로 만들지 마.
```

### 예시 2: 섹션 끝 정답표를 사용하는 PDF

```text
이 PDF의 섹션 2만 처리해줘.
문제 번호는 이 섹션 안에서 1부터 다시 시작한다.
섹션 끝의 정답 표를 사용해서 answer를 채워줘.
위 JSON 스키마를 정확히 따르고, 반드시 JSON만 출력해.
답이 불분명한 항목은 answer를 추측하지 말고 needs_review=true로 남겨줘.
```

### 예시 3: 구조 파악부터 먼저 시키는 요청

```text
이 PDF는 바로 JSON으로 뽑지 말고, 먼저 구조를 분석해줘.
문제 시작/종료 페이지, 정답 페이지, 챕터 목록, 문제 유형, answer key 위치를 먼저 알려줘.
추측하지 말고 PDF 내용만 근거로 답해줘.
```

## JSON 작성 기준 요약

- `question_kind` 는 반드시 `multiple_choice`, `true_false`, `short_answer`, `multi_select` 중 하나만 사용합니다.
- 객관식은 `choices` 를 순서대로 넣고 `answer.choice_indices` 로 정답 번호를 기록합니다.
- O/X는 `choices` 를 `["O", "X"]` 로 고정합니다.
- 단답형은 `choices` 를 비우고 `answer_text` 에 정답을 넣습니다.
- 정답이 확실하지 않으면 억지로 채우지 않습니다.
- 문제 아닌 페이지 요소는 question으로 만들지 않습니다.

## Codex에게 넘길 때

NotebookLM이 JSON을 출력하면 다음 순서로 넘기면 됩니다.

1. JSON을 파일로 저장합니다.
2. 파일명과 함께 Codex에게 전달합니다.
3. 필요하면 "이 JSON을 기존 ingest 흐름에 맞게 변환해줘" 또는 "이 JSON을 앱에 import할 수 있게 연결해줘" 같이 요청합니다.

## 권장 팁

- 한 번에 PDF 전체를 처리하지 말고 챕터별로 나눠서 요청합니다.
- 정답 페이지를 따로 명시하면 answer-key 매핑이 훨씬 안정적입니다.
- OCR이 불안정한 PDF는 먼저 구조 파악 프롬프트를 실행한 뒤 범위를 더 잘게 나눕니다.
- NotebookLM이 설명을 길게 붙이면 다시 `JSON만 출력`을 강하게 요청합니다.

## Codex에게 프롬프트 생성을 요청할 때

NotebookLM에 바로 요청하기 전에, 먼저 Codex에게 PDF 구조와 원하는 문제 양식을 설명하고 맞춤형 프롬프트를 생성하게 할 수도 있습니다.

- 별도 안내: [README_NOTEBOOKLM_REQUEST_TEMPLATE.md](README_NOTEBOOKLM_REQUEST_TEMPLATE.md)
- 추천 흐름:
  1. PDF 특징과 원하는 JSON 양식을 Codex에게 설명합니다.
  2. Codex가 그 PDF에 맞는 구조 파악, 추출, 검증 프롬프트를 만들어줍니다.
  3. 그 프롬프트를 NotebookLM에 넣어 JSON을 추출합니다.
  4. 결과 JSON을 다시 Codex에게 넘겨 앱 반영을 요청합니다.
