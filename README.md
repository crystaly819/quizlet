# PDF Quizlet

`pdfs/` 폴더에 있는 PDF를 문제집처럼 가져와서, 웹에서 랜덤으로 풀고 정답과 해설을 확인하는 로컬 학습 앱입니다.

지원하는 문제 유형:
- 객관식: 노란 하이라이트로 정답 자동 추출
- O/X: `O`, `X` 버튼으로 풀이
- 단답형: 답을 직접 입력해서 채점
- R형 다중선택: 여러 보기 중 2개 이상을 고르는 문제를 체크 후 제출

원문 미리보기는 기본으로 숨겨져 있고, 필요할 때만 펼쳐서 볼 수 있습니다. PNG 파일로 따로 저장하지 않고 PDF에서 바로 렌더링합니다. 해설도 자동으로 열리지 않고, 답을 확인한 뒤 선택적으로 볼 수 있습니다.
학습 중 잘못 승인된 문항을 발견하면 `이 문항 수정` 버튼으로 수동 검수 화면을 열어 정답을 바로잡을 수 있습니다. 수동 검수된 문항은 원문 미리보기 영역에서 표시됩니다.

## 설치

Python 3.11 기준입니다.

```bash
python3 -m pip install -r requirements.txt
```

## 실행

처음 시작하거나 PDF를 새로 넣은 뒤에는 한 번 ingest를 돌리는 것이 가장 안전합니다.

```bash
python3 -m app.ingest pdfs --rebuild
uvicorn app.main:app --reload
```

브라우저에서 `http://127.0.0.1:8000` 을 열면 됩니다.

다른 기기에서도 열고 싶다면 LAN 모드로 실행하면 됩니다.

```bash
python3 -m app.ingest pdfs --rebuild
python3 -m app.serve --reload
```

터미널에 `다른 기기(같은 와이파이)` 주소가 함께 출력됩니다. 같은 Wi-Fi에 연결된 폰이나 태블릿에서 그 주소를 열면 됩니다.

로컬 전용으로만 열고 싶다면 아래처럼 실행합니다.

```bash
python3 -m app.serve --reload --local-only
```

같은 와이파이가 아니어도 열 수 있는 공개 링크가 필요하면 아래처럼 실행합니다.

```bash
python3 -m app.serve --share
```

터미널에 `공개 링크(어디서든 접속)` 주소가 뜨면 그 링크를 그대로 아이폰, 아이패드, 또는 다른 네트워크의 기기에서 Safari로 열면 됩니다. 링크는 서버가 켜져 있는 동안만 유지됩니다.

## Render 배포

Codex나 로컬 터미널을 켜두지 않고 항상 열리게 하려면 Render 웹 서비스로 배포하면 됩니다.

이 저장소에는 Render용 설정 파일 [`render.yaml`](/Users/crystal/Documents/quizlet/render.yaml) 이 포함되어 있습니다.

### 배포 절차

1. 이 저장소를 GitHub에 푸시합니다.
2. Render에서 `New +` → `Blueprint` 를 선택하고 이 저장소를 연결합니다.
3. `render.yaml` 내용을 확인한 뒤 배포를 생성합니다.
4. 첫 배포가 끝나면 Render가 발급한 `onrender.com` 주소로 접속합니다.

### 현재 설정

- 시작 명령은 `python -m app.render_boot` 입니다.
- 첫 배포에서 `data/` 디스크가 비어 있으면 `pdfs/` 의 PDF를 자동 ingest 한 뒤 서버를 시작합니다.
- 이후 재배포에서는 기존 SQLite DB와 캐시를 유지하고, 데이터가 이미 있으면 자동 ingest 를 건너뜁니다.
- 영구 데이터는 `/opt/render/project/src/data` 에 마운트된 persistent disk 에 저장됩니다.

### PDF나 파서를 바꿨을 때

배포 후에 PDF 파일을 교체했거나 파싱 로직을 바꿨다면, Render 환경 변수 `QUIZLET_RENDER_FORCE_REBUILD=1` 로 한 번 배포해서 DB를 다시 만들 수 있습니다. 반영이 끝나면 다시 `0` 으로 돌려두는 편이 안전합니다.

주의:
이 재빌드는 기존 학습 기록, 오답 기록, 수동 검수 내용도 함께 다시 만들어질 수 있습니다.

## GitHub Pages 배포

서버 없이 무료로 열고 싶다면 GitHub Pages용 정적 버전도 사용할 수 있습니다.

### 포함 기능

- deck 목록 보기
- 전체 랜덤 / 미풀이 / 오답노트 풀이
- 브라우저 localStorage 기반 학습 기록 저장
- 집중 타이머

### 제외 기능

- `/review` 검수 화면
- 서버 DB 동기화
- 여러 기기 간 학습 기록 동기화

### 미리보기 동작

GitHub Pages 버전도 원문 미리보기를 지원합니다. 다만 서버에서 즉석 crop API를 호출하는 대신, export 시점에 미리 PNG를 만들어 `docs/previews/` 아래에 넣는 방식입니다.

### export 방법

기존 ingest가 끝난 상태에서 아래 명령을 실행하면 `docs/` 아래에 GitHub Pages용 정적 데이터가 생성됩니다.

```bash
python3 -m app.export_github_pages
```

이 명령은 아래를 갱신합니다.

- `docs/data/app-data.json`
- `docs/assets/styles.css`
- `docs/assets/timer.js`
- `docs/.nojekyll`

`docs/index.html`, `docs/study.html`, `docs/timer.html` 은 정적 앱 셸로 유지됩니다.

### GitHub Pages 설정

1. GitHub 저장소 `Settings`
2. `Pages`
3. `Build and deployment` 에서 `Deploy from a branch`
4. Branch 는 `main`
5. Folder 는 `/docs`
6. 저장 후 배포 완료까지 잠시 대기

배포 주소는 보통 `https://<username>.github.io/<repo>/` 형태입니다.

## 새 PDF 추가하는 법

1. 새 PDF를 [`pdfs/`](/Users/byungjun/workspace/Quizlet/pdfs) 안에 넣습니다.
2. 아래 명령으로 DB와 파싱 캐시를 다시 만듭니다.

```bash
python3 -m app.ingest pdfs --rebuild
```

3. 서버가 켜져 있으면 브라우저를 새로고침합니다.
4. 자동으로 확신하지 못한 문항은 `/review` 화면에서 수정 후 승인하거나, 실제 문제가 아닌 경우 버릴 수 있습니다.

`--rebuild` 는 기존 `data/app.db`와 파싱 캐시를 기준에 맞춰 다시 만드는 방식입니다. 파서를 수정했거나 PDF가 추가/교체됐으면 `--rebuild` 사용을 권장합니다.

## NotebookLM 가이드

규칙 기반 파싱으로 커버하기 어려운 PDF는 NotebookLM으로 구조화 JSON을 먼저 뽑아오는 워크플로우를 사용할 수 있습니다.

- 별도 안내: [README_NOTEBOOKLM.md](README_NOTEBOOKLM.md)
- 요청 템플릿: [README_NOTEBOOKLM_REQUEST_TEMPLATE.md](README_NOTEBOOKLM_REQUEST_TEMPLATE.md)
- 포함 내용: 구조 파악 프롬프트, JSON 추출 프롬프트, 검증 프롬프트, JSON 스키마, 복붙용 요청 예시

## 폴더 구조

- [`app/`](/Users/byungjun/workspace/Quizlet/app): FastAPI 서버, 파서, 템플릿, 정적 파일
- [`pdfs/`](/Users/byungjun/workspace/Quizlet/pdfs): 원본 PDF 보관 폴더
- `data/app.db`: SQLite 데이터베이스
- `data/cache/`: 파싱 결과 JSON
- [`tests/`](/Users/byungjun/workspace/Quizlet/tests): 테스트

## 주요 화면

- `/`: 문제집 목록
- `/decks/{deck_id}/study?mode=all`: 전체 랜덤
- `/decks/{deck_id}/study?mode=unseen`: 미풀이만
- `/decks/{deck_id}/study?mode=wrong`: 오답노트
- `/review`: 저신뢰 문항 검수

## 테스트

빠른 테스트:

```bash
python3 -m pytest tests/test_parser.py tests/test_web.py -q
```

실제 PDF까지 확인:

```bash
python3 -m pytest tests/test_real_pdfs.py -q -m integration
```

OCR 가능성만 빠르게 확인:

```bash
python3 -m app.ocr_probe "pdfs/파일명.pdf" --pages 121 122 --lang eng+snum --psm 6 --dpi 300
```

## 메모

- 기존 DB 스키마가 오래된 상태여도 앱 시작 시 필요한 컬럼은 자동 보강합니다.
- 다만 새 파싱 규칙을 실제 문제 데이터에 반영하려면 `python3 -m app.ingest pdfs --rebuild` 를 다시 실행해야 합니다.
- 단답형/OX 중심 PDF의 공백 없는 한글 문장은 `kiwipiepy` 기반 spacing 복원을 거칩니다.
- 현재 범위는 디지털 텍스트 기반 PDF 중심입니다. 표/그림 위주 문항이나 애매한 문항은 검수 큐로 보냅니다.
