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

const GAPS = [["no_test", "Requirements with no test case"], ["not_built", "Requirements with no rung"],
    ["unknown_requirement", "Requirement IDs not in the requirements workbook"],
    ["tests_without_requirement", "Test cases tied to no requirement"],
    ["rungs_without_requirement", "Rungs that serve no requirement"]];

// a list of IDs that wraps between IDs, never inside one ("TC-" / "02")
function ids(list) {
    const td = el('td', 'ts-reqs');
    if (!list.length) { td.textContent = '-'; return td; }
    list.forEach((x, k) => { if (k) td.append(', '); td.append(el('span', 'ts-nowrap', x)); });
    return td;
}

function status(text) {
    const cls = text === 'Pass' ? 'pass' : text === 'Fail' ? 'fail' : 'gap';
    return el('span', `ts-verdict ${cls}`, text);
}

function results(j) {
    $('tsResults').hidden = false;
    $('tsSum').textContent = `${j.passed} of ${j.total} test case${j.total === 1 ? '' : 's'} pass`;
    $('tsPdf').href = `/api/tests/runs/${encodeURIComponent(j.run_id)}/report.pdf`;
    $('tsJson').href = `/api/tests/runs/${encodeURIComponent(j.run_id)}/record.json`;
    $('tsRunId').textContent = `Run ${j.run_id}: kept in the runs folder with the fingerprint of every input.`;
    $('tsMatrix').replaceChildren(...j.matrix.map((m) => {
        const tr = el('tr');
        const res = el('td');
        res.append(status(m.status));
        tr.append(el('td', 'ts-id', m.id), el('td', '', m.text || '-'), ids(m.rungs),
            ids(m.tests.map((t) => `${t.id}${t.passed ? '' : ' FAIL'}`)), res);
        return tr;
    }));
    const gaps = GAPS.filter(([k]) => (j.gaps[k] || []).length);
    $('tsGaps').replaceChildren(...gaps.map(([k, label]) => el('li', '', `${label}: ${j.gaps[k].join(', ')}`)));
    $('tsGapsBox').hidden = !gaps.length;
    $('tsCases').replaceChildren(...j.results.map((r) => {
        const tr = el('tr');
        const name = el('td');
        name.append(el('span', 'ts-id', r.id), el('span', '', ` ${r.title || ''}`));
        const why = r.error || (r.steps.find((st) => st.passed === false) || {}).message;
        if (!r.passed && why) name.append(el('div', 'ts-why', why));
        const result = el('td');
        result.append(verdict(r.passed));
        tr.append(name, el('td', 'ts-reqs', (r.reqs || []).join(', ') || '-'), result);
        return tr;
    }));
    $('tsReport').textContent = j.report.join('\n');
    $('tsResults').scrollIntoView({ block: 'nearest' });
    history();
}

async function history() {
    try {
        const { runs } = await api('/api/tests/runs');
        $('tsHistoryBox').hidden = !runs.length;
        $('tsHistory').replaceChildren(...runs.slice(0, 20).map((r) => {
            const tr = el('tr');
            const a = el('a', '', 'PDF');
            a.href = `/api/tests/runs/${encodeURIComponent(r.id)}/report.pdf`;
            const link = el('td');
            link.append(a);
            const s = r.summary || {};
            tr.title = `${r.id}: ${(r.program || []).join(', ')}`;
            tr.append(el('td', 'ts-id', r.id), el('td', s.passed === s.test_cases ? 'ok' : 'err', `${s.passed}/${s.test_cases}`), link);
            return tr;
        }));
    } catch { /* no runs yet */ }
}

$('tsReqFile').onchange = async () => {
    const f = $('tsReqFile').files[0];
    $('tsReqFile').value = '';
    if (!f) return;
    const form = new FormData();
    form.append('file', f);
    try {
        showReqs(await api('/api/tests/requirements', { method: 'POST', body: form }));
        tsMsg('');
    } catch (e) { tsMsg(e.message, true); }
};

function showReqs(r) {
    if (r) $('tsReqName').textContent = `Requirements: ${r.name}, ${r.count} requirement${r.count === 1 ? '' : 's'}`;
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
        showReqs(j.requirements);
        const n = (j.device_list || []).length;
        $('tsDevLink').textContent = n ? `${n} device model${n === 1 ? '' : 's'}` : 'device models (none yet)';
    } catch { /* server not ready */ }
    const draft = store.get(DRAFT_KEY, null);
    $('tsTests').value = (draft && typeof draft.tests === 'string' ? draft : saved).tests;
    if (draft && dirty()) tsMsg('Not saved yet: the text from before you left the page.');
    history();
})();
