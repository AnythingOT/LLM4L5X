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
    $('modelBadgeText').textContent = settings.backend === 'llamacpp' ? label : `${settings.model || 'default model'} on ${label}`;
    dot.className = 'dot';
    try {
        const d = await fetchModels(settings);
        dot.className = 'dot ' + (d.ok ? 'ok' : 'bad');
        if (d.ok && settings.backend === 'llamacpp' && d.models.length) $('modelBadgeText').textContent = `${d.models[0]} on ${label}`;
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

// ---------------------------------------------------------------- Logic / UDT mode
const PLACEHOLDER = {
    logic: 'Describe the logic, or paste rungs in neutral or ASCII text',
    udt: 'Describe a UDT, for example: a motor with run and fault bits and a speed',
};
let mode = store.get('llm4l5x.mode', 'logic');
function setMode(m) {
    mode = m === 'udt' ? 'udt' : 'logic';
    store.set('llm4l5x.mode', mode);
    document.querySelectorAll('#modeToggle button').forEach((b) => b.classList.toggle('active', b.dataset.mode === mode));
    document.querySelectorAll('.logic-only').forEach((e) => (e.hidden = mode !== 'logic'));
    document.querySelectorAll('.udt-only').forEach((e) => (e.hidden = mode !== 'udt'));
    inputBox.placeholder = PLACEHOLDER[mode];
}
document.querySelectorAll('#modeToggle button').forEach((b) => (b.onclick = () => { setMode(b.dataset.mode); inputBox.focus(); }));
setMode(mode);

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
function title(text, count) {
    const t = el('div', { cls: 'section-title', text });
    if (count !== undefined) t.appendChild(el('span', { cls: 'count', text: String(count) }));
    return t;
}
// ladder drawings: SVG made by the server (explain/ladder.py), styled by the page's CSS
function drawing(svg, note) {
    const d = el('div', { cls: 'drawing' });
    if (note) d.appendChild(el('div', { cls: 'rung-note', text: note }));
    if (svg) d.insertAdjacentHTML('beforeend', svg);
    return d;
}
async function ladders(rungs) {  // [{text, number}] -> [svg | null]
    try {
        const res = await fetch('/api/ladder', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ rungs }),
        });
        return (await res.json()).svgs;
    } catch { return rungs.map(() => null); }
}
// long lists: the first `n` items, then a button for the rest
function capped(items, n, make, into) {
    items.slice(0, n).forEach((x) => into.appendChild(make(x)));
    if (items.length > n) {
        const more = el('button', { cls: 'show-more', text: `Show all ${items.length}` });
        more.onclick = () => { items.slice(n).forEach((x) => into.insertBefore(make(x), more)); more.remove(); };
        into.appendChild(more);
    }
    return into;
}
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
function download(filename, text, type = 'application/xml') {
    const blob = text instanceof Blob ? text : new Blob([text], { type });
    const a = el('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}
function downloadBase64(filename, b64) {
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    download(filename, new Blob([bytes], { type: 'application/zip' }));
}
async function downloadUdt(selected, output, notesBox) {
    const res = await fetch('/api/udt/download', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ selected, output }),
    });
    if (!res.ok) {
        let msg = `Download failed (${res.status})`;
        try { msg = (await res.json()).message || msg; } catch { /* not JSON */ }
        notesBox.replaceChildren(el('div', { cls: 'err', text: msg }));
        return;
    }
    const cd = res.headers.get('Content-Disposition') || '';
    const name = (cd.match(/filename="([^"]+)"/) || [])[1] || 'download';
    const notes = res.headers.get('X-Notes');
    notesBox.replaceChildren();
    if (notes) {
        JSON.parse(atob(notes)).forEach((n) => notesBox.appendChild(el('div', {
            cls: /left out|only L5K/.test(n) ? 'warn' : 'rung-comment', text: n })));
    }
    download(name, await res.blob());
}
function duration(s) { return s === undefined || s === null || s < 0.05 ? null : el('span', { cls: 'duration', text: `${s.toFixed(2)} s` }); }
function modelLine(d) {
    return el('div', { cls: 'meta', text: `${d.model} on ${d.backend}${d.grammar ? ', grammar-constrained' : ''}, `
        + `${d.model_seconds.toFixed(1)} s, ${d.attempts.length} attempt${d.attempts.length > 1 ? 's' : ''}` });
}
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
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

// import checks (will it import) and rule findings (is it good), one list
function checksBlock(issues, findings, warnings) {
    const box = el('div', { cls: 'checks' });
    (warnings || []).forEach((w) => box.appendChild(el('div', { cls: 'warn', text: `⚠ ${w}` })));
    (issues || []).forEach((i) => box.appendChild(el('div', {
        cls: i.level === 'error' ? 'err' : 'warn',
        text: `${i.level === 'error' ? '✖' : '⚠'} ${i.where ?? 'Rung ' + i.rung}: ${i.message}`,
    })));
    capped(findings || [], 50, findingRow, box);
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
        parts.push(title('What it does'));
        const ul = el('ul', { cls: 'readback' });
        english.forEach((r) => ul.appendChild(el('li', { text: r })));
        parts.push(ul);
    }
    parts.push(title(rungs.length > 1 ? 'Rungs' : 'Rung', rungs.length > 1 ? rungs.length : undefined));
    rungs.forEach((r) => parts.push(drawing(r.svg, r.comment)));
    const shown = rungs.map((r) => (copyForm === 'ascii' ? r.ascii : r.text)).join('\n');
    const txt = el('details');
    txt.appendChild(el('summary', { text: `${fmtName(copyForm) === 'ASCII' ? 'ASCII' : 'Neutral'} text` }));
    txt.appendChild(code(shown));
    txt.open = true;
    parts.push(txt);
    if (d.tags && d.tags.length) {
        parts.push(title('Tags in the download', d.tags.length));
        parts.push(table(['Tag', 'Type', 'Preset', ''],
            d.tags.map((t) => [t.name, t.type, t.preset ?? '', t.auto ? 'helper' : '']), [0]));
    }
    const cb = checksBlock(d.issues, d.lint, d.warnings);
    if (cb) { parts.push(title('Checks')); parts.push(cb); }
    const errs = (d.issues || []).filter((i) => i.level === 'error').length;
    parts.push(el('div', {
        cls: 'status-line ' + (errs ? 'err' : 'ok'),
        text: errs ? `${errs} import error${errs > 1 ? 's' : ''}: fix ${errs > 1 ? 'them' : 'it'} to get an L5X`
            : `Ready to import${d.used_project ? `, checked against ${d.used_project}` : '. No file attached, so tag names are not checked'}`,
    }));
    const row = el('div', { cls: 'btn-row' });
    if (d.l5x) {
        const dl = button(`Download ${d.filename}`, () => download(d.filename, d.l5x));
        dl.classList.add('primary');
        row.appendChild(dl);
    }
    row.appendChild(copyButton(() => shown, `Copy ${fmtName(copyForm)} text`));
    const dur = duration(d.seconds); if (dur) row.appendChild(dur);
    parts.push(row);
    return parts;
}

// ---------------------------------------------------------------- renderers
const render = {
    help() { openHelp(); return null; },

    error(d) {
        const parts = [el('div', { cls: 'err', text: d.message })];
        (d.details || []).forEach((x) => parts.push(el('div', { cls: 'err small', text: `• ${x}` })));
        if (d.hint) parts.push(el('div', { cls: 'rung-comment', text: d.hint }));
        if (d.attempts && d.attempts.length) parts.push(attemptsBlock(d.attempts));
        return addBot(...parts);
    },

    info(d) { return addBot(el('div', { text: d.message })); },

    generated(d) {
        const parts = resultBody(d, { rungs: d.rungs, english: d.readback, copyForm: settings.rung_format });
        parts.unshift(modelLine(d));
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
        parts.unshift(el('div', { cls: 'meta', text: `Read as ${d.source === 'ASCII' ? 'ASCII' : 'neutral'} rung text` }));
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
            el('div', { cls: 'status-line', text: d.filename }),
            el('div', { cls: 'meta', text: `${d.target ?? 'Unknown'} export of ${d.controller ?? 'an unnamed controller'}, version ${d.revision ?? 'unknown'}` }),
            el('div', { text: [plural(d.tags, 'tag'), plural(d.udts.length, 'UDT'), plural(d.aois.length, 'AOI'), plural(d.routines.length, 'routine')].join(', ') }),
            table(['Program', 'Routine', 'Type', 'Rungs', 'Did not parse'],
                d.routines.map((r) => [r.program, r.name, r.type, String(r.rungs), r.unparsed ? String(r.unparsed) : ''])),
        ];
        if (unparsed) parts.push(el('div', { cls: 'warn', text: `${plural(unparsed, 'rung')} could not be read. Validate lists them.` }));
        const v36 = (d.revision_major ?? 0) >= 36;
        if (d.target !== 'DataType') parts.push(el('div', { cls: 'rung-comment', text: `New logic now uses these tags and AOIs, with v${d.revision_major ?? '?'} instruction names (${v36 ? 'GT, EQ, MOVE' : 'GRT, EQU, MOV'}).` }));
        const row = el('div', { cls: 'btn-row' });
        if (d.target !== 'DataType') {
            row.appendChild(button('Explain all rungs', () => send('decompile')));
            row.appendChild(button('Validate', () => send('validate')));
        }
        if (d.udts.length && !d.udt_plan) row.appendChild(button(`Optimize UDTs (${d.udts.length})`, () => send('optimize')));
        parts.push(row);
        const msg = addBot(...parts);
        if (d.udt_plan) render.udt_plan(d.udt_plan);
        return msg;
    },

    decompiled(d) {
        const form = settings.rung_format;
        const parts = [el('div', { cls: 'status-line', text: `${d.ok} of ${plural(d.total, 'rung')} explained` })];
        const list = el('div', { cls: 'checks' });
        const PAGE = 20;
        let shown = 0;
        const more = el('button', { cls: 'show-more' });
        async function next() {
            const page = d.rows.slice(shown, shown + PAGE);
            shown += page.length;
            const svgs = await ladders(page.map((r) => ({ text: r.text, number: r.number })));
            page.forEach((r, i) => {
                list.appendChild(el('div', { cls: 'finding-where', text: r.where }));
                list.appendChild(svgs[i] ? drawing(svgs[i]) : code((form === 'ascii' && r.ascii) ? r.ascii : r.text));
                list.appendChild(el('div', { cls: r.english ? 'rung-comment' : 'warn', text: r.english ? r.english.join(' ') : `Not explained: ${r.why}` }));
            });
            more.textContent = `Show the next ${Math.min(PAGE, d.rows.length - shown)} of ${d.rows.length - shown} left`;
            more.hidden = shown >= d.rows.length;
        }
        more.onclick = next;
        parts.push(list, more);
        next();
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
            title('Will Studio 5000 import it?'),
            el('div', { cls: 'status-line ' + (errs ? 'err' : 'ok'), text: errs || imp.length
                ? `${plural(errs, 'error')}, ${plural(imp.length - errs, 'warning')}` : 'Yes: no import problems found' }),
        ];
        const ib = checksBlock(imp, [], []);
        if (ib) parts.push(ib);
        parts.push(title('Programming rules'));
        const summary = el('div', { cls: 'sev-summary' });
        [['critical', 'critical', 'critical'], ['error', 'error', 'errors'], ['warning', 'warning', 'warnings'], ['info', 'info', 'info']]
            .forEach(([k, one, many]) => {
            const n = el('span', { cls: `sev-count ${k}${c[k] ? '' : ' zero'}` }, el('b', { text: String(c[k]) }));
            n.appendChild(document.createTextNode(c[k] === 1 ? one : many));
            summary.appendChild(n);
        });
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
                    el('span', { text: ` ${fs[0].title} ` }), el('span', { cls: 'muted', text: String(fs.length) })));
                capped(fs, 100, (f) => el('div', { cls: 'finding' },
                    el('span', { cls: 'finding-where', text: f.location }), el('span', { text: f.message })), det);
                parts.push(det);
            }
        }
        if ((L.not_verified || []).length) {
            const nv = el('details');
            nv.appendChild(el('summary', { text: `${plural(L.not_verified.length, 'rule')} could not be checked from this export` }));
            L.not_verified.forEach((n) => nv.appendChild(el('div', { cls: 'finding', text: n })));
            parts.push(nv);
        }
        (L.errors || []).forEach((n) => parts.push(el('div', { cls: 'err', text: `A rule failed to run: ${n}` })));
        (L.notes || []).forEach((n) => parts.push(el('div', { cls: 'rung-comment', text: n })));
        const extra = [];
        if (L.suppressed.length) extra.push(`${L.suppressed.length} finding(s) accepted with lint:disable`);
        if (L.disabled.length) extra.push(`${L.disabled.length} rule(s) switched off`);
        const row = el('div', { cls: 'btn-row' });
        if (extra.length) row.appendChild(el('span', { cls: 'muted', text: extra.join('; ') }));
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

    udt_created(d) {
        const parts = [];
        if (d.model) {
            parts.push(modelLine(d));
            if (d.attempts.length > 1) parts.push(attemptsBlock(d.attempts));
        }
        parts.push(el('div', { cls: 'status-line', text: `${d.udts.length} UDT${d.udts.length > 1 ? 's' : ''} from ${d.source}` }));
        d.udts.forEach((u) => {
            const head = el('div', { cls: 'udt-head' }, el('span', { cls: 'udt-name', text: u.name }),
                el('span', { cls: 'muted', text: u.size === null ? 'size unknown: it nests a type this file cannot size'
                    : `${u.size} bytes${u.size_as_written > u.size ? `, ${u.size_as_written} in the order given` : ''}` }));
            parts.push(head);
            if (u.description) parts.push(el('div', { cls: 'rung-comment', text: u.description }));
            parts.push(table(['Member', 'Data type', 'Description'], u.members.map((m) => [m.name, m.type, m.description]), [0, 1]));
        });
        (d.warnings || []).forEach((w) => parts.push(el('div', { cls: 'warn', text: w })));
        parts.push(el('div', { cls: 'rung-comment', text: 'Members are in the order that wastes no memory: BOOLs packed together, then by size. In Studio 5000: Data Types, Import Data Type.' }));
        const row = el('div', { cls: 'btn-row' });
        const dl = button(`Download ${d.filename}`, () => (d.l5x ? download(d.filename, d.l5x) : downloadBase64(d.filename, d.zip_b64)));
        dl.classList.add('primary');
        row.appendChild(dl);
        const dur = duration(d.seconds); if (dur) row.appendChild(dur);
        parts.push(row);
        return addBot(...parts);
    },

    udt_plan(d) {
        const parts = [el('div', { cls: 'status-line', text: d.target
            ? `${d.target}${d.plans.length > 1 ? `, with ${plural(d.plans.length - 1, 'nested UDT')}` : ''}`
            : `${plural(d.plans.length, 'UDT')} in ${d.filename}` })];
        if (!d.plans.length) return addBot(el('div', { text: 'This file has no UDTs.' }));
        const reorder = d.plans.filter((p) => p.status === 'reordered');
        const t = el('table', { cls: 'grid udt-plan' });
        const hr = el('tr');
        ['', 'UDT', 'Bytes', 'Saved each', 'Instances', 'Saved total', 'Notes'].forEach((h) => hr.appendChild(el('th', { text: h })));
        t.appendChild(hr);
        const boxes = [];
        d.plans.forEach((p) => {
            const tr = el('tr', { cls: p.status });
            const cb = el('input');
            cb.type = 'checkbox';
            cb.disabled = p.status !== 'reordered';
            cb.checked = !!p.default;
            cb.dataset.name = p.name;
            boxes.push(cb);
            tr.appendChild(el('td', {}, cb));
            tr.appendChild(el('td', { cls: 'mono', text: p.name }));
            tr.appendChild(el('td', { text: p.status === 'skipped' ? '—' : `${p.size_now} → ${p.size_best}` }));
            tr.appendChild(el('td', { text: p.saved ? String(p.saved) : '0' }));
            tr.appendChild(el('td', { text: p.instances === null ? '—' : String(p.instances) }));
            tr.appendChild(el('td', { text: p.total_saved === null || p.total_saved === undefined ? '—' : String(p.total_saved) }));
            const notes = el('td');
            if (p.status === 'skipped') notes.appendChild(el('span', { cls: 'muted', text: `Not changed: ${p.reason}` }));
            else if (p.status === 'optimal') notes.appendChild(el('span', { cls: 'muted', text: p.saved
                ? 'Order already best; smaller once its nested UDTs are reordered' : 'Already in the best order' }));
            if (p.risks.length) notes.appendChild(el('span', { cls: 'code error', text: 'layout risk', title: p.risks.join('\n') }));
            if (p.in_aoi.length) notes.appendChild(el('span', { cls: 'code info', text: 'in AOI', title: `Used inside ${p.in_aoi.join(', ')}` }));
            if (p.status === 'reordered' && !p.saved) notes.appendChild(el('span', { cls: 'muted', text: 'Saves nothing ' }));
            if (p.status === 'reordered') {
                const det = el('details', { cls: 'order' });
                det.appendChild(el('summary', { text: 'Member order' }));
                det.appendChild(el('div', { cls: 'mono small', text: `before: ${p.before.join(', ')}` }));
                det.appendChild(el('div', { cls: 'mono small', text: `after:  ${p.after.join(', ')}` }));
                p.risks.forEach((r) => det.appendChild(el('div', { cls: 'err small', text: r })));
                notes.appendChild(det);
            }
            tr.appendChild(notes);
            t.appendChild(tr);
        });
        parts.push(t);
        parts.push(el('div', { cls: 'rung-comment', text: reorder.length
            ? 'Sizes are estimates from the layout rules: check them in Studio 5000. Reordering moves byte offsets: '
              + 'anything that copies a UDT by offset (COP/CPS, MSG, produced/consumed, an HMI reading the raw block) must be checked. '
              + 'Only UDTs that save bytes and have no layout risk are ticked. A UDT can only change offline.'
            : 'Nothing to reorder: every UDT is already in the best order, or cannot be analysed.' }));
        const notesBox = el('div');
        const sel = () => boxes.filter((b) => b.checked).map((b) => b.dataset.name);
        const row = el('div', { cls: 'btn-row' });
        if (reorder.length) {
            const label = () => (sel().length === 1 ? `Download ${sel()[0]}_opt.L5X` : `Download ${sel().length} UDTs (zip)`);
            const one = button(label(), () => downloadUdt(sel(), sel().length === 1 ? 'single' : 'zip', notesBox));
            one.classList.add('primary');
            row.appendChild(one);
            let full = null;
            if (d.full) {
                full = button('Download whole program (test the import first)', () => downloadUdt(sel(), 'program', notesBox));
                full.classList.add('caution');
                row.appendChild(full);
            }
            const refresh = () => {
                one.textContent = label();
                one.disabled = !sel().length;
                if (full) full.disabled = !sel().length;
            };
            boxes.forEach((b) => b.addEventListener('change', refresh));
            refresh();
        }
        parts.push(row);
        parts.push(notesBox);
        return addBot(...parts);
    },

    xref(d) {
        if (!d.refs.length) return addBot(el('div', { text: `${d.tag} is not used in any rung.` }));
        return addBot(
            el('div', { cls: 'status-line', text: `${d.tag}: ${plural(d.refs.length, 'reference')}` }),
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
    const command = /^\s*(summary|decompile|validate|optimize|xref)\b/i.test(text);
    const english = !command && !/:=|;/.test(text) && !/^\s*\w+\s*\(/.test(text) && !/^\s*(XIC|XIO|SOR|BST)\b/i.test(text);
    const who = settings.backend === 'llamacpp' ? 'the model' : (settings.model || 'the model');
    const wait = loading(english ? `Asking ${who} (can take a minute on a CPU)` : 'Working');
    try {
        const res = await fetch('/api/process', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, settings, mode: command ? 'logic' : mode }),
        });
        wait.remove();
        show(await res.json());
    } catch (e) {
        wait.remove();
        render.error({ message: `Cannot reach the server: ${e.message}. Is 'python app.py' still running?` });
    }
}

function onInput() { enterButton.disabled = !inputBox.value.trim(); grow(); }
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
    $('projectName').textContent = name || '';
    document.querySelectorAll('.project-only').forEach((c) => (c.hidden = !name));
    if (programs && programs.length) {
        settings = loadSettings();
        if (!programs.includes(settings.program)) { settings.program = preferred || programs[0]; saveSettings(settings); }
    }
}

async function upload(file) {
    addUser(`Attached ${file.name}`);
    const excel = /\.xls[xm]$/i.test(file.name);
    const wait = loading(excel ? 'Reading the UDT sheet' : 'Reading the L5X');
    const fd = new FormData();
    fd.append('file', file);
    fd.append('settings', JSON.stringify(loadSettings()));
    try {
        const res = await fetch('/api/project', { method: 'POST', body: fd });
        wait.remove();
        if (res.status === 413) return render.error({ message: 'The file is larger than the 50 MB limit.' });
        const d = await res.json();
        if (excel && d.kind === 'udt_created') setMode('udt');
        show(d);
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
    intro();
})();

// ---------------------------------------------------------------- first screen
const EXAMPLE = {
    said: 'Start the pump with the start button and keep it running until the stop button is pressed or the pump faults.',
    text: '[XIC(Start_PB) ,XIC(Pump_Run) ]XIO(Stop_PB)XIO(Pump_Fault)OTE(Pump_Run);',
};
async function intro() {
    const box = el('section', { cls: 'intro' });
    box.appendChild(el('h1', { text: 'Ladder logic from plain English, checked before it reaches Studio 5000' }));
    box.appendChild(el('p', { text: 'Describe what a rung should do, or paste rungs to read them. A model on this PC writes the logic; '
        + 'fixed code draws it, checks it against your project and writes the L5X.' }));
    const ex = el('div', { cls: 'example' });
    ex.appendChild(el('div', { cls: 'said', text: EXAMPLE.said }));
    const [svg] = await ladders([{ text: EXAMPLE.text, number: 0 }]);
    if (svg) ex.appendChild(drawing(svg));
    box.appendChild(ex);
    const row = el('div', { cls: 'btn-row' });
    const tryIt = button('Try this example', () => { setMode('logic'); inputBox.value = EXAMPLE.said; onInput(); inputBox.focus(); });
    tryIt.classList.add('primary');
    row.appendChild(tryIt);
    row.appendChild(button('Attach an L5X', () => $('fileInput').click()));
    row.appendChild(button('Create a UDT', () => { setMode('udt'); inputBox.focus(); }));
    row.appendChild(button('What else it does', openHelp));
    box.appendChild(row);
    chatWindow.prepend(box);
}

// the input grows with its text, up to its max-height
function grow() { inputBox.style.height = 'auto'; inputBox.style.height = `${inputBox.scrollHeight}px`; }
inputBox.addEventListener('input', grow);
