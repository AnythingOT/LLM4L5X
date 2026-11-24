// Energize page: load a program + plant, drive inputs, watch outputs and the ladder light up.
// All text goes in with textContent: tag names and rung text come from files. The only markup inserted
// is the rung drawings, which the server builds from the rung with every text escaped (explain/ladder.py).
'use strict';

let running = null;  // interval id while Run is on
let busy = false;
let view = null;     // what the last load returned
let typing = null;   // the number field being edited: live values must not overwrite it
let pending = {};    // writes not sent yet: a click while a step is on its way is sent with the next one

function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
}

// before a load the message goes under the files; once loaded, into the toolbar, which stays in view
function msg(text, bad) {
    const live = !$('enLive').hidden;
    const box = live ? $('enLiveMsg') : $('enMsg');
    $(live ? 'enMsg' : 'enLiveMsg').textContent = '';
    box.textContent = text;
    box.classList.toggle('err', !!bad);
}

async function post(url, body, form) {
    const r = await fetch(url, form ? { method: 'POST', body: form }
        : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
    const j = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
    if (!r.ok || j.error) throw new Error(j.error || j.message || `HTTP ${r.status}`);
    return j;
}

const isOn = (v) => v === true || (typeof v === 'number' && v !== 0);
function num(v) {
    if (typeof v === 'boolean') return v ? '1' : '0';
    if (typeof v === 'number' && !Number.isInteger(v)) return String(Math.round(v * 1000) / 1000);
    return String(v);
}

// ------------------------------------------------------------------ building the lists

function inputRow(tag) {
    const li = el('li', 'en-row');
    li.dataset.tag = tag;
    const id = 'in_' + tag.replace(/[^\w]/g, '_');
    const name = el('label', 'en-name', tag);
    name.htmlFor = id;
    let ctl;
    if (view.kinds[tag] === 'BOOL') {
        ctl = el('input', 'switch');
        ctl.type = 'checkbox';
        ctl.onchange = () => write(tag, ctl.checked ? 1 : 0);
    } else {
        ctl = el('input', 'en-num');
        ctl.type = 'number';
        ctl.step = 'any';
        ctl.onfocus = () => { typing = tag; };
        ctl.onblur = () => { typing = null; };
        ctl.onkeydown = (e) => {
            if (e.key === 'Enter') { e.preventDefault(); commit(tag, ctl); }
            if (e.key === 'Escape') { ctl.blur(); }
        };
        ctl.onchange = () => commit(tag, ctl);
    }
    ctl.id = id;
    ctl.dataset.ctl = tag;
    li.append(name, ctl);
    return li;
}

function outputRow(tag) {
    const li = el('li', 'en-row');
    li.dataset.tag = tag;
    li.append(el('span', 'en-name', tag));
    if (view.kinds[tag] === 'BOOL') {
        const lamp = el('span', 'en-lamp');
        lamp.dataset.lamp = tag;
        lamp.setAttribute('role', 'img');
        li.append(lamp);
    } else {
        const v = el('span', 'en-val');
        v.dataset.val = tag;
        li.append(v);
    }
    return li;
}

function structRow(s) {
    const li = el('li', 'en-row en-struct');
    li.dataset.tag = s.name;
    const top = el('div', 'en-struct-top');
    top.append(el('span', 'en-name', s.name), el('span', 'en-val', ''), el('span', 'en-dn', 'DN'));
    const bar = el('div', 'en-bar');
    bar.setAttribute('role', 'progressbar');
    bar.setAttribute('aria-label', s.name);
    bar.append(el('i'));
    li.dataset.kind = s.kind;
    li.append(top, bar);
    return li;
}

function fill(id, items, make) {
    $(id).replaceChildren(...items.map(make));
}

function build(j) {
    view = j;
    pending = {};  // a change queued for the previous program must not reach this one
    const structNames = new Set(j.structs.map((s) => s.name));
    const isMember = (t) => structNames.has(t.split('.')[0]) && t.includes('.');
    fill('enInputs', j.inputs, inputRow);
    fill('enOutputs', j.outputs.filter((t) => !isMember(t)), outputRow);
    fill('enStructs', j.structs, structRow);
    fill('enFeedback', j.feedbacks, outputRow);
    $('enStructHead').hidden = !j.structs.length;
    $('enFeedHead').hidden = !j.feedbacks.length;

    // rungs, grouped by routine as in Logix Designer; a rung the drawing cannot lay out shows its text
    const box = $('enRungs');
    box.replaceChildren();
    let routine = null;
    j.rungs.forEach((r, i) => {
        if (r.routine !== routine) {
            routine = r.routine;
            box.append(el('h3', 'en-routine', routine));
        }
        const fig = el('figure', 'en-rung');
        fig.dataset.i = i;
        if (r.svg) fig.insertAdjacentHTML('beforeend', r.svg);  // server-built, escaped: see the header
        else fig.append(el('code', '', `${r.number}  ${r.text}`));
        box.append(fig);
    });

    $('enSkipped').replaceChildren(...j.skipped.map((t) => el('li', '', t)));
    $('enSkippedBox').hidden = !j.skipped.length;
    $('enDevices').textContent = j.devices ? `Device models: ${j.devices}` : 'Add device models';
    $('enDevices').title = j.devices ? 'Device models answer the outputs; edit them on the Tests page'
        : 'Nothing answers the outputs yet: add device models on the Tests page';
    const files = (j.names || []).join(', ');
    const plain = j.outputs.filter((t) => !isMember(t)).length;
    $('enSummary').textContent = `${files}: ${j.rungs.length} rungs, ${j.inputs.length} inputs, ${plain} outputs`
        + (j.structs.length ? `, ${j.structs.length} ${j.structs.length === 1 ? 'timer or counter' : 'timers and counters'}` : '')
        + (j.feedbacks.length ? `, ${j.feedbacks.length} from the device models` : '');
    document.querySelectorAll('.en-filter').forEach((f) => { f.value = ''; });
}

// ------------------------------------------------------------------ live values

function show(snap) {
    const t = snap.tags;
    $('enTime').textContent = (snap.now_ms / 1000).toFixed(2);
    document.querySelectorAll('[data-ctl]').forEach((c) => {
        const v = t[c.dataset.ctl];
        if (c.type === 'checkbox') c.checked = isOn(v);
        else if (typing !== c.dataset.ctl) c.value = num(v);
    });
    document.querySelectorAll('[data-lamp]').forEach((l) => {
        const on = isOn(t[l.dataset.lamp]);
        l.classList.toggle('on', on);
        l.setAttribute('aria-label', on ? 'on' : 'off');
    });
    document.querySelectorAll('[data-val]').forEach((v) => { v.textContent = num(t[v.dataset.val]); });
    for (const li of $('enStructs').children) {
        const n = li.dataset.tag;
        const acc = Number(t[`${n}.ACC`]) || 0;
        const pre = Number(t[`${n}.PRE`]) || 0;
        const timer = li.dataset.kind === 'TIMER';
        li.querySelector('.en-val').textContent = timer
            ? `${(acc / 1000).toFixed(1)} / ${(pre / 1000).toFixed(1)} s` : `${acc} / ${pre}`;
        const pct = pre > 0 ? Math.max(0, Math.min(100, (100 * acc) / pre)) : 0;
        li.querySelector('.en-bar i').style.width = `${pct}%`;
        li.querySelector('.en-bar').setAttribute('aria-valuenow', String(Math.round(pct)));
        li.classList.toggle('done', isOn(t[`${n}.DN`]));
    }
    // the ladder, as Logix Designer shows it online: a contact passes power, a coil is on, a rung is true
    document.querySelectorAll('#enRungs .lad-el').forEach((g) => {
        const v = isOn(t[g.dataset.tag]);
        const k = g.dataset.kind;
        g.classList.toggle('live', k === 'XIC' ? v : k === 'XIO' ? !v : v);
    });
    document.querySelectorAll('#enRungs .en-rung').forEach((f) => f.classList.toggle('lit', !!snap.power[f.dataset.i]));
    const notes = snap.notes || [];
    $('enNotes').replaceChildren(...notes.map((n) => el('li', '', n)));
    $('enNotes').hidden = !notes.length;
}

async function step(ms) {
    if (busy) return;
    busy = true;
    const writes = pending;
    pending = {};
    try { show(await post('/api/energize/step', { ms, writes })); }
    catch (e) { stop(); msg(e.message, true); }
    finally { busy = false; }
    if (Object.keys(pending).length) step(0);  // written while this step was on its way
}

function write(tag, value) {
    pending[tag] = value;
    return step(0);
}

function commit(tag, input) {
    const v = Number(input.value);
    if (input.value.trim() === '' || !Number.isFinite(v)) {  // a number field reads "" for "-" or "1e"
        msg(`${tag}: type a number, then press Enter`, true);
        return;
    }
    msg('');
    write(tag, v);
}

function stop() {
    if (!running) return;
    clearInterval(running);
    running = null;
    $('enRun').textContent = 'Run';
    $('enRun').setAttribute('aria-pressed', 'false');
}

// ------------------------------------------------------------------ controls

$('enFiles').onchange = () => {
    const names = [...$('enFiles').files].map((f) => f.name);
    $('enFileNames').textContent = names.length ? names.join(', ') : 'L5X routines, a project export, or the Routines.zip from a requirements run';
    $('enLoad').disabled = !names.length;
};

$('enRun').onclick = () => {
    if (running) { stop(); return; }
    running = setInterval(() => step(200), 200);  // real time: 200 ms of plant time every 200 ms
    $('enRun').textContent = 'Pause';
    $('enRun').setAttribute('aria-pressed', 'true');
};
$('enStep').onclick = () => step(100);
$('enReset').onclick = async () => {
    stop();
    pending = {};
    try { show(await post('/api/energize/step', { reset: true })); } catch (e) { msg(e.message, true); }
};
$('enChange').onclick = () => {
    stop();
    $('enSetup').hidden = false;
    $('enFiles').focus();
};

function open_(j) {  // a loaded program: build the page from it and show its live state
    build(j);
    show(j.snapshot);
    $('enSetup').hidden = true;
    $('enLive').hidden = false;
}

$('enLoad').onclick = async () => {
    stop();
    const form = new FormData();
    for (const f of $('enFiles').files) form.append('files', f);
    msg('Loading...');
    $('enLoad').disabled = true;
    try {
        const j = await post('/api/energize/load', null, form);
        msg('');
        open_(j);
    } catch (e) {
        msg(e.message, true);
    } finally {
        $('enLoad').disabled = !$('enFiles').files.length;
    }
};

// the program stays loaded on the server: coming back to this page (or from Tests) shows it as it was left
(async () => {
    try {
        const j = await (await fetch('/api/energize/state')).json();
        if (j.loaded) open_(j);
    } catch { /* nothing loaded: the page starts empty */ }
})();

document.querySelectorAll('.en-filter').forEach((f) => {
    f.oninput = () => {
        const q = f.value.trim().toLowerCase();
        for (const id of f.dataset.for.split(' ')) {
            for (const li of $(id).children) li.hidden = !!q && !li.dataset.tag.toLowerCase().includes(q);
        }
    };
});
