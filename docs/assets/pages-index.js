function resolveSiteAsset(relativePath) {
  const currentUrl = new URL(window.location.href);
  let pathname = currentUrl.pathname;
  if (!pathname.endsWith("/")) {
    const lastSegment = pathname.split("/").pop() || "";
    pathname = lastSegment.includes(".")
      ? pathname.slice(0, pathname.lastIndexOf("/") + 1)
      : `${pathname}/`;
  }
  return new URL(relativePath, `${currentUrl.origin}${pathname}`).toString();
}

async function loadDeckData() {
  const response = await fetch(resolveSiteAsset("data/app-data.json"));
  if (!response.ok) {
    throw new Error("정적 문제 데이터를 불러오지 못했습니다.");
  }
  return response.json();
}

function loadProgressState() {
  try {
    return JSON.parse(window.localStorage.getItem("quizlet-gh-progress-v1") || "{}");
  } catch (error) {
    return {};
  }
}

function deckProgressSummary(deck, progress) {
  let seenCount = 0;
  let wrongCount = 0;
  for (const question of deck.questions) {
    const record = progress[question.key];
    if (!record) continue;
    if (record.seen) seenCount += 1;
    if (record.wrong) wrongCount += 1;
  }
  return { seenCount, wrongCount };
}

function studyLink(deckSlug, mode) {
  return `./study.html?deck=${encodeURIComponent(deckSlug)}&mode=${encodeURIComponent(mode)}`;
}

function renderDecks(data) {
  const grid = document.querySelector("[data-deck-grid]");
  if (!grid) return;

  if (!data.decks.length) {
    grid.innerHTML = `
      <article class="empty-card">
        <h2>문제집이 아직 없습니다.</h2>
        <p>\`python -m app.export_github_pages\` 를 다시 실행해 정적 데이터를 생성해 주세요.</p>
      </article>
    `;
    return;
  }

  const progress = loadProgressState();
  grid.innerHTML = "";

  for (const deck of data.decks) {
    const summary = deckProgressSummary(deck, progress);
    const card = document.createElement("article");
    card.className = "deck-card";
    card.innerHTML = `
      <h2>${deck.title}</h2>
      <p class="deck-meta">${deck.page_count} pages · ${deck.question_count} questions</p>
      <p class="deck-meta">이 브라우저 기준 ${summary.seenCount}개 풀이 · 오답노트 ${summary.wrongCount}개</p>
      <div class="deck-actions">
        <a class="button" href="./questions.html?deck=${encodeURIComponent(deck.slug)}&mode=all">문제 목록</a>
        <a class="button" href="${studyLink(deck.slug, "all")}">전체 랜덤</a>
        <a class="button ghost" href="./questions.html?deck=${encodeURIComponent(deck.slug)}&mode=unseen">미풀이 목록</a>
        <a class="button ghost" href="./questions.html?deck=${encodeURIComponent(deck.slug)}&mode=wrong">오답 목록</a>
      </div>
    `;
    grid.appendChild(card);
  }
}

loadDeckData()
  .then(renderDecks)
  .catch((error) => {
    const grid = document.querySelector("[data-deck-grid]");
    if (!grid) return;
    grid.innerHTML = `
      <article class="empty-card">
        <h2>정적 데이터 로딩 실패</h2>
        <p>${error.message}</p>
      </article>
    `;
  });
