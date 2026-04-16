const timerRoots = document.querySelectorAll("[data-focus-timer]");

if (timerRoots.length > 0) {
  const storageKey = "quizlet-focus-timer-state-v1";
  const defaultRoot = timerRoots[0];
  const defaultFocusMinutes = Number.parseInt(defaultRoot.dataset.focusMinutes || "90", 10);
  const defaultBreakMinutes = Number.parseInt(defaultRoot.dataset.breakMinutes || "15", 10);
  const ambientModes = {
    none: "꺼짐",
    rain: "비 오는 소리",
    library: "도서관 소음",
    forest: "숲 소리",
    stream: "시냇물",
    waves: "파도 소리",
    white: "화이트 노이즈",
    brown: "브라운 노이즈",
  };
  const ambientAudioSupported = Boolean(window.AudioContext || window.webkitAudioContext);

  const displayEls = document.querySelectorAll("[data-timer-display]");
  const phaseEls = document.querySelectorAll("[data-timer-phase]");
  const phaseShortEls = document.querySelectorAll("[data-timer-phase-short]");
  const subtitleEls = document.querySelectorAll("[data-timer-subtitle]");
  const statusEls = document.querySelectorAll("[data-timer-status]");
  const cycleCountEls = document.querySelectorAll("[data-timer-cycle-count]");
  const nextPhaseEls = document.querySelectorAll("[data-timer-next-phase]");
  const progressBarEls = document.querySelectorAll("[data-timer-progress-bar]");
  const startPauseButtons = document.querySelectorAll("[data-timer-start-pause]");
  const resetButtons = document.querySelectorAll("[data-timer-reset]");
  const skipButtons = document.querySelectorAll("[data-timer-skip]");
  const applySettingsButtons = document.querySelectorAll("[data-timer-apply-settings]");
  const focusInputs = document.querySelectorAll("[data-timer-focus-input]");
  const breakInputs = document.querySelectorAll("[data-timer-break-input]");
  const presetButtons = document.querySelectorAll("[data-timer-preset-focus]");
  const ambientModeSelects = document.querySelectorAll("[data-ambient-mode]");
  const ambientToggleButtons = document.querySelectorAll("[data-ambient-toggle]");
  const ambientVolumeInputs = document.querySelectorAll("[data-ambient-volume]");
  const ambientVolumeValueEls = document.querySelectorAll("[data-ambient-volume-value]");
  const ambientStatusEls = document.querySelectorAll("[data-ambient-status]");

  let intervalId = null;
  let state = loadState();
  let ambientAudioContext = null;
  let ambientMasterGain = null;
  let ambientIsPlaying = false;
  let ambientNeedsGesture = false;
  let ambientSources = [];
  let ambientNodes = [];
  let ambientCleanupFns = [];
  const noiseBufferCache = new Map();

  function buildFreshState(focusMinutes, breakMinutes) {
    return {
      phase: "focus",
      focusMinutes,
      breakMinutes,
      remainingSeconds: focusMinutes * 60,
      completedFocusSessions: 0,
      isRunning: false,
      lastTickAt: 0,
      ambientMode: "none",
      ambientVolume: 0.35,
      ambientShouldPlay: false,
    };
  }

  function coerceMinutes(value, fallback, max) {
    const parsed = Number.parseInt(value, 10);
    if (Number.isNaN(parsed) || parsed < 1) {
      return fallback;
    }
    return Math.min(parsed, max);
  }

  function clampSeconds(value, totalSeconds) {
    const parsed = Number.parseInt(value, 10);
    if (Number.isNaN(parsed)) {
      return totalSeconds;
    }
    return Math.min(Math.max(parsed, 0), totalSeconds);
  }

  function coerceAmbientMode(value) {
    return Object.prototype.hasOwnProperty.call(ambientModes, value) ? value : "none";
  }

  function coerceAmbientVolume(value, fallback = 0.35) {
    const parsed = Number.parseFloat(value);
    if (Number.isNaN(parsed)) {
      return fallback;
    }
    return Math.min(Math.max(parsed, 0), 1);
  }

  function getPhaseSeconds(phase, focusMinutes = state.focusMinutes, breakMinutes = state.breakMinutes) {
    return (phase === "focus" ? focusMinutes : breakMinutes) * 60;
  }

  function loadState() {
    const fallback = buildFreshState(defaultFocusMinutes, defaultBreakMinutes);

    try {
      const rawState = window.localStorage.getItem(storageKey);
      if (!rawState) {
        return fallback;
      }

      const parsed = JSON.parse(rawState);
      if (!parsed || typeof parsed !== "object") {
        return fallback;
      }

      const focusMinutes = coerceMinutes(parsed.focusMinutes, defaultFocusMinutes, 300);
      const breakMinutes = coerceMinutes(parsed.breakMinutes, defaultBreakMinutes, 120);
      const phase = parsed.phase === "break" ? "break" : "focus";
      const totalSeconds = getPhaseSeconds(phase, focusMinutes, breakMinutes);
      const remainingSeconds = clampSeconds(parsed.remainingSeconds, totalSeconds);
      const completedFocusSessions = Math.max(0, Number.parseInt(parsed.completedFocusSessions || "0", 10) || 0);
      const isRunning = parsed.isRunning === true;
      const lastTickAt = Number.parseInt(parsed.lastTickAt || "0", 10) || 0;
      const ambientMode = coerceAmbientMode(parsed.ambientMode);
      const ambientVolume = coerceAmbientVolume(parsed.ambientVolume, fallback.ambientVolume);
      const ambientShouldPlay = parsed.ambientShouldPlay === true && ambientMode !== "none";

      return {
        phase,
        focusMinutes,
        breakMinutes,
        remainingSeconds,
        completedFocusSessions,
        isRunning,
        lastTickAt,
        ambientMode,
        ambientVolume,
        ambientShouldPlay,
      };
    } catch (error) {
      return fallback;
    }
  }

  function saveState() {
    try {
      window.localStorage.setItem(storageKey, JSON.stringify(state));
    } catch (error) {
      // Ignore storage failures and keep the timer usable for the current session.
    }
  }

  function formatTime(totalSeconds) {
    const safeSeconds = Math.max(0, totalSeconds);
    const minutes = Math.floor(safeSeconds / 60);
    const seconds = safeSeconds % 60;
    return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }

  function getPhaseLabel(phase) {
    return phase === "focus" ? "집중 시간" : "휴식 시간";
  }

  function getPhaseShortLabel(phase) {
    return phase === "focus" ? "집중" : "휴식";
  }

  function getNextPhaseLabel(phase) {
    return phase === "focus" ? `${state.breakMinutes}분 휴식` : `${state.focusMinutes}분 집중`;
  }

  function getAmbientLabel(mode) {
    return ambientModes[mode] || ambientModes.none;
  }

  function getStatusLabel() {
    if (state.isRunning) {
      return state.phase === "focus" ? "집중 중" : "휴식 중";
    }
    return state.remainingSeconds === getPhaseSeconds(state.phase) ? "대기 중" : "일시정지";
  }

  function getAmbientStatusLabel() {
    if (!ambientAudioSupported) {
      return "이 브라우저에서는 지원되지 않음";
    }
    if (state.ambientMode === "none") {
      return "꺼짐";
    }
    if (ambientIsPlaying) {
      return `${getAmbientLabel(state.ambientMode)} 재생 중`;
    }
    if (ambientNeedsGesture || state.ambientShouldPlay) {
      return `${getAmbientLabel(state.ambientMode)} 다시 재생`;
    }
    return `${getAmbientLabel(state.ambientMode)} 준비됨`;
  }

  function getSubtitle() {
    if (state.isRunning) {
      return state.phase === "focus"
        ? "지금은 공부에만 집중하면 됩니다. 시간이 끝나면 자동으로 휴식으로 넘어갑니다."
        : "잠깐 쉬는 시간입니다. 끝나면 다음 집중 세션이 자동으로 시작됩니다.";
    }

    if (state.remainingSeconds === getPhaseSeconds(state.phase)) {
      return state.phase === "focus"
        ? "준비되면 시작 버튼을 눌러 첫 집중 세션을 시작하세요."
        : "휴식 타이머가 준비되었습니다. 시작하면 카운트다운이 이어집니다.";
    }

    return "잠시 멈춘 상태입니다. 다시 시작하면 이어서 진행됩니다.";
  }

  function updateDocumentTitle() {
    document.title = `${formatTime(state.remainingSeconds)} · ${getPhaseLabel(state.phase)} | 수정 예시 문제집`;
  }

  function render() {
    const totalPhaseSeconds = getPhaseSeconds(state.phase);
    const progressRatio = totalPhaseSeconds === 0 ? 0 : state.remainingSeconds / totalPhaseSeconds;
    const clampedProgress = Math.max(0, Math.min(1, progressRatio));
    const timerLabel = state.isRunning ? "일시정지" : "시작";
    const ambientLabel = ambientIsPlaying ? "정지" : "재생";
    const ambientVolumePercent = `${Math.round(state.ambientVolume * 100)}%`;
    const ambientToggleDisabled = !ambientAudioSupported || state.ambientMode === "none";

    for (const element of displayEls) {
      element.textContent = formatTime(state.remainingSeconds);
    }
    for (const element of phaseEls) {
      element.textContent = getPhaseLabel(state.phase);
    }
    for (const element of phaseShortEls) {
      element.textContent = getPhaseShortLabel(state.phase);
    }
    for (const element of subtitleEls) {
      element.textContent = getSubtitle();
    }
    for (const element of statusEls) {
      element.textContent = getStatusLabel();
    }
    for (const element of cycleCountEls) {
      element.textContent = `${state.completedFocusSessions}회`;
    }
    for (const element of nextPhaseEls) {
      element.textContent = getNextPhaseLabel(state.phase);
    }
    for (const element of progressBarEls) {
      element.style.transform = `scaleX(${clampedProgress})`;
    }
    for (const button of startPauseButtons) {
      button.textContent = timerLabel;
    }
    for (const input of focusInputs) {
      input.value = String(state.focusMinutes);
    }
    for (const input of breakInputs) {
      input.value = String(state.breakMinutes);
    }
    for (const select of ambientModeSelects) {
      select.value = state.ambientMode;
    }
    for (const input of ambientVolumeInputs) {
      input.value = String(Math.round(state.ambientVolume * 100));
    }
    for (const element of ambientVolumeValueEls) {
      element.textContent = ambientVolumePercent;
    }
    for (const element of ambientStatusEls) {
      element.textContent = getAmbientStatusLabel();
    }
    for (const button of ambientToggleButtons) {
      button.textContent = ambientLabel;
      button.disabled = ambientToggleDisabled;
    }
    updateDocumentTitle();
  }

  function clearTimerInterval() {
    if (intervalId !== null) {
      window.clearInterval(intervalId);
      intervalId = null;
    }
  }

  function startTimerInterval() {
    clearTimerInterval();
    intervalId = window.setInterval(tick, 1000);
  }

  function removeTrackedNode(collection, node) {
    const index = collection.indexOf(node);
    if (index >= 0) {
      collection.splice(index, 1);
    }
  }

  function registerAmbientSource(node) {
    ambientSources.push(node);
    return node;
  }

  function registerAmbientNode(node) {
    ambientNodes.push(node);
    return node;
  }

  function disconnectNode(node) {
    try {
      node.disconnect();
    } catch (error) {
      // Nodes can already be disconnected when we rebuild the ambience chain.
    }
  }

  function cleanupTransientAmbientNodes(source, nodes) {
    source.addEventListener(
      "ended",
      () => {
        disconnectNode(source);
        removeTrackedNode(ambientSources, source);
        for (const node of nodes) {
          disconnectNode(node);
          removeTrackedNode(ambientNodes, node);
        }
      },
      { once: true }
    );
  }

  function getNoiseBuffer(color) {
    if (!ambientAudioContext) {
      return null;
    }

    const cacheKey = `${color}:${ambientAudioContext.sampleRate}`;
    const cachedBuffer = noiseBufferCache.get(cacheKey);
    if (cachedBuffer) {
      return cachedBuffer;
    }

    const durationSeconds = 2.5;
    const frameCount = Math.floor(ambientAudioContext.sampleRate * durationSeconds);
    const buffer = ambientAudioContext.createBuffer(2, frameCount, ambientAudioContext.sampleRate);

    for (let channel = 0; channel < buffer.numberOfChannels; channel += 1) {
      const data = buffer.getChannelData(channel);
      let lastBrown = 0;
      let b0 = 0;
      let b1 = 0;
      let b2 = 0;
      let b3 = 0;
      let b4 = 0;
      let b5 = 0;
      let b6 = 0;

      for (let index = 0; index < frameCount; index += 1) {
        const white = Math.random() * 2 - 1;

        if (color === "brown") {
          lastBrown = (lastBrown + 0.02 * white) / 1.02;
          data[index] = lastBrown * 3.5;
          continue;
        }

        if (color === "pink") {
          b0 = 0.99886 * b0 + white * 0.0555179;
          b1 = 0.99332 * b1 + white * 0.0750759;
          b2 = 0.969 * b2 + white * 0.153852;
          b3 = 0.8665 * b3 + white * 0.3104856;
          b4 = 0.55 * b4 + white * 0.5329522;
          b5 = -0.7616 * b5 - white * 0.016898;
          data[index] = (b0 + b1 + b2 + b3 + b4 + b5 + b6 + white * 0.5362) * 0.11;
          b6 = white * 0.115926;
          continue;
        }

        data[index] = white * 0.3;
      }
    }

    noiseBufferCache.set(cacheKey, buffer);
    return buffer;
  }

  async function ensureAmbientAudioContext() {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) {
      return null;
    }

    if (!ambientAudioContext || ambientAudioContext.state === "closed") {
      ambientAudioContext = new AudioContextClass();
      ambientMasterGain = registerAmbientNode(ambientAudioContext.createGain());
      ambientMasterGain.connect(ambientAudioContext.destination);
    }

    if (ambientAudioContext.state === "suspended") {
      await ambientAudioContext.resume();
    }

    ambientMasterGain.gain.setTargetAtTime(state.ambientVolume, ambientAudioContext.currentTime, 0.05);
    return ambientAudioContext;
  }

  function stopAmbientSound(options = {}) {
    const { shouldRender = true } = options;

    for (const cleanup of ambientCleanupFns.splice(0)) {
      cleanup();
    }
    for (const source of ambientSources.splice(0)) {
      try {
        source.stop();
      } catch (error) {
        // Buffer/oscillator nodes can already be stopped when changing sound presets.
      }
      disconnectNode(source);
    }
    for (const node of ambientNodes.splice(0)) {
      if (node !== ambientMasterGain) {
        disconnectNode(node);
      }
    }

    if (ambientMasterGain) {
      ambientNodes = [ambientMasterGain];
    }

    ambientIsPlaying = false;
    ambientNeedsGesture = false;

    if (shouldRender) {
      render();
    }
  }

  function createLoopingNoise(color, destination, options = {}) {
    const { gain = 0.15, highpass = null, lowpass = null } = options;
    const source = registerAmbientSource(ambientAudioContext.createBufferSource());
    source.buffer = getNoiseBuffer(color);
    source.loop = true;

    let currentNode = source;

    if (highpass !== null) {
      const highpassFilter = registerAmbientNode(ambientAudioContext.createBiquadFilter());
      highpassFilter.type = "highpass";
      highpassFilter.frequency.value = highpass;
      currentNode.connect(highpassFilter);
      currentNode = highpassFilter;
    }

    if (lowpass !== null) {
      const lowpassFilter = registerAmbientNode(ambientAudioContext.createBiquadFilter());
      lowpassFilter.type = "lowpass";
      lowpassFilter.frequency.value = lowpass;
      currentNode.connect(lowpassFilter);
      currentNode = lowpassFilter;
    }

    const gainNode = registerAmbientNode(ambientAudioContext.createGain());
    gainNode.gain.value = gain;
    currentNode.connect(gainNode);
    gainNode.connect(destination);
    source.start();
  }

  function spawnNoiseBurst(color, destination, options = {}) {
    const {
      when = ambientAudioContext.currentTime,
      duration = 0.22,
      offset = Math.random() * 0.8,
      filterType = "bandpass",
      frequency = 1800,
      q = 0.8,
      peakGain = 0.02,
    } = options;

    const source = registerAmbientSource(ambientAudioContext.createBufferSource());
    source.buffer = getNoiseBuffer(color);

    const filter = registerAmbientNode(ambientAudioContext.createBiquadFilter());
    filter.type = filterType;
    filter.frequency.value = frequency;
    filter.Q.value = q;

    const gainNode = registerAmbientNode(ambientAudioContext.createGain());
    gainNode.gain.setValueAtTime(0.0001, when);
    gainNode.gain.exponentialRampToValueAtTime(peakGain, when + 0.02);
    gainNode.gain.exponentialRampToValueAtTime(0.0001, when + duration);

    source.connect(filter);
    filter.connect(gainNode);
    gainNode.connect(destination);

    source.start(when, offset, duration);
    source.stop(when + duration + 0.02);
    cleanupTransientAmbientNodes(source, [filter, gainNode]);
  }

  function spawnToneSweep(destination, options = {}) {
    const {
      when = ambientAudioContext.currentTime,
      duration = 0.18,
      type = "sine",
      startFrequency = 1800,
      endFrequency = 2400,
      peakGain = 0.01,
    } = options;

    const oscillator = registerAmbientSource(ambientAudioContext.createOscillator());
    oscillator.type = type;
    oscillator.frequency.setValueAtTime(startFrequency, when);
    oscillator.frequency.exponentialRampToValueAtTime(endFrequency, when + duration);

    const gainNode = registerAmbientNode(ambientAudioContext.createGain());
    gainNode.gain.setValueAtTime(0.0001, when);
    gainNode.gain.exponentialRampToValueAtTime(peakGain, when + 0.02);
    gainNode.gain.exponentialRampToValueAtTime(0.0001, when + duration);

    oscillator.connect(gainNode);
    gainNode.connect(destination);
    oscillator.start(when);
    oscillator.stop(when + duration + 0.02);
    cleanupTransientAmbientNodes(oscillator, [gainNode]);
  }

  function scheduleAmbientTask(callback, getDelayMs) {
    let timeoutId = null;
    let cancelled = false;

    function run() {
      if (cancelled || !ambientIsPlaying) {
        return;
      }

      callback();
      timeoutId = window.setTimeout(run, getDelayMs());
    }

    timeoutId = window.setTimeout(run, getDelayMs());
    ambientCleanupFns.push(() => {
      cancelled = true;
      if (timeoutId !== null) {
        window.clearTimeout(timeoutId);
      }
    });
  }

  function buildRainAmbience(destination) {
    createLoopingNoise("pink", destination, { gain: 0.18, highpass: 140, lowpass: 3200 });
    createLoopingNoise("white", destination, { gain: 0.06, highpass: 2600, lowpass: 9000 });
    createLoopingNoise("brown", destination, { gain: 0.035, lowpass: 650 });

    const raindropIntervalId = window.setInterval(() => {
      if (!ambientIsPlaying) {
        return;
      }
      if (Math.random() < 0.55) {
        spawnNoiseBurst("white", destination, {
          duration: 0.08 + Math.random() * 0.06,
          frequency: 3200 + Math.random() * 1800,
          q: 1.2,
          peakGain: 0.004 + Math.random() * 0.004,
        });
      }
    }, 650);
    ambientCleanupFns.push(() => window.clearInterval(raindropIntervalId));
  }

  function buildLibraryAmbience(destination) {
    createLoopingNoise("pink", destination, { gain: 0.08, highpass: 220, lowpass: 2200 });
    createLoopingNoise("brown", destination, { gain: 0.03, lowpass: 540 });

    const humOscillator = registerAmbientSource(ambientAudioContext.createOscillator());
    humOscillator.type = "triangle";
    humOscillator.frequency.value = 92;
    const humGain = registerAmbientNode(ambientAudioContext.createGain());
    humGain.gain.value = 0.005;
    humOscillator.connect(humGain);
    humGain.connect(destination);
    humOscillator.start();

    const rustleIntervalId = window.setInterval(() => {
      if (!ambientIsPlaying) {
        return;
      }

      const burstCount = 1 + Math.floor(Math.random() * 2);
      const startAt = ambientAudioContext.currentTime;
      for (let burstIndex = 0; burstIndex < burstCount; burstIndex += 1) {
        spawnNoiseBurst("white", destination, {
          when: startAt + burstIndex * (0.06 + Math.random() * 0.08),
          duration: 0.16 + Math.random() * 0.12,
          frequency: 1200 + Math.random() * 1100,
          q: 0.7,
          peakGain: 0.006 + Math.random() * 0.005,
        });
      }
    }, 4200);
    ambientCleanupFns.push(() => window.clearInterval(rustleIntervalId));
  }

  function buildForestAmbience(destination) {
    createLoopingNoise("pink", destination, { gain: 0.06, highpass: 250, lowpass: 4200 });
    createLoopingNoise("brown", destination, { gain: 0.02, lowpass: 900 });
    createLoopingNoise("white", destination, { gain: 0.015, highpass: 3200, lowpass: 9200 });

    scheduleAmbientTask(
      () => {
        const startAt = ambientAudioContext.currentTime;
        const chirpCount = 1 + Math.floor(Math.random() * 3);
        for (let chirpIndex = 0; chirpIndex < chirpCount; chirpIndex += 1) {
          spawnToneSweep(destination, {
            when: startAt + chirpIndex * (0.08 + Math.random() * 0.08),
            duration: 0.08 + Math.random() * 0.1,
            type: Math.random() < 0.5 ? "sine" : "triangle",
            startFrequency: 1500 + Math.random() * 1200,
            endFrequency: 2400 + Math.random() * 1800,
            peakGain: 0.002 + Math.random() * 0.003,
          });
        }
      },
      () => 3000 + Math.random() * 5000
    );
  }

  function buildStreamAmbience(destination) {
    createLoopingNoise("white", destination, { gain: 0.08, highpass: 500, lowpass: 6200 });
    createLoopingNoise("pink", destination, { gain: 0.06, highpass: 180, lowpass: 2600 });
    createLoopingNoise("brown", destination, { gain: 0.02, lowpass: 700 });

    scheduleAmbientTask(
      () => {
        const burstCount = 2 + Math.floor(Math.random() * 3);
        const startAt = ambientAudioContext.currentTime;
        for (let burstIndex = 0; burstIndex < burstCount; burstIndex += 1) {
          spawnNoiseBurst("white", destination, {
            when: startAt + burstIndex * (0.05 + Math.random() * 0.06),
            duration: 0.1 + Math.random() * 0.08,
            frequency: 1800 + Math.random() * 1200,
            q: 1.0,
            peakGain: 0.003 + Math.random() * 0.003,
          });
        }
      },
      () => 900 + Math.random() * 1400
    );
  }

  function buildWavesAmbience(destination) {
    createLoopingNoise("brown", destination, { gain: 0.09, lowpass: 850 });
    createLoopingNoise("pink", destination, { gain: 0.05, highpass: 140, lowpass: 2200 });
    createLoopingNoise("white", destination, { gain: 0.02, highpass: 2100, lowpass: 7600 });

    scheduleAmbientTask(
      () => {
        const startAt = ambientAudioContext.currentTime;
        const burstCount = 3;
        for (let burstIndex = 0; burstIndex < burstCount; burstIndex += 1) {
          spawnNoiseBurst("white", destination, {
            when: startAt + burstIndex * 0.42,
            duration: 1.4 + Math.random() * 0.7,
            frequency: 1300 + Math.random() * 900,
            q: 0.35,
            peakGain: 0.0016 + Math.random() * 0.0014,
          });
          spawnNoiseBurst("pink", destination, {
            when: startAt + burstIndex * 0.42 + 0.08,
            duration: 1.7 + Math.random() * 0.8,
            filterType: "lowpass",
            frequency: 950 + Math.random() * 260,
            q: 0.3,
            peakGain: 0.002 + Math.random() * 0.0012,
          });
        }
      },
      () => 3800 + Math.random() * 2400
    );
  }

  function buildAmbientSound(mode, destination) {
    switch (mode) {
      case "rain":
        buildRainAmbience(destination);
        break;
      case "library":
        buildLibraryAmbience(destination);
        break;
      case "forest":
        buildForestAmbience(destination);
        break;
      case "stream":
        buildStreamAmbience(destination);
        break;
      case "waves":
        buildWavesAmbience(destination);
        break;
      case "brown":
        createLoopingNoise("brown", destination, { gain: 0.18, lowpass: 1400 });
        createLoopingNoise("pink", destination, { gain: 0.03, highpass: 250, lowpass: 2200 });
        break;
      case "white":
        createLoopingNoise("white", destination, { gain: 0.15, highpass: 120, lowpass: 9800 });
        break;
      default:
        break;
    }
  }

  async function startAmbientSound() {
    if (state.ambientMode === "none") {
      state.ambientShouldPlay = false;
      render();
      return;
    }

    try {
      const audioContext = await ensureAmbientAudioContext();
      if (!audioContext || !ambientMasterGain) {
        render();
        return;
      }

      stopAmbientSound({ shouldRender: false });
      ambientMasterGain.gain.setTargetAtTime(state.ambientVolume, audioContext.currentTime, 0.05);
      buildAmbientSound(state.ambientMode, ambientMasterGain);
      ambientIsPlaying = true;
      ambientNeedsGesture = false;
      state.ambientShouldPlay = true;
      saveState();
      render();
    } catch (error) {
      ambientIsPlaying = false;
      ambientNeedsGesture = true;
      render();
    }
  }

  function beep() {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) {
      return;
    }

    const audioContext = new AudioContextClass();
    const oscillator = audioContext.createOscillator();
    const gainNode = audioContext.createGain();

    oscillator.type = "sine";
    oscillator.frequency.setValueAtTime(880, audioContext.currentTime);
    gainNode.gain.setValueAtTime(0.001, audioContext.currentTime);
    gainNode.gain.exponentialRampToValueAtTime(0.08, audioContext.currentTime + 0.01);
    gainNode.gain.exponentialRampToValueAtTime(0.001, audioContext.currentTime + 0.22);

    oscillator.connect(gainNode);
    gainNode.connect(audioContext.destination);
    oscillator.start();
    oscillator.stop(audioContext.currentTime + 0.24);
    oscillator.addEventListener("ended", () => {
      audioContext.close().catch(() => {});
    });
  }

  function notifyPhaseChange(nextPhase) {
    const message =
      nextPhase === "focus"
        ? "휴식이 끝났어요. 다시 집중할 시간입니다."
        : `집중 세션이 끝났어요. ${state.breakMinutes}분 쉬어가세요.`;
    beep();
    window.setTimeout(() => beep(), 180);

    if (typeof window.Notification !== "undefined" && window.Notification.permission === "granted") {
      new window.Notification("집중 타이머", { body: message });
    }
  }

  function transitionPhase(options = {}) {
    const { countFocusCompletion = true } = options;
    const nextPhase = state.phase === "focus" ? "break" : "focus";

    if (state.phase === "focus" && countFocusCompletion) {
      state.completedFocusSessions += 1;
    }

    state.phase = nextPhase;
    state.remainingSeconds = getPhaseSeconds(nextPhase);
    state.lastTickAt = Date.now();
    notifyPhaseChange(nextPhase);
    saveState();
    render();
  }

  function tick() {
    const now = Date.now();
    const lastTickAt = state.lastTickAt || now;
    const elapsedSeconds = Math.max(1, Math.floor((now - lastTickAt) / 1000));

    state.lastTickAt = now;
    state.remainingSeconds = Math.max(0, state.remainingSeconds - elapsedSeconds);

    if (state.remainingSeconds === 0) {
      transitionPhase();
      return;
    }

    saveState();
    render();
  }

  function advanceStateByElapsed(elapsedSeconds) {
    let remainingElapsed = Math.max(0, elapsedSeconds);

    while (remainingElapsed > 0) {
      if (remainingElapsed < state.remainingSeconds) {
        state.remainingSeconds -= remainingElapsed;
        remainingElapsed = 0;
        continue;
      }

      remainingElapsed -= state.remainingSeconds;
      if (state.phase === "focus") {
        state.completedFocusSessions += 1;
      }
      state.phase = state.phase === "focus" ? "break" : "focus";
      state.remainingSeconds = getPhaseSeconds(state.phase);
    }
  }

  function requestNotificationsIfNeeded() {
    if (typeof window.Notification === "undefined") {
      return;
    }

    if (window.Notification.permission === "default") {
      window.Notification.requestPermission().catch(() => {});
    }
  }

  function startPauseTimer() {
    if (state.isRunning) {
      state.isRunning = false;
      clearTimerInterval();
    } else {
      state.isRunning = true;
      state.lastTickAt = Date.now();
      startTimerInterval();
      requestNotificationsIfNeeded();
    }

    saveState();
    render();
  }

  function resetTimer() {
    state = buildFreshState(state.focusMinutes, state.breakMinutes);
    clearTimerInterval();
    saveState();
    render();
  }

  function skipPhase() {
    const wasRunning = state.isRunning;
    transitionPhase({ countFocusCompletion: false });

    if (!wasRunning) {
      state.isRunning = false;
      clearTimerInterval();
      saveState();
      render();
    }
  }

  function applySettings(focusMinutes, breakMinutes) {
    state.focusMinutes = coerceMinutes(focusMinutes, defaultFocusMinutes, 300);
    state.breakMinutes = coerceMinutes(breakMinutes, defaultBreakMinutes, 120);
    state.phase = "focus";
    state.remainingSeconds = getPhaseSeconds("focus");
    state.completedFocusSessions = 0;
    state.isRunning = false;
    state.lastTickAt = 0;
    clearTimerInterval();
    saveState();
    render();
  }

  function updateAmbientMode(nextMode) {
    state.ambientMode = coerceAmbientMode(nextMode);
    state.ambientShouldPlay = state.ambientMode !== "none";
    saveState();

    if (state.ambientMode === "none") {
      stopAmbientSound();
      return;
    }

    void startAmbientSound();
  }

  function updateAmbientVolume(nextVolume) {
    state.ambientVolume = coerceAmbientVolume(Number.parseFloat(nextVolume) / 100, state.ambientVolume);
    saveState();

    if (ambientAudioContext && ambientMasterGain) {
      ambientMasterGain.gain.setTargetAtTime(state.ambientVolume, ambientAudioContext.currentTime, 0.05);
    }

    render();
  }

  function toggleAmbientSound() {
    if (ambientIsPlaying) {
      state.ambientShouldPlay = false;
      saveState();
      stopAmbientSound();
      return;
    }
    state.ambientShouldPlay = true;
    saveState();
    void startAmbientSound();
  }

  function hydrateRunningState() {
    if (state.ambientShouldPlay && state.ambientMode !== "none") {
      ambientNeedsGesture = true;
      void startAmbientSound();
    }

    if (!state.isRunning) {
      render();
      return;
    }

    const now = Date.now();
    const elapsedSeconds = Math.max(0, Math.floor((now - state.lastTickAt) / 1000));
    if (elapsedSeconds > 0) {
      advanceStateByElapsed(elapsedSeconds);
      state.lastTickAt = now;
      saveState();
    }

    startTimerInterval();
    render();
  }

  for (const button of startPauseButtons) {
    button.addEventListener("click", startPauseTimer);
  }
  for (const button of resetButtons) {
    button.addEventListener("click", resetTimer);
  }
  for (const button of skipButtons) {
    button.addEventListener("click", skipPhase);
  }
  for (const button of applySettingsButtons) {
    button.addEventListener("click", () => {
      const focusValue = focusInputs[0]?.value ?? state.focusMinutes;
      const breakValue = breakInputs[0]?.value ?? state.breakMinutes;
      applySettings(focusValue, breakValue);
    });
  }
  for (const button of presetButtons) {
    button.addEventListener("click", () => {
      applySettings(button.dataset.timerPresetFocus, button.dataset.timerPresetBreak);
    });
  }
  for (const select of ambientModeSelects) {
    select.addEventListener("change", () => {
      updateAmbientMode(select.value);
    });
  }
  for (const input of ambientVolumeInputs) {
    input.addEventListener("input", () => {
      updateAmbientVolume(input.value);
    });
  }
  for (const button of ambientToggleButtons) {
    button.addEventListener("click", toggleAmbientSound);
  }

  window.addEventListener("beforeunload", () => {
    saveState();
    stopAmbientSound({ shouldRender: false });
  });
  hydrateRunningState();
}
