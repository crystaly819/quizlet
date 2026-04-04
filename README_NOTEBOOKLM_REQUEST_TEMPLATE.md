# Codex 요청 템플릿 가이드

이 문서는 "NotebookLM에 넣을 프롬프트를 Codex가 대신 만들어주게 하고 싶다"는 상황을 위한 안내입니다.

추천 흐름은 아래와 같습니다.

1. PDF 구조와 원하는 문제 양식을 Codex에게 설명합니다.
2. Codex가 그 설명을 바탕으로 NotebookLM용 프롬프트를 만듭니다.
3. 사용자는 그 프롬프트를 NotebookLM에 넣어 JSON을 추출합니다.
4. 추출된 JSON을 다시 Codex에게 넘겨 앱 반영 또는 import를 요청합니다.

## 언제 이 방식을 쓰면 좋은가

아래 같은 경우에 특히 잘 맞습니다.

- PDF마다 정답 표시 방식이 다를 때
- 섹션마다 번호가 다시 시작할 때
- 섹션 끝 정답표나 마지막 answer key를 사용해야 할 때
- 객관식, O/X, 단답형, 복수정답이 섞여 있을 때
- 문제 아닌 텍스트를 많이 걸러내야 할 때
- 룰 기반 파서만으로 커버하기 어려울 때

## 최소 요청 템플릿

먼저 아래 템플릿만 채워서 Codex에게 보내면 됩니다.

```text
PDF 파일명:

무시할 앞페이지:

문제 시작 페이지:

정답 위치:

문제 유형:
- 객관식 / OX / 단답형 / 복수정답 / 섞여있음

원하는 최종 문제 양식:
- stem
- choices
- answer
- explanation
- source_pages
- section_title
- needs_review

특이사항:
- 섹션마다 번호가 1부터 다시 시작하는지
- 한 본문에 문제 여러 개가 들어있는지
- 정답이 섹션 끝 표인지, 마지막 answer key인지
- OCR 깨짐이 있는지
- 문제 아닌 블록이 섞여 있는지

이 조건에 맞는 NotebookLM용 구조 파악 프롬프트, JSON 추출 프롬프트, 검증 프롬프트를 만들어줘.
```

## 더 정확하게 요청하는 확장 템플릿

PDF 구조가 복잡하면 아래 확장 템플릿을 쓰는 것이 좋습니다.

```text
PDF 파일명:

PDF 성격:
- 문제집 / 답지 / 해설집 / 혼합형

문제 범위:
- 시작 페이지:
- 종료 페이지:

정답 범위:
- 시작 페이지:
- 종료 페이지:

섹션 또는 챕터 구조:
- 예: Chapter 1, Chapter 2
- 또는 예: 섹션별로 끝에서 정답표 제공

문항 번호 규칙:
- 파일 전체 연속 번호 / 섹션마다 1부터 다시 시작

문제 유형:
- multiple_choice
- true_false
- short_answer
- multi_select

정답 표기 방식:
- 문제 바로 아래
- 섹션 끝 표
- 파일 마지막 정답표
- <답 ...> 형태
- 하이라이트
- 기타

원하는 JSON 필드:
- deck_title
- section_title
- question_id
- local_number
- source_pages
- question_kind
- stem
- choices
- answer
- answer_text
- explanation
- needs_review
- review_reason

버려야 하는 요소:
- 목차
- 머리말
- 꼬리말
- 페이지 번호
- 해설 전용 블록
- 예시 문제
- 문제 아닌 표/그림

품질 이슈:
- OCR 깨짐 있음 / 없음
- 띄어쓰기 깨짐 있음 / 없음
- 표 구조가 복잡함 / 단순함

Codex에게 원하는 출력:
- NotebookLM용 구조 파악 프롬프트
- NotebookLM용 JSON 추출 프롬프트
- NotebookLM용 검증 프롬프트
- NotebookLM에 바로 보낼 수 있는 짧은 요청 예시 2~3개
```

## 바로 복붙 가능한 요청 예시

### 예시 1: 섹션 끝 정답표를 쓰는 객관식 PDF

```text
PDF 파일명: [답] 생화학 분과회 문제집 답치기
무시할 앞페이지: 1~8
문제 시작 페이지: 9
정답 위치: 각 섹션 마지막 페이지 하단의 정답표
문제 유형: 객관식
원하는 최종 문제 양식:
- section_title
- local_number
- stem
- choices
- answer.choice_indices
- source_pages
- needs_review
특이사항:
- 섹션마다 번호가 1부터 다시 시작함
- 섹션 끝에서 정답이 한 번에 모여 있음
- 문제 아닌 장식이나 정답표 자체는 question으로 만들면 안 됨

이 조건에 맞는 NotebookLM용 구조 파악 프롬프트, JSON 추출 프롬프트, 검증 프롬프트를 만들어줘.
```

### 예시 2: 마지막 answer key를 쓰는 챕터형 PDF

```text
PDF 파일명: [절대보안][문제집] 약품미생물학 연습 답치기
무시할 앞페이지: 1~3
문제 시작 페이지: 4
정답 위치: p.121부터 시작하는 전체 챕터 answer key
문제 유형: 객관식 중심
원하는 최종 문제 양식:
- chapter_title
- local_number
- stem
- choices
- answer.choice_indices
- source_pages
- needs_review
특이사항:
- 챕터별로 문제와 정답을 매핑해야 함
- 일부 OCR 깨짐 가능성이 있음
- 정답이 불분명하면 추측하지 말고 needs_review=true로 남겨야 함

이 조건에 맞는 NotebookLM용 구조 파악 프롬프트, JSON 추출 프롬프트, 검증 프롬프트를 만들어줘.
```

### 예시 3: O/X와 단답형이 섞인 PDF

```text
PDF 파일명: 15. 약제학 약동학 개념확인 문제집_워터마크
무시할 앞페이지: 1~4
문제 시작 페이지: 5
정답 위치: 각 표 안의 정답 또는 해설
문제 유형: O/X와 단답형 혼합
원하는 최종 문제 양식:
- question_kind
- stem
- choices
- answer
- answer_text
- explanation
- source_pages
특이사항:
- 표의 제목에 O/X와 단답형이 나뉘어 있음
- O/X는 O/X만 선택 가능해야 함
- 단답형은 사용자가 직접 입력할 수 있어야 함
- 해설은 있으면 explanation에 넣어야 함

이 조건에 맞는 NotebookLM용 프롬프트를 만들어줘.
```

## Codex가 프롬프트를 더 잘 만들어주도록 돕는 정보

아래 정보가 있으면 결과가 더 좋아집니다.

- 실제 문제가 시작되는 페이지
- 정답이 있는 페이지 또는 블록
- 번호가 섹션마다 리셋되는지 여부
- 한 본문에 여러 문제가 들어가는지 여부
- 정답 표현이 숫자, O/X, 단답 텍스트 중 무엇인지
- 문제 아닌 텍스트가 어디에 많이 섞이는지
- OCR이 필요한 페이지가 있는지

## Codex에게 이렇게 요청하면 됩니다

아래 한 줄 요청으로도 충분합니다.

```text
이 PDF 구조와 내가 원하는 문제 JSON 양식을 설명할 테니, 그 조건에 맞는 NotebookLM용 구조 파악 프롬프트, JSON 추출 프롬프트, 검증 프롬프트를 만들어줘.
```

## 그 다음 단계

Codex가 프롬프트를 만들어주면 아래 순서로 이어가면 됩니다.

1. NotebookLM에 프롬프트를 넣습니다.
2. JSON 결과를 저장합니다.
3. Codex에게 JSON 파일을 넘깁니다.
4. 필요하면 "이 JSON을 앱에 import할 수 있게 연결해줘" 라고 요청합니다.
