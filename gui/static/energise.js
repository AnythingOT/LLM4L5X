// Energise page: load a program + plant, drive inputs, watch outputs and energised rungs.
// All text goes in with textContent: tag names and rung text come from files.
'use strict';

let running = null;  // interval id while Run is on
let busy = false;

function msg(text, bad) { $('enMsg').textContent = text; $('enMsg').classList.toggle('warn-text', !!bad); }

async function post(url, body, form) {
    const r = await fetch(url, form ? { method: 'POST', body: form }
        : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
    const j = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
    if (!r.ok || j.error) throw new Error(j.error || j.message || `HTTP ${r.status}`);
    return j;
}

// one form for every BOOL, logic (true/false) or plant (1/0): the toggle reads it back
function fmt(v) {
    if (typeof v === 'boolean') return v ? '1' : '0';
    return typeof v === 'number' && !Number.isInteger(v) ? v.toFixed(2) : String(v);
}

function rows(table, names, snap, clickable) {
    table.replaceChildren();
    for (const n of names) {
        const tr = document.createElement('tr');
        const a = document.createElement('td'); a.textContent = n;
        const b = document.createElement('td'); b.dataset.tag = n;
        const v = snap.tags[n];
        b.textContent = fmt(v);
        b.className = 'val ' + (v ? 'on' : 'off');
        if (clickable) {
            b.classList.add('click');
            b.title = 'Click: 0/1. Shift+click: type a number.';
            b.onclick = (e) => write(n, e.shiftKey);
        }
        tr.append(a, b);
        table.append(tr);
    }
}

let tags = { inputs: [], outputs: [], feedbacks: [] };

function show(snap) {
    $('enTime').textContent = (snap.now_ms / 1000).toFixed(2);
    for (const [id, list] of [['enInputs', tags.inputs], ['enOutputs', tags.outputs], ['enFeedback', tags.feedbacks]]) {
        for (const n of list) {
            const td = $(id).querySelector(`td[data-tag="${CSS.escape(n)}"]`);
            if (!td) continue;
            const v = snap.tags[n];
            td.textContent = fmt(v);
            td.classList.toggle('on', !!v); td.classList.toggle('off', !v);
        }
    }
    $('enRungs').querySelectorAll('li').forEach((li, i) => li.classList.toggle('lit', !!snap.power[i]));
    $('enNotes').replaceChildren(...(snap.notes || []).map((t) => { const li = document.createElement('li'); li.textContent = t; return li; }));
}

async function step(ms, writes) {
    if (busy) return;
    busy = true;
    try { show(await post('/api/energise/step', { ms, writes })); }
    catch (e) { stop(); msg(e.message, true); }
    finally { busy = false; }
}

async function write(tag, typed) {
    const td = $('enInputs').querySelector(`td[data-tag="${CSS.escape(tag)}"]`);
    let v;
    if (typed) {
        const t = prompt(`New value for ${tag}`, td.textContent);
        if (t === null) return;
        v = Number(t);
        if (!Number.isFinite(v)) { msg(`${t} is not a number`, true); return; }
    } else {
        v = Number(td.textContent) ? 0 : 1;
    }
    await step(0, { [tag]: v });
}

function stop() { if (running) { clearInterval(running); running = null; $('enRun').textContent = 'Run'; } }

$('enRun').onclick = () => {
    if (running) { stop(); return; }
    running = setInterval(() => step(200), 200);  // real time: 200 ms of plant time every 200 ms
    $('enRun').textContent = 'Pause';
};
$('enStep').onclick = () => step(100);
$('enReset').onclick = async () => { stop(); try { show(await post('/api/energise/step', { reset: true })); } catch (e) { msg(e.message, true); } };

$('enLoad').onclick = async () => {
    stop();
    const form = new FormData();
    for (const f of $('enFiles').files) form.append('files', f);
    form.append('plant', $('enPlant').value);
    form.append('scenarios', $('enScenarios').value);
    msg('Loading...');
    try {
        const j = await post('/api/energise/load', null, form);
        tags = { inputs: j.inputs, outputs: j.outputs, feedbacks: j.feedbacks };
        rows($('enInputs'), j.inputs, j.snapshot, true);
        rows($('enOutputs'), j.outputs, j.snapshot, false);
        rows($('enFeedback'), j.feedbacks, j.snapshot, false);
        $('enSkipped').replaceChildren(...j.skipped.map((t) => { const li = document.createElement('li'); li.textContent = t; return li; }));
        $('enRungs').replaceChildren(...j.rungs.map((r) => {
            const li = document.createElement('li');
            const where = document.createElement('span'); where.className = 'muted'; where.textContent = `${r.routine} ${r.number}  `;
            const code = document.createElement('code'); code.textContent = r.text;
            li.append(where, code);
            return li;
        }));
        $('enLive').hidden = false; $('enRungsCard').hidden = false; $('enScenRow').hidden = !j.has_scenarios;
        $('enReport').hidden = true;
        show(j.snapshot);
        msg(`${j.rungs.length} rungs, ${j.inputs.length} inputs, ${j.feedbacks.length} plant feedback tags.`);
    } catch (e) { msg(e.message, true); }
};

$('enScen').onclick = async () => {
    $('enScenSum').textContent = 'Running...';
    try {
        const j = await post('/api/energise/scenarios');
        $('enScenSum').textContent = `${j.passed} of ${j.total} scenarios pass`;
        $('enReport').textContent = j.report.join('\n');
        $('enReport').hidden = false;
    } catch (e) { $('enScenSum').textContent = e.message; }
};
