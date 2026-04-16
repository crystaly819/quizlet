const root = document.querySelector("[data-study-app]");

if (root) {
  const deckId = root.dataset.deckId;
  const mode = root.dataset.mode;

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
  const reviewLinkEl = document.getElementById("review-link");
  const emptyStateEl = document.getElementById("empty-state");
  const previewEl = document.getElementById("question-preview");
  const previewToggleEl = document.getElementById("preview-toggle");
  const previewAutoToggleEl = document.getElementById("preview-auto-toggle");
  const previewEmptyEl = document.getElementById("preview-empty");
  const manualReviewBadgeEl = document.getElementById("manual-review-badge");
  const manualReviewNoteEl = document.getElementById("manual-review-note");
  const previewAutoStorageKey = "quizlet-preview-auto-visible";

  let currentQuestion = null;
  let selectedMultiIndices = new Set();
  let previewAutoVisible = false;
  try {
    previewAutoVisible = window.localStorage.getItem(previewAutoStorageKey) === "1";
  } catch (error) {
    previewAutoVisible = false;
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

  function resetPreview() {
    previewEl.classList.add("hidden");
    previewEl.removeAttribute("src");
    previewToggleEl.disabled = true;
    previewToggleEl.textContent = "원문 보기";
    previewEmptyEl.textContent = "원문은 기본으로 숨겨져 있습니다.";
    previewEmptyEl.classList.remove("hidden");
    manualReviewBadgeEl.classList.add("hidden");
    manualReviewNoteEl.classList.add("hidden");
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

  function resetReviewLink() {
    reviewLinkEl.classList.add("hidden");
    reviewLinkEl.setAttribute("href", "/review");
  }

  function configureReviewLink(question) {
    resetReviewLink();
    if (!question.review_url) {
      return;
    }
    reviewLinkEl.setAttribute("href", question.review_url);
    reviewLinkEl.classList.remove("hidden");
  }

  function setEmptyState(message) {
    currentQuestion = null;
    numberEl.textContent = "문항 없음";
    pageEl.textContent = "";
    stemEl.textContent = "";
    resetAnswerInputs();
    resetFeedback();
    emptyStateEl.textContent = message;
    emptyStateEl.classList.remove("hidden");
    resetPreview();
    resetReviewLink();
  }

  function configurePreview(question) {
    resetPreview();
    if (!question.crop_url) {
      previewToggleEl.textContent = "원문 없음";
      previewEmptyEl.textContent = "이 문항은 원문 crop이 없습니다.";
      if (question.manual_reviewed) {
        manualReviewBadgeEl.classList.remove("hidden");
        manualReviewNoteEl.classList.remove("hidden");
      }
      return;
    }

    previewEl.src = question.crop_url;
    previewToggleEl.disabled = false;
    applyPreviewVisibility();
    if (question.manual_reviewed) {
      manualReviewBadgeEl.classList.remove("hidden");
      manualReviewNoteEl.classList.remove("hidden");
    }
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

  function showFeedback(message, variant) {
    feedbackEl.className = `answer-feedback ${variant}`;
    feedbackEl.textContent = message;
  }

  function disableChoiceButtons() {
    for (const button of choiceListEl.querySelectorAll("button")) {
      button.disabled = true;
    }
  }

  async function requestAttempt(payload) {
    const response = await fetch("/api/attempts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "채점 중 오류가 발생했습니다.");
    }
    return data;
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

  async function loadNextQuestion() {
    resetFeedback();
    resetAnswerInputs();
    emptyStateEl.classList.add("hidden");
    numberEl.textContent = "문항을 불러오는 중...";
    pageEl.textContent = "";
    stemEl.textContent = "";
    resetPreview();
    resetReviewLink();

    const response = await fetch(`/api/decks/${deckId}/next?mode=${mode}`);
    const data = await response.json();

    if (!data.question) {
      setEmptyState("현재 모드에서 더 이상 보여줄 문항이 없습니다.");
      return;
    }

    currentQuestion = data.question;
    numberEl.textContent = `${data.question.number}번`;
    pageEl.textContent = `p.${data.question.page_number}`;
    stemEl.textContent = data.question.stem;
    configurePreview(data.question);
    configureReviewLink(data.question);
    renderQuestion(data.question);
  }

  function revealFlashcardAnswer() {
    if (!currentQuestion) return;

    showFeedback(`정답: ${currentQuestion.answer_text || "정답 없음"}`, "reveal");
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

  async function submitChoice(selectedIndex) {
    if (!currentQuestion) return;

    try {
      const data = await requestAttempt({
        question_id: currentQuestion.id,
        selected_index: selectedIndex,
      });

      disableChoiceButtons();
      if (data.question_kind === "true_false") {
        const label = data.correct_text || (data.correct_index === 1 ? "O" : "X");
        showFeedback(
          data.is_correct ? `정답입니다. 정답: ${label}` : `오답입니다. 정답은 ${label}`,
          data.is_correct ? "correct" : "incorrect"
        );
      } else if (data.question_kind === "multi_select") {
        showFeedback(
          data.is_correct
            ? `정답입니다. 정답: ${data.correct_text}`
            : `오답입니다. 정답은 ${data.correct_text}`,
          data.is_correct ? "correct" : "incorrect"
        );
      } else {
        showFeedback(
          data.is_correct
            ? `정답입니다. ${data.correct_index}번: ${data.correct_text}`
            : `오답입니다. 정답은 ${data.correct_index}번: ${data.correct_text}`,
          data.is_correct ? "correct" : "incorrect"
        );
      }
      maybeShowExplanation(data.explanation_text);
      nextButton.classList.remove("hidden");
    } catch (error) {
      showFeedback(error.message, "incorrect");
    }
  }

  async function submitMultiSelect() {
    if (!currentQuestion) return;
    const selectedIndices = [...selectedMultiIndices].sort((left, right) => left - right);
    if (selectedIndices.length === 0) {
      showFeedback("정답이라고 생각하는 보기를 하나 이상 선택해 주세요.", "incorrect");
      return;
    }

    try {
      const data = await requestAttempt({
        question_id: currentQuestion.id,
        selected_indices: selectedIndices,
      });

      disableChoiceButtons();
      multiSelectSubmitEl.disabled = true;
      showFeedback(
        data.is_correct
          ? `정답입니다. 정답: ${data.correct_text}`
          : `오답입니다. 정답은 ${data.correct_text}`,
        data.is_correct ? "correct" : "incorrect"
      );
      maybeShowExplanation(data.explanation_text);
      nextButton.classList.remove("hidden");
    } catch (error) {
      showFeedback(error.message, "incorrect");
    }
  }

  async function submitShortAnswer(event) {
    event.preventDefault();
    if (!currentQuestion) return;

    const answerInput = shortAnswerInputEl.value.trim();
    if (!answerInput) {
      showFeedback("정답을 입력한 뒤 확인해 주세요.", "incorrect");
      return;
    }

    try {
      const data = await requestAttempt({
        question_id: currentQuestion.id,
        answer_input: answerInput,
      });

      shortAnswerInputEl.disabled = true;
      shortAnswerSubmitEl.disabled = true;
      showFeedback(
        data.is_correct ? `정답입니다. 정답: ${data.correct_text}` : `오답입니다. 정답은 ${data.correct_text}`,
        data.is_correct ? "correct" : "incorrect"
      );
      maybeShowExplanation(data.explanation_text);
      nextButton.classList.remove("hidden");
    } catch (error) {
      showFeedback(error.message, "incorrect");
    }
  }

  async function submitFlashcardResult(wasCorrect) {
    if (!currentQuestion) return;

    try {
      const data = await requestAttempt({
        question_id: currentQuestion.id,
        was_correct: wasCorrect,
      });

      flashcardControlsEl.classList.add("hidden");
      showFeedback(
        data.is_correct
          ? `정답을 맞혔다고 체크했습니다. 정답: ${data.correct_text}`
          : `오답노트에 기록했습니다. 정답: ${data.correct_text}`,
        data.is_correct ? "correct" : "incorrect"
      );
      maybeShowExplanation(data.explanation_text);
      nextButton.classList.remove("hidden");
    } catch (error) {
      showFeedback(error.message, "incorrect");
    }
  }

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

  explanationToggleEl.addEventListener("click", () => {
    const isHidden = explanationTextEl.classList.contains("hidden");
    explanationTextEl.classList.toggle("hidden", !isHidden);
    explanationToggleEl.textContent = isHidden ? "해설 숨기기" : "해설 보기";
  });

  shortAnswerFormEl.addEventListener("submit", submitShortAnswer);
  multiSelectSubmitEl.addEventListener("click", submitMultiSelect);
  nextButton.addEventListener("click", loadNextQuestion);
  updatePreviewAutoToggleLabel();
  loadNextQuestion();
}
