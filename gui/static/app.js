// LLM4L5X chat GUI. All text is inserted with textContent (never innerHTML)
// so tag names and comments from L5X files cannot inject markup.
'use strict';

const $ = (id) => document.getElementById(id);
const chatWindow = $('chatWindow');
const inputBox = $('inputBox');
const enterButton = $('enterButton');
const attachButton = $('attachButton');
const fileInput = $('fileInput');
const inputWrapper = $('inputWrapper');

// ---------------------------------------------------------------- storage (may be unavailable)
const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* ignore */ } },
};

// ---------------------------------------------------------------- settings
const DEFAULTS = {
    output: 'rungs', routine: 'GeneratedRoutine', program: 'MainProgram', controller: 'LLM4L5X',
    revision: '32.04', scope: 'controller', display: 'placeholder', prefix: 'L4X', comments: true,
};
let settings = Object.assign({}, DEFAULTS, store.get('llm4l5x.settings', {}));
const fields = {
    output: 'setOutput', routine: 'setRoutine', program: 'setProgram', controller: 'setController',
    revision: 'setRevision', scope: 'setScope', display: 'setDisplay', prefix: 'setPrefix', comments: 'setComments',
};
function fillSettings() {
    for (const [k, id] of Object.entries(fields)) {
        const el = $(id);
        if (el.type === 'checkbox') el.checked = !!settings[k]; else el.value = settings[k];
    }
}
function readSettings() {
    for (const [k, id] of Object.entries(fields)) {
        const el = $(id);
        settings[k] = el.type === 'checkbox' ? el.checked : el.value.trim();
    }
    store.set('llm4l5x.settings', settings);
}
const modal = $('settingsModal');
$('settingsButton').onclick = () => { fillSettings(); modal.classList.add('show'); };
modal.querySelector('.close-button').onclick = () => modal.classList.remove('show');
modal.onclick = (e) => { if (e.target === modal) modal.classList.remove('show'); };
$('saveSettings').onclick = () => { readSettings(); modal.classList.remove('show'); };
$('resetSettings').onclick = () => { settings = Object.assign({}, DEFAULTS); fillSettings(); };

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
function scrollDown() { chatWindow.scrollTop = chatWindow.scrollHeight; }
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
function copyButton(getText, label = 'Copy') {
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
function duration(s) { return s === undefined ? null : el('span', { cls: 'duration', text: `⏱️ ${s.toFixed(3)}s` }); }
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
function issuesBlock(issues) {
    if (!issues || !issues.length) return null;
    const box = el('div');
    issues.forEach((i) => box.appendChild(el('div', {
        cls: i.level === 'error' ? 'err' : 'warn',
        text: `${i.level === 'error' ? '✖' : '⚠'} ${i.where ?? 'rung ' + i.rung}: ${i.message}`,
    })));
    return box;
}

// ---------------------------------------------------------------- renderers
const render = {
    help() {
        return addBot(
            el('div', { text: 'Type LogicSpec, paste existing rung text, or attach an .L5X export.' }),
            title('LogicSpec'),
            code([
                'Pump := (Start_PB OR Pump) AND NOT Stop_PB;      // OTE, OR = branch',
                'IF A AND N > 5 THEN SET B, CLEAR N;              // several outputs',
                'IF TRUE THEN Total := Total + 1;                 // unconditional math',
                'X := RISE(PB) AND Ready;                         // one-shot',
                'Alarm := DELAY(Level > 80.0, 5s [, TimerTag]);   // on-delay (OFFDELAY too)',
                'IF RISE(P) THEN COUNT_UP(C, 10);                 // counter (COUNT_DOWN too)',
                'Actions: SET RESET CLEAR RESET_ACC START_TIMER(T,5s) START_OFF_TIMER(T,5s) N := A [+-*/ B]',
                'Compare: =  <>  >  <  >=  <=        AND/OR mixed? parentheses are required',
            ].join('\n')),
            title('Paste existing rungs (either form)'),
            code([
                'XIC(a)[XIC(b) ,XIO(c) ]OTE(d);          // neutral text (as in L5X)',
                'XIC a BST XIC b NXB XIO c BND OTE d     // ASCII text (one rung per line, SOR/EOR ok)',
            ].join('\n')),
            title('Commands (need an attached project)'),
            code('summary      decompile      validate      xref TagName'),
        );
    },

    error(d) {
        return addBot(el('div', { cls: 'err', text: d.message }), d.hint ? el('div', { cls: 'rung-comment', text: d.hint }) : null);
    },

    info(d) { return addBot(el('div', { text: d.message })); },

    compiled(d) {
        const parts = [];
        parts.push(title('What this does — check it'));
        const ul = el('ul', { cls: 'readback' });
        d.readback.forEach((r) => ul.appendChild(el('li', { text: r })));
        parts.push(ul);

        parts.push(title(`Rungs (${d.rungs.length}) — neutral text, as stored in L5X`));
        const rungText = d.rungs.map((r) => r.text).join('\n');
        parts.push(code(rungText));
        const asciiText = d.rungs.map((r) => r.ascii).join('\n');
        const asciiBox = el('details');
        asciiBox.appendChild(el('summary', { text: 'ASCII text (for the editor\'s ASCII mode, one rung at a time)' }));
        asciiBox.appendChild(code(asciiText));
        parts.push(asciiBox);

        if (d.tags.length) {
            parts.push(title(`New tags (${d.tags.length})`));
            parts.push(table(['Tag', 'Type', 'Preset', ''],
                d.tags.map((t) => [t.name, t.type, t.preset ?? '', t.auto ? 'auto' : '']), [0]));
        }
        const notes = [];
        (d.warnings || []).forEach((w) => notes.push({ level: 'warning', where: 'note', message: w }));
        (d.issues || []).forEach((i) => notes.push(i));
        const ib = issuesBlock(notes);
        if (ib) { parts.push(title('Checks')); parts.push(ib); }

        const errs = (d.issues || []).filter((i) => i.level === 'error').length;
        parts.push(el('div', {
            cls: 'status-line ' + (errs ? 'err' : 'ok'),
            text: errs ? `✖ ${errs} error(s): no L5X produced` :
                `✔ Ready${d.used_project ? ' — checked against ' + d.used_project : ' — no project attached, tags not checked'}`,
        }));

        const row = el('div', { cls: 'btn-row' });
        if (d.l5x) row.appendChild(button(`Download ${d.filename}`, () => download(d.filename, d.l5x)));
        row.appendChild(copyButton(() => rungText, 'Copy neutral'));
        row.appendChild(copyButton(() => asciiText, 'Copy ASCII'));
        const dur = duration(d.seconds); if (dur) row.appendChild(dur);
        parts.push(row);
        return addBot(...parts);
    },

    rungs(d) {
        const parts = [title(`${d.source === 'ASCII' ? 'ASCII' : 'Neutral'} rung text → LogicSpec (${d.rungs.length})`)];
        d.rungs.forEach((r) => {
            parts.push(code(r.text));
            parts.push(el('div', { cls: 'rung-comment', text: `ASCII: ${r.ascii}` }));
            if (r.logicspec) {
                parts.push(code(r.logicspec));
                r.english.forEach((e) => parts.push(el('div', { cls: 'rung-comment', text: e })));
            } else {
                parts.push(el('div', { cls: 'warn', text: `Not convertible: ${r.why}` }));
            }
        });
        const ib = issuesBlock(d.issues);
        if (ib) { parts.push(title('Checks')); parts.push(ib); }
        const row = el('div', { cls: 'btn-row' });
        const specs = d.rungs.filter((r) => r.logicspec).map((r) => r.logicspec).join('\n');
        if (specs) row.appendChild(button('Edit as LogicSpec', () => { inputBox.value = specs; onInput(); inputBox.focus(); }));
        row.appendChild(copyButton(() => d.rungs.map((r) => r.text).join('\n'), 'Copy neutral'));
        row.appendChild(copyButton(() => d.rungs.map((r) => r.ascii).join('\n'), 'Copy ASCII'));
        const dur = duration(d.seconds); if (dur) row.appendChild(dur);
        parts.push(row);
        return addBot(...parts);
    },

    project(d) {
        setProject(d.filename, d.programs);
        if (d.revision_major) {
            settings.revision = `${d.revision_major}.00`;
            store.set('llm4l5x.settings', settings);
        }
        const unparsed = d.routines.reduce((a, r) => a + r.unparsed, 0);
        const parts = [
            el('div', { cls: 'status-line ok', text: `✔ Attached ${d.filename}` }),
            el('div', { text: `Controller ${d.controller ?? '?'} · revision ${d.revision ?? '?'} · export type ${d.target ?? '?'}` }),
            el('div', { text: `${d.tags} tags · ${d.udts.length} UDTs · ${d.aois.length} AOIs · ${d.routines.length} routines` }),
            table(['Program', 'Routine', 'Type', 'Rungs', 'Unparsed'],
                d.routines.map((r) => [r.program, r.name, r.type, String(r.rungs), r.unparsed ? String(r.unparsed) : ''])),
        ];
        if (unparsed) parts.push(el('div', { cls: 'warn', text: `⚠ ${unparsed} rung(s) could not be parsed — run 'validate' to see them.` }));
        const v36 = (d.revision_major ?? 0) >= 36;
        parts.push(el('div', { cls: 'rung-comment', text: `New LogicSpec is now checked against this project's tags and AOIs, and written with v${d.revision_major ?? '?'} instruction names (${v36 ? 'GT, EQ, MOVE …' : 'GRT, EQU, MOV …'}).` }));
        const row = el('div', { cls: 'btn-row' });
        row.appendChild(button('Decompile all rungs', () => send('decompile')));
        row.appendChild(button('Validate', () => send('validate')));
        parts.push(row);
        return addBot(...parts);
    },

    decompiled(d) {
        const parts = [el('div', { cls: 'status-line', text: `${d.ok}/${d.total} rungs convertible to LogicSpec` })];
        const det = el('details');
        det.open = d.total <= 40;
        det.appendChild(el('summary', { text: 'Show all rungs' }));
        det.appendChild(table(['Where', 'Rung', 'LogicSpec / reason'],
            d.rows.map((r) => [r.where, r.text, r.logicspec ?? `✖ ${r.why}`]), [1, 2]));
        parts.push(det);
        const specs = d.rows.filter((r) => r.logicspec).map((r) => `// ${r.where}\n${r.logicspec}`).join('\n');
        const row = el('div', { cls: 'btn-row' });
        if (specs) {
            row.appendChild(copyButton(() => specs));
            row.appendChild(button('Download .spec', () => download('decompiled.spec', specs)));
        }
        parts.push(row);
        return addBot(...parts);
    },

    validated(d) {
        const errs = d.rows.filter((r) => r.level === 'error').length;
        const warns = d.rows.length - errs;
        return addBot(
            el('div', { cls: 'status-line ' + (errs ? 'err' : 'ok'), text: `${errs} error(s), ${warns} warning(s)` }),
            issuesBlock(d.rows),
        );
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

function show(d) { (render[d.kind] || render.error)(d.kind in render ? d : { message: 'Unexpected reply from server.' }); }

// ---------------------------------------------------------------- sending
async function send(text) {
    addUser(text);
    const wait = loading('Working');
    try {
        const res = await fetch('/api/process', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, settings }),
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
        const t = c.dataset.text;
        if (t === 'help' || t === 'decompile' || t === 'validate') send(t);
        else { inputBox.value = t; onInput(); inputBox.focus(); }
    };
});

// ---------------------------------------------------------------- project attach / detach
function setProject(name, programs) {
    $('projectBadge').hidden = !name;
    $('projectName').textContent = name ? `📁 ${name}` : '';
    document.querySelectorAll('.project-only').forEach((c) => (c.hidden = !name));
    const dl = $('programList');
    dl.replaceChildren(...(programs || []).map((p) => { const o = el('option'); o.value = p; return o; }));
    if (programs && programs.length && !programs.includes(settings.program)) {
        settings.program = programs[0];
        store.set('llm4l5x.settings', settings);
    }
}

async function upload(file) {
    addUser(`📎 ${file.name}`);
    const wait = loading('Reading L5X');
    const fd = new FormData();
    fd.append('file', file);
    try {
        const res = await fetch('/api/project', { method: 'POST', body: fd });
        wait.remove();
        if (res.status === 413) return render.error({ message: 'File is larger than the 50 MB limit.' });
        show(await res.json());
    } catch (e) {
        wait.remove();
        render.error({ message: `Upload failed: ${e.message}` });
    }
}
attachButton.onclick = () => fileInput.click();
fileInput.onchange = () => { if (fileInput.files.length) upload(fileInput.files[0]); fileInput.value = ''; };
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
        setProject(s.project, s.programs);
    } catch { /* server not ready */ }
    addBot(
        el('div', { text: 'LLM4L5X — LogicSpec to Studio 5000 ladder, and back. Everything runs on this PC.' }),
        el('div', { cls: 'rung-comment', text: "Try a chip below, type 'help', or Attach an .L5X export to check against your real tags." }),
    );
})();
