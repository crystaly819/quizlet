const studyRoot = document.querySelector("[data-static-study-app]");

if (studyRoot) {
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

  const params = new URLSearchParams(window.location.search);
  const deckSlug = params.get("deck") || "";
  const mode = ["all", "unseen", "wrong"].includes(params.get("mode")) ? params.get("mode") : "all";
  const progressStorageKey = "quizlet-gh-progress-v1";
  const previewAutoStorageKey = "quizlet-preview-auto-visible";

  const titleEl = document.querySelector("[data-study-title]");
  const metaEl = document.querySelector("[data-study-meta]");
  const progressSummaryEl = document.querySelector("[data-progress-summary]");
  const progressDetailEl = document.querySelector("[data-progress-detail]");
  const numberEl = document.getElementById("question-number");
  const pageEl = document.getElementById("question-page");
  const stemEl = document.getElementById("question-stem");
  const choiceListEl = document.getElementById("choice-list");
  const shortAnswerFormEl = document.getElementById("short-answer-form");
  const shortAnswerInputEl = document.getElementById("short-answer-input");
  const shortAnswerSubmitEl = document.getElementById("short-answer-submit");
  const selectionControlsEl = document.getElementById("selection-controls");
  const multiSelectSubmitEl = document.getElementById("multi-select-submit");
  const feedbackEl = document.getElementById("answer-feedback");
  const flashcardControlsEl = document.getElementById("flashcard-controls");
  const explanationActionsEl = document.getElementById("explanation-actions");
  const explanationToggleEl = document.getElementById("explanation-toggle");
  const explanationTextEl = document.getElementById("explanation-text");
  const nextButton = document.getElementById("next-button");
  const emptyStateEl = document.getElementById("empty-state");
  const previewEl = document.getElementById("question-preview");
  const previewToggleEl = document.getElementById("preview-toggle");
  const previewAutoToggleEl = document.getElementById("preview-auto-toggle");
  const previewEmptyEl = document.getElementById("preview-empty");
  const manualReviewBadgeEl = document.getElementById("manual-review-badge");
  const manualReviewNoteEl = document.getElementById("manual-review-note");

  let currentDeck = null;
  let currentQuestion = null;
  let selectedMultiIndices = new Set();
  let previewAutoVisible = false;
  let progressState = loadProgressState();

  try {
    previewAutoVisible = window.localStorage.getItem(previewAutoStorageKey) === "1";
  } catch (error) {
    previewAutoVisible = false;
  }

  function loadProgressState() {
    try {
      return JSON.parse(window.localStorage.getItem(progressStorageKey) || "{}");
    } catch (error) {
      return {};
    }
  }

  function saveProgressState() {
    try {
      window.localStorage.setItem(progressStorageKey, JSON.stringify(progressState));
    } catch (error) {
      // Ignore storage failures and keep the page usable for the current session.
    }
  }

  function normalizeAnswerText(value) {
    return (value || "").toLowerCase().replace(/\s+/g, "");
  }

  function deckStudyLink(slug, currentMode) {
    return `./study.html?deck=${encodeURIComponent(slug)}&mode=${encodeURIComponent(currentMode)}`;
  }

  function updateModeLinks() {
    for (const link of document.querySelectorAll("[data-mode-link]")) {
      const linkMode = link.dataset.modeLink;
      link.href = deckStudyLink(deckSlug, linkMode);
      link.classList.toggle("active", linkMode === mode);
    }
  }

  function updateProgressSummary() {
    if (!currentDeck) {
      progressSummaryEl.textContent = "0 / 0";
      progressDetailEl.textContent = "문제집을 불러오는 중입니다.";
      return;
    }
    let seen = 0;
    let wrong = 0;
    for (const question of currentDeck.questions) {
      const record = progressState[question.key];
      if (!record) continue;
      if (record.seen) seen += 1;
      if (record.wrong) wrong += 1;
    }
    progressSummaryEl.textContent = `${seen} / ${currentDeck.questions.length}`;
    progressDetailEl.textContent = `현재 브라우저 기준 오답노트 ${wrong}개 · 모드 ${modeLabel(mode)}`;
  }

  function modeLabel(currentMode) {
    if (currentMode === "unseen") return "미풀이";
    if (currentMode === "wrong") return "오답노트";
    return "전체 랜덤";
  }

  function eligibleQuestions() {
    if (!currentDeck) return [];
    if (mode === "unseen") {
      return currentDeck.questions.filter((question) => !progressState[question.key]?.seen);
    }
    if (mode === "wrong") {
      return currentDeck.questions.filter((question) => progressState[question.key]?.wrong);
    }
    return currentDeck.questions;
  }

  function randomQuestion(questions) {
    if (!questions.length) return null;
    const randomIndex = Math.floor(Math.random() * questions.length);
    return questions[randomIndex];
  }

  function resetFeedback() {
    feedbackEl.className = "answer-feedback hidden";
    feedbackEl.textContent = "";
    flashcardControlsEl.classList.add("hidden");
    flashcardControlsEl.innerHTML = "";
    explanationActionsEl.classList.add("hidden");
    explanationToggleEl.textContent = "해설 보기";
    explanationTextEl.classList.add("hidden");
    explanationTextEl.textContent = "";
    nextButton.classList.add("hidden");
  }

  function resetAnswerInputs() {
    choiceListEl.innerHTML = "";
    shortAnswerFormEl.classList.add("hidden");
    shortAnswerInputEl.value = "";
    shortAnswerInputEl.disabled = false;
    shortAnswerSubmitEl.disabled = false;
    selectionControlsEl.classList.add("hidden");
    multiSelectSubmitEl.disabled = false;
    selectedMultiIndices = new Set();
  }

  function resetReviewIndicators() {
    manualReviewBadgeEl.classList.add("hidden");
    manualReviewNoteEl.classList.add("hidden");
  }

  function resetPreview() {
    previewEl.classList.add("hidden");
    previewEl.removeAttribute("src");
    previewToggleEl.disabled = true;
    previewToggleEl.textContent = "원문 보기";
    previewEmptyEl.textContent = "원문은 기본으로 숨겨져 있습니다.";
    previewEmptyEl.classList.remove("hidden");
  }

  function updatePreviewAutoToggleLabel() {
    previewAutoToggleEl.textContent = `전체 자동 보기: ${previewAutoVisible ? "켬" : "끔"}`;
  }

  function showPreview() {
    if (!previewEl.getAttribute("src")) {
      return;
    }
    previewEl.classList.remove("hidden");
    previewEmptyEl.classList.add("hidden");
    previewToggleEl.textContent = "원문 숨기기";
  }

  function hidePreview() {
    previewEl.classList.add("hidden");
    previewEmptyEl.textContent = "원문은 기본으로 숨겨져 있습니다.";
    previewEmptyEl.classList.remove("hidden");
    previewToggleEl.textContent = "원문 보기";
  }

  function applyPreviewVisibility() {
    if (!previewEl.getAttribute("src")) {
      hidePreview();
      return;
    }
    if (previewAutoVisible) {
      showPreview();
      return;
    }
    hidePreview();
  }

  function configurePreview(question) {
    resetPreview();
    if (!question.preview_src) {
      previewToggleEl.textContent = "원문 없음";
      previewEmptyEl.textContent = "이 문항은 정적 export에 포함된 원문 미리보기가 없습니다.";
      return;
    }
    previewEl.src = resolveSiteAsset(question.preview_src);
    previewToggleEl.disabled = false;
    applyPreviewVisibility();
  }

  function setEmptyState(message) {
    currentQuestion = null;
    numberEl.textContent = "문항 없음";
    pageEl.textContent = "";
    stemEl.textContent = "";
    resetAnswerInputs();
    resetFeedback();
    resetReviewIndicators();
    resetPreview();
    emptyStateEl.textContent = message;
    emptyStateEl.classList.remove("hidden");
  }

  function showFeedback(message, variant) {
    feedbackEl.className = `answer-feedback ${variant}`;
    feedbackEl.textContent = message;
  }

  function maybeShowExplanation(explanationText) {
    const trimmed = (explanationText || "").trim();
    if (!trimmed) {
      explanationActionsEl.classList.add("hidden");
      explanationTextEl.classList.add("hidden");
      explanationTextEl.textContent = "";
      return;
    }
    explanationTextEl.textContent = trimmed;
    explanationTextEl.classList.add("hidden");
    explanationToggleEl.textContent = "해설 보기";
    explanationActionsEl.classList.remove("hidden");
  }

  function disableChoiceButtons() {
    for (const button of choiceListEl.querySelectorAll("button")) {
      button.disabled = true;
    }
  }

  function updateQuestionRecord(question, isCorrect) {
    const previous = progressState[question.key] || { seen: false, wrong: false, attempts: 0 };
    progressState[question.key] = {
      seen: true,
      wrong: previous.wrong || !isCorrect,
      attempts: (previous.attempts || 0) + 1,
      lastCorrect: isCorrect,
      updatedAt: Date.now(),
    };
    saveProgressState();
    updateProgressSummary();
  }

  function renderChoices(question) {
    for (const choice of question.choices) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "choice-button";
      if (question.question_kind === "true_false") {
        button.classList.add("binary-choice");
      }
      button.textContent =
        question.question_kind === "true_false" ? choice.text : `${choice.index}. ${choice.text}`;
      if (question.question_kind === "multi_select") {
        button.addEventListener("click", () => toggleMultiSelectChoice(button, choice.index));
      } else {
        button.addEventListener("click", () => submitChoice(choice.index));
      }
      choiceListEl.appendChild(button);
    }
  }

  function renderQuestion(question) {
    resetAnswerInputs();
    resetFeedback();
    resetReviewIndicators();
    emptyStateEl.classList.add("hidden");

    currentQuestion = question;
    numberEl.textContent = `${question.number}번`;
    pageEl.textContent = `p.${question.page_number}`;
    stemEl.textContent = question.stem;
    configurePreview(question);
    if (question.manual_reviewed) {
      manualReviewBadgeEl.classList.remove("hidden");
      manualReviewNoteEl.classList.remove("hidden");
    }

    if (question.question_kind === "flashcard") {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "button";
      button.textContent = "정답 보기";
      button.addEventListener("click", revealFlashcardAnswer);
      choiceListEl.appendChild(button);
      return;
    }

    if (question.question_kind === "short_answer") {
      shortAnswerFormEl.classList.remove("hidden");
      window.setTimeout(() => shortAnswerInputEl.focus(), 0);
      return;
    }

    renderChoices(question);
    if (question.question_kind === "multi_select") {
      selectionControlsEl.classList.remove("hidden");
    }
  }

  function loadNextQuestion() {
    const nextQuestion = randomQuestion(eligibleQuestions());
    if (!nextQuestion) {
      setEmptyState("현재 모드에서 더 이상 보여줄 문항이 없습니다.");
      return;
    }
    renderQuestion(nextQuestion);
  }

  function toggleMultiSelectChoice(button, choiceIndex) {
    if (button.disabled) return;
    if (selectedMultiIndices.has(choiceIndex)) {
      selectedMultiIndices.delete(choiceIndex);
      button.classList.remove("selected");
      return;
    }
    selectedMultiIndices.add(choiceIndex);
    button.classList.add("selected");
  }

  function revealFlashcardAnswer() {
    if (!currentQuestion) return;
    showFeedback(`정답: ${currentQuestion.correct_text || "정답 없음"}`, "reveal");
    maybeShowExplanation(currentQuestion.explanation_text);
    flashcardControlsEl.classList.remove("hidden");
    flashcardControlsEl.innerHTML = "";

    const correctButton = document.createElement("button");
    correctButton.type = "button";
    correctButton.className = "button";
    correctButton.textContent = "맞았음";
    correctButton.addEventListener("click", () => submitFlashcardResult(true));

    const wrongButton = document.createElement("button");
    wrongButton.type = "button";
    wrongButton.className = "button ghost";
    wrongButton.textContent = "틀렸음";
    wrongButton.addEventListener("click", () => submitFlashcardResult(false));

    flashcardControlsEl.appendChild(correctButton);
    flashcardControlsEl.appendChild(wrongButton);
    disableChoiceButtons();
  }

  function submitFlashcardResult(wasCorrect) {
    if (!currentQuestion) return;
    updateQuestionRecord(currentQuestion, wasCorrect);
    flashcardControlsEl.classList.add("hidden");
    showFeedback(
      wasCorrect
        ? `정답을 맞혔다고 체크했습니다. 정답: ${currentQuestion.correct_text || ""}`
        : `오답노트에 기록했습니다. 정답: ${currentQuestion.correct_text || ""}`,
      wasCorrect ? "correct" : "incorrect"
    );
    maybeShowExplanation(currentQuestion.explanation_text);
    nextButton.classList.remove("hidden");
  }

  function submitChoice(selectedIndex) {
    if (!currentQuestion) return;
    let isCorrect = false;

    if (currentQuestion.question_kind === "true_false") {
      isCorrect = selectedIndex === currentQuestion.correct_index;
      showFeedback(
        isCorrect
          ? `정답입니다. 정답: ${currentQuestion.correct_text}`
          : `오답입니다. 정답은 ${currentQuestion.correct_text}`,
        isCorrect ? "correct" : "incorrect"
      );
    } else {
      isCorrect = selectedIndex === currentQuestion.correct_index;
      showFeedback(
        isCorrect
          ? `정답입니다. ${currentQuestion.correct_index}번: ${currentQuestion.correct_text}`
          : `오답입니다. 정답은 ${currentQuestion.correct_index}번: ${currentQuestion.correct_text}`,
        isCorrect ? "correct" : "incorrect"
      );
    }

    disableChoiceButtons();
    updateQuestionRecord(currentQuestion, isCorrect);
    maybeShowExplanation(currentQuestion.explanation_text);
    nextButton.classList.remove("hidden");
  }

  function submitMultiSelect() {
    if (!currentQuestion) return;
    const selectedIndices = [...selectedMultiIndices].sort((left, right) => left - right);
    if (!selectedIndices.length) {
      showFeedback("정답이라고 생각하는 보기를 하나 이상 선택해 주세요.", "incorrect");
      return;
    }

    const correctIndices = [...(currentQuestion.correct_indices || [])].sort((left, right) => left - right);
    const isCorrect =
      selectedIndices.length === correctIndices.length &&
      selectedIndices.every((value, index) => value === correctIndices[index]);

    disableChoiceButtons();
    multiSelectSubmitEl.disabled = true;
    updateQuestionRecord(currentQuestion, isCorrect);
    showFeedback(
      isCorrect
        ? `정답입니다. 정답: ${currentQuestion.correct_text}`
        : `오답입니다. 정답은 ${currentQuestion.correct_text}`,
      isCorrect ? "correct" : "incorrect"
    );
    maybeShowExplanation(currentQuestion.explanation_text);
    nextButton.classList.remove("hidden");
  }

  function submitShortAnswer(event) {
    event.preventDefault();
    if (!currentQuestion) return;

    const submitted = shortAnswerInputEl.value.trim();
    if (!submitted) {
      showFeedback("정답을 입력한 뒤 확인해 주세요.", "incorrect");
      return;
    }

    const isCorrect = normalizeAnswerText(submitted) === normalizeAnswerText(currentQuestion.answer_text);
    shortAnswerInputEl.disabled = true;
    shortAnswerSubmitEl.disabled = true;
    updateQuestionRecord(currentQuestion, isCorrect);
    showFeedback(
      isCorrect
        ? `정답입니다. 정답: ${currentQuestion.correct_text}`
        : `오답입니다. 정답은 ${currentQuestion.correct_text}`,
      isCorrect ? "correct" : "incorrect"
    );
    maybeShowExplanation(currentQuestion.explanation_text);
    nextButton.classList.remove("hidden");
  }

  explanationToggleEl.addEventListener("click", () => {
    const isHidden = explanationTextEl.classList.contains("hidden");
    explanationTextEl.classList.toggle("hidden", !isHidden);
    explanationToggleEl.textContent = isHidden ? "해설 숨기기" : "해설 보기";
  });

  previewToggleEl.addEventListener("click", () => {
    if (previewToggleEl.disabled || !previewEl.getAttribute("src")) {
      return;
    }

    const isHidden = previewEl.classList.contains("hidden");
    if (isHidden) {
      showPreview();
      return;
    }

    hidePreview();
  });

  previewAutoToggleEl.addEventListener("click", () => {
    previewAutoVisible = !previewAutoVisible;
    try {
      window.localStorage.setItem(previewAutoStorageKey, previewAutoVisible ? "1" : "0");
    } catch (error) {
      // Ignore storage failures and keep the in-memory toggle working.
    }
    updatePreviewAutoToggleLabel();
    applyPreviewVisibility();
  });

  shortAnswerFormEl.addEventListener("submit", submitShortAnswer);
  multiSelectSubmitEl.addEventListener("click", submitMultiSelect);
  nextButton.addEventListener("click", loadNextQuestion);
  updatePreviewAutoToggleLabel();

  fetch(resolveSiteAsset("data/app-data.json"))
    .then((response) => {
      if (!response.ok) {
        throw new Error("정적 문제 데이터를 불러오지 못했습니다.");
      }
      return response.json();
    })
    .then((data) => {
      currentDeck = data.decks.find((deck) => deck.slug === deckSlug) || null;
      updateModeLinks();
      if (!currentDeck) {
        titleEl.textContent = "문제집을 찾을 수 없습니다";
        metaEl.textContent = "잘못된 deck 링크이거나 export 데이터가 오래되었습니다.";
        setEmptyState("선택한 문제집을 찾을 수 없습니다.");
        return;
      }
      titleEl.textContent = currentDeck.title;
      metaEl.textContent = `${currentDeck.approved_count} approved · localStorage 기반 ${modeLabel(mode)} 모드`;
      document.title = `${currentDeck.title} | 수정 예시 문제집`;
      updateProgressSummary();
      loadNextQuestion();
    })
    .catch((error) => {
      titleEl.textContent = "데이터 로딩 실패";
      metaEl.textContent = error.message;
      setEmptyState(error.message);
    });
}
