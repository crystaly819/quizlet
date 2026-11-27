const questionListRoot = document.querySelector("[data-question-list]");

if (questionListRoot) {
  const params = new URLSearchParams(window.location.search);
  let deckSlug = params.get("deck") || "";
  const mode = ["all", "unseen", "wrong"].includes(params.get("mode")) ? params.get("mode") : "all";
  const titleEl = document.querySelector("[data-list-title]");
  const summaryEl = document.querySelector("[data-list-summary]");
  const searchEl = document.querySelector("[data-question-search]");
  const emptyEl = document.querySelector("[data-list-empty]");
  let currentDeck = null;
  let progress = {};

  function listLink(currentMode) {
    return `./questions.html?deck=${encodeURIComponent(deckSlug)}&mode=${currentMode}`;
  }

  function matchesMode(question, currentMode) {
    const record = progress[question.key];
    if (currentMode === "unseen") return !record?.seen;
    if (currentMode === "wrong") return Boolean(record?.wrong);
    return true;
  }

  function renderList() {
    if (!currentDeck) return;
    try {
      progress = JSON.parse(window.localStorage.getItem("quizlet-gh-progress-v1") || "{}") || {};
    } catch (error) {
      progress = {};
    }
    const labels = { all: "전체", unseen: "미풀이", wrong: "오답" };
    for (const link of document.querySelectorAll("[data-list-mode]")) {
      const linkMode = link.dataset.listMode;
      const count = currentDeck.questions.filter((question) => matchesMode(question, linkMode)).length;
      link.href = listLink(linkMode);
      link.textContent = `${labels[linkMode]} ${count}`;
      link.classList.toggle("active", linkMode === mode);
      if (linkMode === mode) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    }

    const search = searchEl.value.trim().toLocaleLowerCase();
    const eligible = currentDeck.questions.filter((question) => matchesMode(question, mode));
    const visible = eligible.filter((question) =>
      `${question.number}번 ${question.stem}`.toLocaleLowerCase().includes(search)
    );
    summaryEl.textContent = `${labels[mode]} ${eligible.length}문항 중 ${visible.length}문항 표시 · 이 브라우저의 풀이 기록 기준`;
    questionListRoot.innerHTML = "";
    for (const question of visible) {
      const record = progress[question.key];
      const row = document.createElement("a");
      row.className = "question-list-row";
      row.href = `./study.html?deck=${encodeURIComponent(deckSlug)}&mode=${mode}&question=${encodeURIComponent(question.key)}&order=list`;

      const number = document.createElement("strong");
      number.className = "question-list-number";
      number.textContent = `${question.number}번`;
      const content = document.createElement("span");
      content.className = "question-list-content";
      const stem = document.createElement("span");
      stem.className = "question-list-stem";
      stem.textContent = question.stem;
      const page = document.createElement("span");
      page.className = "deck-meta";
      page.textContent = `p.${question.page_number}`;
      content.appendChild(stem);
      content.appendChild(page);
      const status = document.createElement("span");
      status.className = `question-status ${record?.wrong ? "is-wrong" : record?.seen ? "is-seen" : "is-unseen"}`;
      status.textContent = record?.wrong ? "오답" : record?.seen ? "풀이 완료" : "미풀이";
      row.appendChild(number);
      row.appendChild(content);
      row.appendChild(status);
      questionListRoot.appendChild(row);
    }
    emptyEl.classList.toggle("hidden", visible.length > 0);
    emptyEl.textContent = search
      ? "검색 결과가 없습니다. 다른 검색어를 입력해 주세요."
      : mode === "wrong" ? "오답으로 기록된 문제가 없습니다."
      : mode === "unseen" ? "모든 문제를 풀었습니다. 전체 목록에서 다시 골라보세요."
      : "이 과목에 표시할 문제가 없습니다.";
  }

  searchEl.addEventListener("input", renderList);
  // Refresh saved progress when returning from a question, including browser back/forward cache.
  window.addEventListener("pageshow", renderList);
  window.addEventListener("storage", renderList);

  fetch(new URL("./data/app-data.json", window.location.href))
    .then((response) => {
      if (!response.ok) throw new Error("문제 목록을 불러오지 못했습니다. 새로고침해 주세요.");
      return response.json();
    })
    .then((data) => {
      if (!deckSlug && data.decks.length) deckSlug = data.decks[0].slug;
      currentDeck = data.decks.find((deck) => deck.slug === deckSlug);
      if (!currentDeck) {
        titleEl.textContent = "문제집을 찾을 수 없습니다";
        emptyEl.textContent = "과목 목록으로 돌아가 문제집을 다시 선택해 주세요.";
        emptyEl.classList.remove("hidden");
        return;
      }
      currentDeck.questions.sort((left, right) => left.page_number - right.page_number || String(left.number).localeCompare(String(right.number), "ko", { numeric: true }));
      titleEl.textContent = `${currentDeck.title} · 문제 목록`;
      document.title = `${currentDeck.title} 문제 목록 | 수정 예시 문제집`;
      renderList();
    })
    .catch((error) => {
      titleEl.textContent = "문제 목록 로딩 실패";
      emptyEl.textContent = error.message;
      emptyEl.classList.remove("hidden");
    });
}
