// Chat page.
'use strict';

const chatWindow = $('chatWindow');
const inputBox = $('inputBox');
const enterButton = $('enterButton');
const inputWrapper = $('inputWrapper');
let settings = loadSettings();
window.addEventListener('focus', () => { settings = loadSettings(); updateBadge(); });  // changed in another tab

// ---------------------------------------------------------------- model badge
async function updateBadge() {
    const dot = $('modelDot');
    const label = BACKEND_INFO[settings.backend] ? BACKEND_INFO[settings.backend].label : settings.backend;
    $('modelBadgeText').textContent = settings.backend === 'llamacpp' ? label : `${settings.model || 'default model'} · ${label}`;
    dot.className = 'dot';
    try {
        const d = await fetchModels(settings);
        dot.className = 'dot ' + (d.ok ? 'ok' : 'bad');
        if (d.ok && settings.backend === 'llamacpp' && d.models.length) $('modelBadgeText').textContent = `${d.models[0]} · ${label}`;
        $('modelBadge').title = d.ok ? `Connected: ${d.url}${d.grammar ? ' (grammar-constrained)' : ''}. Click to change.`
            : `${d.error}. Click to change.`;
    } catch { dot.className = 'dot bad'; }
}

// ---------------------------------------------------------------- help popup and examples row
const helpModal = $('helpModal');
function openHelp() { helpModal.classList.add('show'); }
$('helpButton').onclick = openHelp;
helpModal.querySelector('.close-button').onclick = () => helpModal.classList.remove('show');
helpModal.onclick = (e) => { if (e.target === helpModal) helpModal.classList.remove('show'); };
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') helpModal.classList.remove('show'); });

const chips = $('chips');
function setChips(open) {
    chips.hidden = !open;
    $('examplesButton').setAttribute('aria-expanded', String(open));
    $('examplesButton').classList.toggle('active', open);
    store.set('llm4l5x.chips', open);
}
$('examplesButton').onclick = () => setChips(chips.hidden);
setChips(store.get('llm4l5x.chips', false));

// ---------------------------------------------------------------- message helpers
function scrollDown() { window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'smooth' }); }
function addUser(text) { chatWindow.appendChild(el('div', { cls: 'chat-message user', text })); scrollDown(); }
function addBot(...children) {
    const m = el('div', { cls: 'chat-message bot' }, ...children);
    chatWindow.appendChild(m);
    scrollDown();
    return m;
}
function loading(label) {
    const t = el('span', { cls: 'loading-text', text: label });
    for (let i = 0; i < 3; i++) t.appendChild(el('span', { cls: 'loading-dot', text: '.' }));
    return addBot(t);
}
function title(text) { return el('div', { cls: 'section-title', text }); }
function code(text) { return el('div', { cls: 'code-style', text }); }
function button(label, onClick) {
    const b = el('button', { cls: 'save-btn', text: label });
    b.onclick = onClick;
    return b;
}
function copyButton(getText, label) {
    const b = button(label, async () => {
        try { await navigator.clipboard.writeText(getText()); b.textContent = 'Copied'; }
        catch { b.textContent = 'Copy failed'; }
        setTimeout(() => (b.textContent = label), 1500);
    });
    return b;
}
function download(filename, text) {
    const blob = new Blob([text], { type: 'application/xml' });
    const a = el('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}
function duration(s) { return s === undefined ? null : el('span', { cls: 'duration', text: `⏱️ ${s.toFixed(2)}s` }); }
function table(headers, rows, monoCols = []) {
    const t = el('table', { cls: 'grid' });
    const hr = el('tr');
    headers.forEach((h) => hr.appendChild(el('th', { text: h })));
    t.appendChild(hr);
    rows.forEach((r) => {
        const tr = el('tr');
        r.forEach((c, i) => tr.appendChild(el('td', { cls: monoCols.includes(i) ? 'mono' : '', text: c ?? '' })));
        t.appendChild(tr);
    });
    return t;
}
const fmtName = (f) => (f === 'ascii' ? 'ASCII' : 'neutral');

// import checks (will it import) and rule findings (is it good), one list
function checksBlock(issues, findings, warnings) {
    const box = el('div', { cls: 'checks' });
    (warnings || []).forEach((w) => box.appendChild(el('div', { cls: 'warn', text: `⚠ ${w}` })));
    (issues || []).forEach((i) => box.appendChild(el('div', {
        cls: i.level === 'error' ? 'err' : 'warn',
        text: `${i.level === 'error' ? '✖' : '⚠'} ${i.where ?? 'Rung ' + i.rung}: ${i.message}`,
    })));
    (findings || []).forEach((f) => box.appendChild(findingRow(f)));
    return box.childNodes.length ? box : null;
}
function findingRow(f) {
    return el('div', { cls: 'finding' },
        el('span', { cls: `code ${f.severity}`, text: f.code, title: f.title }),
        el('span', { cls: 'finding-where', text: f.location }),
        el('span', { text: f.message }));
}

function attemptsBlock(attempts) {
    const det = el('details');
    det.appendChild(el('summary', { text: `The model needed ${attempts.length} attempts` }));
    attempts.forEach((a, i) => det.appendChild(el('div', { cls: a.error ? 'warn' : 'ok',
        text: `#${i + 1}: ${a.error ? a.error : 'accepted'}` })));
    return det;
}

// rungs, read-back, tags, checks, then Copy + Download (formats from Settings)
function resultBody(d, { rungs, english, copyForm }) {
    const parts = [];
    if (english && english.length) {
        parts.push(title('What this does: check it'));
        const ul = el('ul', { cls: 'readback' });
        english.forEach((r) => ul.appendChild(el('li', { text: r })));
        parts.push(ul);
    }
    const shown = rungs.map((r) => (copyForm === 'ascii' ? r.ascii : r.text)).join('\n');
    parts.push(title(`Rungs (${rungs.length}), ${fmtName(copyForm)} text`));
    parts.push(code(shown));
    if (d.tags && d.tags.length) {
        parts.push(title(`Tags in the download (${d.tags.length})`));
        parts.push(table(['Tag', 'Type', 'Preset', ''],
            d.tags.map((t) => [t.name, t.type, t.preset ?? '', t.auto ? 'helper' : '']), [0]));
    }
    const cb = checksBlock(d.issues, d.lint, d.warnings);
    if (cb) { parts.push(title('Checks')); parts.push(cb); }
    const errs = (d.issues || []).filter((i) => i.level === 'error').length;
    parts.push(el('div', {
        cls: 'status-line ' + (errs ? 'err' : 'ok'),
        text: errs ? `✖ ${errs} import error(s): no L5X produced`
            : `✔ Ready${d.used_project ? `, checked against ${d.used_project}` : ': no project attached, so tag names are not checked'}`,
    }));
    const row = el('div', { cls: 'btn-row' });
    row.appendChild(copyButton(() => shown, `Copy ${fmtName(copyForm)}`));
    if (d.l5x) row.appendChild(button(`Download ${d.filename}`, () => download(d.filename, d.l5x)));
    const dur = duration(d.seconds); if (dur) row.appendChild(dur);
    parts.push(row);
    return parts;
}

// ---------------------------------------------------------------- renderers
const render = {
    help() { openHelp(); return null; },

    error(d) {
        const parts = [el('div', { cls: 'err', text: d.message })];
        if (d.hint) parts.push(el('div', { cls: 'rung-comment', text: d.hint }));
        if (d.attempts && d.attempts.length) parts.push(attemptsBlock(d.attempts));
        return addBot(...parts);
    },

    info(d) { return addBot(el('div', { text: d.message })); },

    generated(d) {
        const parts = resultBody(d, { rungs: d.rungs, english: d.readback, copyForm: settings.rung_format });
        const meta = el('div', { cls: 'duration', text: `🤖 ${d.model} via ${d.backend}${d.grammar ? ', grammar-constrained' : ''}: `
            + `${d.model_seconds.toFixed(1)}s, ${d.attempts.length} attempt${d.attempts.length > 1 ? 's' : ''}` });
        parts.unshift(meta);
        if (d.attempts.length > 1) parts.splice(1, 0, attemptsBlock(d.attempts));
        return addBot(...parts);
    },

    compiled(d) {  // typed in the logic language (kept for testing; not advertised)
        return addBot(...resultBody(d, { rungs: d.rungs, english: d.readback, copyForm: settings.rung_format }));
    },

    rungs(d) {
        // show and copy the form the user did NOT type
        const other = d.source === 'ASCII' ? 'neutral' : 'ascii';
        const english = [];
        const parts = [];
        d.rungs.forEach((r, i) => {
            if (r.english.length) r.english.forEach((e) => english.push(d.rungs.length > 1 ? `Rung ${i}: ${e}` : e));
            else english.push(`Rung ${i}: not explained (${r.why})`);
        });
        parts.push(...resultBody(d, { rungs: d.rungs, english, copyForm: other }));
        parts.unshift(el('div', { cls: 'status-line', text: d.source === 'ASCII'
            ? `ASCII → neutral text (${d.rungs.length} rung${d.rungs.length > 1 ? 's' : ''})`
            : `Neutral → ASCII text (${d.rungs.length} rung${d.rungs.length > 1 ? 's' : ''})` }));
        return addBot(...parts);
    },

    project(d) {
        setProject(d.filename, d.programs, d.default_program);
        if (d.revision_major) {
            settings = loadSettings();
            settings.revision = `${d.revision_major}.00`;
            saveSettings(settings);
        }
        const unparsed = d.routines.reduce((a, r) => a + r.unparsed, 0);
        const parts = [
            el('div', { cls: 'status-line ok', text: `✔ Attached ${d.filename}` }),
            el('div', { text: `${d.target ?? '?'} export · controller ${d.controller ?? '?'} · version ${d.revision ?? '?'}` }),
            el('div', { text: `${d.tags} tags · ${d.udts.length} UDTs · ${d.aois.length} AOIs · ${d.routines.length} routines` }),
            table(['Program', 'Routine', 'Type', 'Rungs', 'Did not parse'],
                d.routines.map((r) => [r.program, r.name, r.type, String(r.rungs), r.unparsed ? String(r.unparsed) : ''])),
        ];
        if (unparsed) parts.push(el('div', { cls: 'warn', text: `⚠ ${unparsed} rung(s) could not be read: Validate lists them.` }));
        const v36 = (d.revision_major ?? 0) >= 36;
        parts.push(el('div', { cls: 'rung-comment', text: `New logic now uses this project's tags and AOIs, with v${d.revision_major ?? '?'} instruction names (${v36 ? 'GT, EQ, MOVE …' : 'GRT, EQU, MOV …'}).` }));
        const row = el('div', { cls: 'btn-row' });
        row.appendChild(button('Explain all rungs', () => send('decompile')));
        row.appendChild(button('Validate', () => send('validate')));
        parts.push(row);
        return addBot(...parts);
    },

    decompiled(d) {
        const form = settings.rung_format;
        const parts = [el('div', { cls: 'status-line', text: `${d.ok} of ${d.total} rungs explained` })];
        const det = el('details');
        det.open = d.total <= 40;
        det.appendChild(el('summary', { text: 'Show every rung' }));
        det.appendChild(table(['Where', `Rung (${fmtName(form)})`, 'What it does'],
            d.rows.map((r) => [r.where, (form === 'ascii' && r.ascii) ? r.ascii : r.text,
                r.english ? r.english.join(' ') : `✖ ${r.why}`]), [1]));
        parts.push(det);
        const text = d.rows.map((r) => `${r.where}\n  ${r.english ? r.english.join('\n  ') : 'not explained: ' + r.why}`).join('\n');
        const row = el('div', { cls: 'btn-row' });
        row.appendChild(copyButton(() => text, 'Copy explanations'));
        row.appendChild(button('Download .txt', () => download('Explained.txt', text)));
        parts.push(row);
        return addBot(...parts);
    },

    validated(d) {
        const imp = d.import || [];
        const errs = imp.filter((r) => r.level === 'error').length;
        const L = d.lint;
        const c = L.counts;
        const parts = [
            title('Import checks: will Studio 5000 accept it'),
            el('div', { cls: 'status-line ' + (errs ? 'err' : 'ok'), text: errs || imp.length
                ? `${errs} error(s), ${imp.length - errs} warning(s)` : '✔ No problems' }),
        ];
        const ib = checksBlock(imp, [], []);
        if (ib) parts.push(ib);
        parts.push(title('Rules: is it good'));
        const summary = el('div', { cls: 'sev-summary' });
        [['critical', 'Critical'], ['error', 'Error'], ['warning', 'Warning'], ['info', 'Info']].forEach(([k, label]) =>
            summary.appendChild(el('span', { cls: `code ${k}`, text: `${c[k]} ${label}` })));
        parts.push(summary);
        const order = ['critical', 'error', 'warning', 'info'];
        for (const sev of order) {
            const list = L.findings.filter((f) => f.severity === sev);
            if (!list.length) continue;
            const byCode = new Map();
            list.forEach((f) => { if (!byCode.has(f.code)) byCode.set(f.code, []); byCode.get(f.code).push(f); });
            for (const [codeName, fs] of byCode) {
                const det = el('details', { cls: 'rule-findings' });
                det.open = sev === 'critical' || (sev === 'error' && fs.length <= 5);
                det.appendChild(el('summary', {}, el('span', { cls: `code ${sev}`, text: codeName }),
                    el('span', { text: ` ${fs[0].title} (${fs.length})` })));
                fs.forEach((f) => det.appendChild(el('div', { cls: 'finding' },
                    el('span', { cls: 'finding-where', text: f.location }), el('span', { text: f.message }))));
                parts.push(det);
            }
        }
        (L.not_verified || []).forEach((n) => parts.push(el('div', { cls: 'warn', text: `? not verified ${n}` })));
        (L.errors || []).forEach((n) => parts.push(el('div', { cls: 'err', text: `✖ a rule crashed: ${n}` })));
        (L.notes || []).forEach((n) => parts.push(el('div', { cls: 'rung-comment', text: n })));
        const extra = [];
        if (L.suppressed.length) extra.push(`${L.suppressed.length} finding(s) accepted with lint:disable`);
        if (L.disabled.length) extra.push(`${L.disabled.length} rule(s) switched off`);
        const row = el('div', { cls: 'btn-row' });
        if (extra.length) row.appendChild(el('span', { cls: 'muted', text: extra.join(' · ') }));
        const a = el('a', { cls: 'save-btn', text: 'Rules page' }); a.href = '/rules';
        row.appendChild(a);
        const report = [`Validation of ${d.filename}`, '', 'Import checks:',
            ...imp.map((i) => `  [${i.level}] ${i.where}: ${i.message}`), '',
            `Rules: ${c.critical} critical, ${c.error} error, ${c.warning} warning, ${c.info} info`,
            ...L.findings.map((f) => `  ${f.code} ${f.location}: ${f.message}`),
            ...(L.not_verified || []).map((n) => `  not verified ${n}`), ...(L.notes || []).map((n) => `  note: ${n}`)].join('\n');
        row.appendChild(button('Download report', () => download('Validation.txt', report)));
        parts.push(row);
        return addBot(...parts);
    },

    xref(d) {
        if (!d.refs.length) return addBot(el('div', { text: `No references to ${d.tag}.` }));
        return addBot(
            el('div', { cls: 'status-line', text: `${d.refs.length} reference(s) to ${d.tag}` }),
            table(['Where', 'Instruction', 'Operand', 'Role'],
                d.refs.map((r) => [r.where, r.instruction, r.operand, r.role]), [1, 2]),
        );
    },
};

function show(d) { (render[d.kind] || render.error)(d.kind in render ? d : { message: 'Unexpected reply from the server.' }); }

// ---------------------------------------------------------------- sending
async function send(text) {
    settings = loadSettings();
    if (/^\s*(help|\?)\s*$/i.test(text)) { openHelp(); return; }
    addUser(text);
    const english = !/:=|;|^\s*(summary|decompile|validate|xref)\b/i.test(text) && !/^\s*\w+\s*\(/.test(text)
        && !/^\s*(XIC|XIO|SOR|BST)\b/i.test(text);
    const who = settings.backend === 'llamacpp' ? 'the model' : (settings.model || 'the model');
    const wait = loading(english ? `Asking ${who} (can take a minute on a CPU)` : 'Working');
    try {
        const res = await fetch('/api/process', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text, settings }),
        });
        wait.remove();
        show(await res.json());
    } catch (e) {
        wait.remove();
        render.error({ message: `Cannot reach the server: ${e.message}. Is 'python app.py' still running?` });
    }
}

function onInput() { enterButton.disabled = !inputBox.value.trim(); }
inputBox.addEventListener('input', onInput);
inputBox.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); }
});
enterButton.onclick = submit;
function submit() {
    const text = inputBox.value.trim();
    if (!text) return;
    inputBox.value = '';
    onInput();
    send(text);
}
document.querySelectorAll('.chip').forEach((c) => {
    c.onclick = () => {
        if (c.dataset.send) send(c.dataset.send);
        else { inputBox.value = c.dataset.text; onInput(); inputBox.focus(); }
    };
});

// ---------------------------------------------------------------- project attach / detach
function setProject(name, programs, preferred) {
    $('projectBadge').hidden = !name;
    $('projectName').textContent = name ? `📁 ${name}` : '';
    document.querySelectorAll('.project-only').forEach((c) => (c.hidden = !name));
    if (programs && programs.length) {
        settings = loadSettings();
        if (!programs.includes(settings.program)) { settings.program = preferred || programs[0]; saveSettings(settings); }
    }
}

async function upload(file) {
    addUser(`📎 ${file.name}`);
    const wait = loading('Reading the L5X');
    const fd = new FormData();
    fd.append('file', file);
    try {
        const res = await fetch('/api/project', { method: 'POST', body: fd });
        wait.remove();
        if (res.status === 413) return render.error({ message: 'The file is larger than the 50 MB limit.' });
        show(await res.json());
    } catch (e) {
        wait.remove();
        render.error({ message: `Upload failed: ${e.message}` });
    }
}
$('attachButton').onclick = () => $('fileInput').click();
$('fileInput').onchange = () => { const f = $('fileInput'); if (f.files.length) upload(f.files[0]); f.value = ''; };
$('detachButton').onclick = async () => {
    const res = await fetch('/api/project', { method: 'DELETE' });
    setProject(null, []);
    show(await res.json());
};
['dragenter', 'dragover'].forEach((ev) => inputWrapper.addEventListener(ev, (e) => { e.preventDefault(); inputWrapper.classList.add('dragging'); }));
['dragleave', 'drop'].forEach((ev) => inputWrapper.addEventListener(ev, (e) => { e.preventDefault(); inputWrapper.classList.remove('dragging'); }));
inputWrapper.addEventListener('drop', (e) => { const f = e.dataTransfer.files[0]; if (f) upload(f); });

// ---------------------------------------------------------------- start
(async () => {
    try {
        const s = await (await fetch('/api/status')).json();
        setProject(s.project, s.programs, s.default_program);
    } catch { /* server not ready */ }
    updateBadge();
    addBot(
        el('div', { text: 'Describe ladder logic in plain English, or paste rungs, and get checked Studio 5000 rungs. Everything runs on this PC.' }),
        el('div', { cls: 'rung-comment', text: 'Press ? for what it can do, ⓘ in the input box for examples. Attach your .L5X so the logic uses your real tag names.' }),
    );
})();
