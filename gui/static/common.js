// Shared by every page: settings storage, theme, DOM helpers.
// All text is inserted with textContent (never innerHTML), so tag names and
// comments from L5X files cannot inject markup.
'use strict';

const $ = (id) => document.getElementById(id);

const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage unavailable */ } },
};

const SETTINGS_KEY = 'llm4l5x.settings';
const DEFAULTS = {
    output: 'routine', routine: 'GeneratedRoutine', program: 'MainProgram', controller: 'LLM4L5X',
    revision: '32.04', scope: 'controller', display: 'placeholder', prefix: 'L4X', comments: true,
    backend: 'ollama', llm_url: '', model: 'phi4-mini', think: 'default',
    rung_format: 'neutral', disabled_rules: [],
};
const BACKEND_INFO = {
    ollama: { url: 'http://127.0.0.1:11434', label: 'Ollama',
        help: 'Models installed with "ollama pull <name>". No grammar: a malformed answer is sent back to the model to fix.' },
    llamacpp: { url: 'http://127.0.0.1:8080', label: 'llama.cpp',
        help: 'Start it with: llama-server -m model.gguf --port 8080 --jinja. Every answer is constrained to valid logic with your tag names, and thinking is always off. The server runs the model it was started with.' },
    openai: { url: 'http://127.0.0.1:1234', label: 'OpenAI-compatible',
        help: 'Any local server with the OpenAI chat API (LM Studio, Jan, vLLM). No grammar.' },
};

function loadSettings() {
    const s = Object.assign({}, DEFAULTS, store.get(SETTINGS_KEY, {}));
    if (!s.llm_url && s.ollama) s.llm_url = s.ollama;  // saved by an older version
    if (!Array.isArray(s.disabled_rules)) s.disabled_rules = [];
    return s;
}
function saveSettings(s) { store.set(SETTINGS_KEY, s); }

// ---------------------------------------------------------------- theme
if (store.get('llm4l5x.theme', 'light') === 'dark') document.body.classList.add('dark-mode');
$('toggleTheme').onclick = () => {
    document.body.classList.toggle('dark-mode');
    store.set('llm4l5x.theme', document.body.classList.contains('dark-mode') ? 'dark' : 'light');
};

// ---------------------------------------------------------------- DOM helpers
function el(tag, opts = {}, ...children) {
    const e = document.createElement(tag);
    if (opts.cls) e.className = opts.cls;
    if (opts.text !== undefined) e.textContent = opts.text;
    if (opts.title) e.title = opts.title;
    for (const c of children) if (c) e.appendChild(c);
    return e;
}

async function fetchModels(s) {
    const res = await fetch('/api/llm/models', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ settings: s }),
    });
    return res.json();
}

let savedTimer = null;
function flashSaved() {
    const n = $('savedNote');
    if (!n) return;
    n.textContent = '✔ Saved';
    clearTimeout(savedTimer);
    savedTimer = setTimeout(() => (n.textContent = ''), 1500);
}
