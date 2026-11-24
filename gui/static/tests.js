// Tests page: test cases, kept on the server with the program Energize runs (device models: Devices page).
// All text goes in with textContent: tag names, titles and reports come from files.
'use strict';

const DRAFT_KEY = 'llm4l5x.tests.draft';  // what was typed, kept if the page is left before saving
let saved = { tests: '' };  // what the server has

function tsMsg(text, bad) {
    $('tsMsg').textContent = text;
    $('tsMsg').classList.toggle('err', !!bad);
}

function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
}

async function api(url, opts) {
    const r = await fetch(url, opts);
    const j = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
    if (!r.ok || j.error) throw new Error(j.error || `HTTP ${r.status}`);
    return j;
}

function text() { return { tests: $('tsTests').value }; }
function dirty() { return text().tests !== saved.tests; }

function showProgram(j) {
    $('tsProgram').textContent = j.loaded
        ? `${(j.names || []).join(', ')}: ${j.rungs.length} rungs` : 'No program loaded';
    $('tsOpen').hidden = !j.loaded;
}

async function save() {
    const j = await api('/api/tests/save', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(text()),
    });
    saved = text();
    store.set(DRAFT_KEY, null);
    return j;
}

$('tsSave').onclick = async () => {
    try {
        const j = await save();
        tsMsg(`Saved: ${j.tests} test case${j.tests === 1 ? '' : 's'}.`);
    } catch (e) { tsMsg(e.message, true); }
};

$('tsRun').onclick = async () => {
    $('tsRun').disabled = true;
    tsMsg('Running...');
    try {
        if (dirty()) await save();  // what is on the screen is what runs
        const j = await api('/api/tests/run', { method: 'POST' });
        tsMsg('');
        results(j);
    } catch (e) {
        tsMsg(e.message, true);
    } finally {
        $('tsRun').disabled = false;
    }
};

function verdict(ok) { return el('span', `ts-verdict ${ok ? 'pass' : 'fail'}`, ok ? 'Pass' : 'Fail'); }

function results(j) {
    $('tsResults').hidden = false;
    $('tsSum').textContent = `${j.passed} of ${j.total} test case${j.total === 1 ? '' : 's'} pass`;
    $('tsCases').replaceChildren(...j.results.map((r) => {
        const tr = el('tr');
        const name = el('td');
        name.append(el('span', 'ts-id', r.id), el('span', '', ` ${r.title || ''}`));
        if (r.error) name.append(el('div', 'ts-why', r.error));
        const result = el('td');
        result.append(verdict(r.passed));
        tr.append(name, el('td', 'ts-reqs', (r.reqs || []).join(', ') || '-'), result);
        return tr;
    }));
    $('tsTrace').replaceChildren(...Object.entries(j.trace).map(([req, cases]) => {
        const tr = el('tr');
        const result = el('td');
        result.append(verdict(cases.every(([, ok]) => ok)));
        tr.append(el('td', 'ts-id', req), el('td', 'ts-reqs', cases.map(([id]) => id).join(', ')), result);
        return tr;
    }));
    $('tsReport').textContent = j.report.join('\n');
    $('tsResults').scrollIntoView({ block: 'nearest' });
}

// a program loaded here is the same one Energize runs
$('tsFiles').onchange = async () => {
    const form = new FormData();
    for (const f of $('tsFiles').files) form.append('files', f);
    $('tsFiles').value = '';
    tsMsg('Loading...');
    try {
        if (dirty()) await save();
        showProgram(await api('/api/energize/load', { method: 'POST', body: form }));
        tsMsg('');
    } catch (e) { tsMsg(e.message, true); }
};

$('tsTests').addEventListener('input', () => store.set(DRAFT_KEY, text()));

(async () => {
    try {
        const j = await api('/api/energize/state');
        saved = { tests: j.test_text || '' };
        showProgram(j);
        const n = (j.device_list || []).length;
        $('tsDevLink').textContent = n ? `${n} device model${n === 1 ? '' : 's'}` : 'device models (none yet)';
    } catch { /* server not ready */ }
    const draft = store.get(DRAFT_KEY, null);
    $('tsTests').value = (draft && typeof draft.tests === 'string' ? draft : saved).tests;
    if (draft && dirty()) tsMsg('Not saved yet: the text from before you left the page.');
})();
