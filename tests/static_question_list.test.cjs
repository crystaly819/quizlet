const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

class Element {
  constructor() {
    this.children = [];
    this.dataset = {};
    this.listeners = {};
    this.attributes = {};
    this.textContent = '';
    this.value = '';
    const classes = new Set();
    this.classList = {
      add: (...names) => names.forEach((name) => classes.add(name)),
      remove: (...names) => names.forEach((name) => classes.delete(name)),
      contains: (name) => classes.has(name),
      toggle(name, enabled = !classes.has(name)) {
        enabled ? classes.add(name) : classes.delete(name);
      },
    };
  }
  set innerHTML(value) { this.children = []; this.html = value; }
  get innerHTML() { return this.html || ''; }
  appendChild(child) { this.children.push(child); return child; }
  addEventListener(event, callback) { this.listeners[event] = callback; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] || null; }
  removeAttribute(name) { delete this.attributes[name]; }
  querySelectorAll() { return this.children; }
  focus() {}
}

const questions = [1, 2, 3].map((number) => ({
  key: `q${number}`, number, page_number: number + 2,
  stem: `${number === 2 ? '완충' : '농도'} 개념 ${number}`,
  question_kind: 'multiple_choice',
  choices: [{ index: 1, text: '보기 A' }, { index: 2, text: '보기 B' }],
  correct_index: 1, correct_text: '비밀 정답', explanation_text: '비밀 해설',
}));
const deck = { slug: 'chemistry', title: '분석학', approved_count: 3, questions };
const progress = {
  q1: { seen: true, wrong: false, attempts: 1 },
  q2: { seen: true, wrong: true, attempts: 1 },
};

async function openPage(script, query, records = progress, decks = [deck]) {
  const elements = new Map();
  const get = (selector) => {
    if (!elements.has(selector)) elements.set(selector, new Element());
    return elements.get(selector);
  };
  const listModes = ['all', 'unseen', 'wrong'].map((mode) => {
    const el = new Element(); el.dataset.listMode = mode; return el;
  });
  const studyModes = ['all', 'unseen', 'wrong'].map((mode) => {
    const el = new Element(); el.dataset.modeLink = mode; return el;
  });
  const storage = new Map([['quizlet-gh-progress-v1', JSON.stringify(records)]]);
  const window = {
    location: { href: `https://example.test/quizlet/study.html${query}`, search: query },
    localStorage: { getItem: (key) => storage.get(key), setItem: (key, value) => storage.set(key, value) },
    history: { replaceState: (_state, _title, url) => { window.lastUrl = url; } },
    setTimeout: (callback) => callback(),
    addEventListener: () => {},
  };
  const document = {
    querySelector: get, getElementById: (id) => get(`#${id}`),
    createElement: () => new Element(),
    querySelectorAll: (selector) => selector === '[data-list-mode]' ? listModes : studyModes,
  };
  const context = vm.createContext({ window, document, URL, URLSearchParams, fetch: async () => ({ ok: true, json: async () => ({ decks: structuredClone(decks) }) }) });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'docs', 'assets', script), 'utf8'), context);
  await new Promise((resolve) => setImmediate(resolve));
  return { get, storage, window, listModes, studyModes };
}

function textOf(el) {
  return el.textContent + el.children.map(textOf).join(' ');
}

test('question list shows numbered questions, statuses and direct links without revealing answers', async () => {
  const page = await openPage('pages-questions.js', '?deck=chemistry&mode=all');
  const rows = page.get('[data-question-list]').children;
  assert.equal(rows.length, 3);
  assert.match(textOf(rows[0]), /1번/);
  assert.match(textOf(rows[0]), /풀이 완료/);
  assert.match(textOf(rows[1]), /오답/);
  assert.match(textOf(rows[2]), /미풀이/);
  assert.match(rows[1].href, /question=q2/);
  assert.match(rows[1].href, /order=list/);
  assert.doesNotMatch(rows.map(textOf).join(' '), /비밀 정답|비밀 해설/);
  assert.deepEqual(JSON.parse(page.storage.get('quizlet-gh-progress-v1')), progress);
});

test('unseen and wrong lists use existing saved progress and preserve the selected mode', async () => {
  for (const [mode, key] of [['unseen', 'q3'], ['wrong', 'q2']]) {
    const page = await openPage('pages-questions.js', `?deck=chemistry&mode=${mode}`);
    const rows = page.get('[data-question-list]').children;
    assert.equal(rows.length, 1);
    assert.match(rows[0].href, new RegExp(`question=${key}`));
    assert.match(rows[0].href, new RegExp(`mode=${mode}`));
  }
});

test('search narrows the list by question text or number', async () => {
  const page = await openPage('pages-questions.js', '?deck=chemistry');
  const search = page.get('[data-question-search]');
  search.value = '완충'; search.listeners.input();
  assert.equal(page.get('[data-question-list]').children.length, 1);
  search.value = '3'; search.listeners.input();
  assert.equal(page.get('[data-question-list]').children.length, 1);
  assert.match(page.get('[data-question-list]').children[0].href, /question=q3/);
  search.value = '없음'; search.listeners.input();
  assert.equal(page.get('[data-question-list]').children.length, 0);
  assert.equal(page.get('[data-list-empty]').classList.contains('hidden'), false);
});

test('empty lists and missing decks show a helpful state', async () => {
  const page = await openPage('pages-questions.js', '?deck=chemistry&mode=wrong', {});
  assert.equal(page.get('[data-question-list]').children.length, 0);
  assert.match(page.get('[data-list-empty]').textContent, /오답/);
  const missing = await openPage('pages-questions.js', '?deck=missing');
  assert.match(missing.get('[data-list-title]').textContent, /찾을 수 없/);
});

test('a selected question opens directly without marking it seen; answering updates the existing storage', async () => {
  const page = await openPage('pages-study.js', '?deck=chemistry&mode=all&question=q2&order=list');
  assert.equal(page.get('#question-stem').textContent, questions[1].stem);
  assert.deepEqual(JSON.parse(page.storage.get('quizlet-gh-progress-v1')), progress);
  assert.match(page.get('[data-question-list-link]').href, /questions.html\?deck=chemistry&mode=all/);
  page.get('#choice-list').children[0].listeners.click();
  assert.equal(JSON.parse(page.storage.get('quizlet-gh-progress-v1')).q2.attempts, 2);
  page.get('#next-button').listeners.click();
  assert.equal(page.get('#question-stem').textContent, questions[2].stem);
});

test('unseen selection advances to the next remaining question after submission', async () => {
  const page = await openPage('pages-study.js', '?deck=chemistry&mode=unseen&question=q2&order=list', {});
  assert.equal(page.get('#question-stem').textContent, questions[1].stem);
  page.get('#choice-list').children[0].listeners.click();
  page.get('#next-button').listeners.click();
  assert.equal(page.get('#question-stem').textContent, questions[2].stem);
});

test('stale or foreign question keys do not silently open a random question', async () => {
  const page = await openPage('pages-study.js', '?deck=chemistry&question=foreign&order=list');
  assert.match(page.get('#empty-state').textContent, /선택한 문항/);
  const stale = await openPage('pages-study.js', '?deck=chemistry&mode=unseen&question=q1&order=list');
  assert.match(stale.get('#empty-state').textContent, /선택한 문항/);
});
