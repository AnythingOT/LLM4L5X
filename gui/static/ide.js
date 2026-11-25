// The chat view's workbench: explorer (the attached file as a tree), editor tabs, the panel (problems,
// output, test results) and the resizable panes. app.js puts results into tabs through openTab().
// All text goes in with textContent; only ladder SVG made by the server is inserted as markup.
'use strict';

// ---------------------------------------------------------------- layout: pane sizes, remembered
const LAYOUT_KEY = 'llm4l5x.layout';
const ide = $('ide');
const layout = Object.assign({ explorer: 250, chat: 360, panel: 170, panelCollapsed: false, panelTab: 'problems' },
    store.get(LAYOUT_KEY, {}));
function applyLayout() {
    ide.style.setProperty('--explorer-w', `${layout.explorer}px`);
    ide.style.setProperty('--chat-w', `${layout.chat}px`);
    ide.style.setProperty('--panel-h', `${layout.panel}px`);
    $('panel').classList.toggle('collapsed', layout.panelCollapsed);
}
applyLayout();
document.querySelectorAll('.gutter[data-resize]').forEach((g) => {
    g.addEventListener('pointerdown', (e) => {
        e.preventDefault();
        g.setPointerCapture(e.pointerId);
        g.classList.add('dragging');
        const which = g.dataset.resize;
        const start = { x: e.clientX, y: e.clientY, v: layout[which] };
        const move = (ev) => {
            if (which === 'explorer') layout.explorer = Math.min(480, Math.max(170, start.v + ev.clientX - start.x));
            if (which === 'chat') layout.chat = Math.min(680, Math.max(280, start.v - (ev.clientX - start.x)));
            if (which === 'panel') {
                layout.panelCollapsed = false;
                layout.panel = Math.min(window.innerHeight * 0.7, Math.max(80, start.v - (ev.clientY - start.y)));
            }
            applyLayout();
        };
        const up = () => {
            g.classList.remove('dragging');
            g.removeEventListener('pointermove', move);
            store.set(LAYOUT_KEY, layout);
        };
        g.addEventListener('pointermove', move);
        g.addEventListener('pointerup', up, { once: true });
    });
});

// ---------------------------------------------------------------- editor tabs
// A tab is a document in the editor. Results get a new tab each; an item from the explorer (a routine, a UDT)
// has a key, so opening it again shows its tab. Explorer tabs are reopened after a reload.
const TABS_KEY = 'llm4l5x.tabs';
const tabsBar = $('tabs');
const tabBody = $('tabBody');
const tabs = new Map();  // id -> {btn, doc, item}
let tabSeq = 0;
let activeId = null;
const savedTabs = (() => { try { return JSON.parse(sessionStorage.getItem(TABS_KEY)) || []; } catch { return []; } })();
const restoredTabs = savedTabs.length > 0;

function saveTabs() {
    const items = [...tabs.values()].filter((t) => t.item).map((t) => t.item);
    try { sessionStorage.setItem(TABS_KEY, JSON.stringify(items)); } catch { /* storage unavailable */ }
}

function openTab(key, title, kind, build, opts = {}) {
    if (key && tabs.has(key)) {
        activateTab(key);
        return tabs.get(key).doc;
    }
    const id = key || `t${++tabSeq}`;
    const doc = el('div', { cls: 'doc' });
    doc.dataset.tab = id;
    doc.setAttribute('role', 'tabpanel');
    const close = el('span', { cls: 'tx', text: '×', title: 'Close' });
    const btn = el('button', { cls: 'tab', title }, kind ? el('span', { cls: 'tk', text: kind }) : null,
        el('span', { cls: 'tt', text: title }), close);
    btn.setAttribute('role', 'tab');
    btn.onclick = (e) => (e.target === close ? closeTab(id) : activateTab(id));
    btn.onauxclick = (e) => { if (e.button === 1) closeTab(id); };
    tabsBar.appendChild(btn);
    tabBody.appendChild(doc);
    tabs.set(id, { btn, doc, item: opts.item || null });
    if (build) build(doc);
    if (opts.keep !== false) activateTab(id);
    else if (!activeId) activateTab(id);
    saveTabs();
    return doc;
}

function activateTab(id) {
    const t = tabs.get(id);
    if (!t) return;
    activeId = id;
    for (const [k, x] of tabs) {
        x.btn.classList.toggle('active', k === id);
        x.btn.setAttribute('aria-selected', String(k === id));
        x.doc.hidden = k !== id;
    }
    t.btn.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    tabBody.scrollTop = 0;
}

function closeTab(id) {
    const t = tabs.get(id);
    if (!t) return;
    const order = [...tabs.keys()];
    t.btn.remove();
    t.doc.remove();
    tabs.delete(id);
    saveTabs();
    if (activeId === id) {
        const next = order[order.indexOf(id) + 1] || order[order.indexOf(id) - 1];
        activeId = null;
        if (next && tabs.has(next)) activateTab(next);
    }
}

function closeItemTabs() {
    for (const [id, t] of [...tabs]) if (t.item) closeTab(id);
}

// ---------------------------------------------------------------- panel: problems, output, test results
document.querySelectorAll('.ptab').forEach((b) => (b.onclick = () => showPanel(b.dataset.panel)));
function showPanel(name) {
    layout.panelTab = name;
    layout.panelCollapsed = false;
    applyLayout();
    store.set(LAYOUT_KEY, layout);
    document.querySelectorAll('.ptab').forEach((b) => b.classList.toggle('active', b.dataset.panel === name));
    for (const n of ['problems', 'output', 'tests']) $(`panel-${n}`).hidden = n !== name;
    if (name === 'tests') loadTestResults();
}
$('panelToggle').onclick = () => {
    layout.panelCollapsed = !layout.panelCollapsed;
    applyLayout();
    store.set(LAYOUT_KEY, layout);
};

function log(text) {
    const box = $('panel-output');
    const t = new Date();
    box.appendChild(el('div', { cls: 'outline' }, el('time', { text: t.toLocaleTimeString() }), document.createTextNode(text)));
    while (box.childNodes.length > 300) box.firstChild.remove();
    box.scrollTop = box.scrollHeight;
}

// Problems come from the last result that has checks: import checks and rule findings, one list.
function problemsFrom(d) {
    let items = null;
    if (['generated', 'compiled', 'rungs'].includes(d.kind)) {
        items = (d.issues || []).map((i) => ({ sev: i.level, code: i.level === 'error' ? 'import' : 'warning', text: i.message, where: i.where ?? `Rung ${i.rung}` }))
            .concat((d.lint || []).map((f) => ({ sev: f.severity, code: f.code, text: f.message, where: f.location })));
    } else if (d.kind === 'validated') {
        items = (d.import || []).map((i) => ({ sev: i.level, code: 'import', text: i.message, where: i.where }))
            .concat(d.lint.findings.map((f) => ({ sev: f.severity, code: f.code, text: f.message, where: f.location })));
    }
    if (items) setProblems(items);
}
function setProblems(items) {
    const box = $('panel-problems');
    box.replaceChildren();
    const order = { critical: 0, error: 1, warning: 2, info: 3 };
    items.sort((a, b) => (order[a.sev] ?? 4) - (order[b.sev] ?? 4));
    $('problemCount').textContent = items.length ? String(items.length) : '';
    if (!items.length) { box.appendChild(el('div', { cls: 'panel-empty', text: 'No problems in the last result.' })); return; }
    items.slice(0, 500).forEach((p) => {
        const row = el('button', { cls: 'prob' }, el('span', { cls: `code ${p.sev === 'error' || p.sev === 'critical' ? p.sev : p.sev === 'warning' ? 'warning' : 'info'}`, text: p.code }),
            el('span', { text: p.text }), el('span', { cls: 'where', text: p.where || '' }));
        row.onclick = () => openLocation(p.where || '');
        box.appendChild(row);
    });
    if (items.some((p) => p.sev === 'error' || p.sev === 'critical') && layout.panelTab !== 'problems') showPanel('problems');
}
// "MainProgram / Pump / Rung 3", "MainProgram/Pump rung 3": open that routine and show the rung
function openLocation(where) {
    const m = where.match(/([\w:]+)\s*\/\s*(\w+)\s*(?:\/\s*)?[Rr]ung\s*(\d+)/);
    if (m && tree && tree.attached) openRoutine(m[1], m[2], Number(m[3]));
}

async function loadTestResults() {
    const box = $('panel-tests');
    try {
        const s = await (await fetch('/api/status')).json();
        const r = s.last_run;
        box.replaceChildren();
        if (!r) { box.appendChild(el('div', { cls: 'panel-empty', text: 'No test run yet: run the test cases on the Tests view.' })); return; }
        const ok = r.summary.passed === r.summary.test_cases;
        box.appendChild(el('div', { cls: 'outline' }, el('span', { cls: ok ? 'ok' : 'err', text: `${r.summary.passed} of ${r.summary.test_cases} test cases pass` }),
            document.createTextNode(`  ·  run ${r.id}  ·  ${(r.program || []).join(', ')}`)));
        const links = el('div', { cls: 'outline' });
        const pdf = el('a', { text: 'Report (PDF)' }); pdf.href = `/api/tests/runs/${encodeURIComponent(r.id)}/report.pdf`;
        const all = el('a', { text: 'All runs on the Tests view' }); all.href = '/tests';
        links.append(pdf, document.createTextNode('   '), all);
        box.appendChild(links);
    } catch { /* server restarting */ }
}

// ---------------------------------------------------------------- explorer
const OPEN_KEY = 'llm4l5x.tree.open';
let tree = null;
const opened = new Set((() => { try { return JSON.parse(sessionStorage.getItem(OPEN_KEY)) || ['ctrl', 'programs']; } catch { return ['ctrl', 'programs']; } })());
let selectedRow = null;

async function loadTree() {
    try { tree = await (await fetch('/api/project/tree')).json(); } catch { tree = { attached: false }; }
    drawTree();
}

function drawTree() {
    const box = $('tree');
    box.replaceChildren();
    if (!tree || !tree.attached) {
        const empty = el('div', { cls: 'tree-empty' }, el('span', { text: 'No file attached. Attach an L5X export to see its controller, routines, tags, UDTs, AOIs and I/O here.' }));
        const b = button('Attach an L5X', () => $('fileInput').click());
        empty.appendChild(b);
        box.appendChild(empty);
        return;
    }
    const t = tree;
    // a small project opens with its programs unfolded; a large one with the groups only
    if (![...opened].some((k) => k.startsWith('prog:')) && t.programs.length <= 3) t.programs.forEach((p) => opened.add(`prog:${p.name}`));
    const rows = [];
    const group = (id, label, depth, count, children) => {
        const open = opened.has(id);
        rows.push(row({ depth, label, count, group: true, open, onclick: () => toggle(id) }));
        if (open) children();
    };
    const leaf = (depth, label, onclick, extra) => rows.push(row({ depth, label, onclick, ...extra }));
    group('ctrl', `Controller ${t.controller || ''}`.trim(), 0, null, () => {
        leaf(1, 'Summary', () => openSummary(), { note: t.processor || '' });
        group('tasks', 'Tasks', 1, t.tasks.length, () => t.tasks.forEach((k) => {
            group(`task:${k.name}`, k.name, 2, k.type === 'PERIODIC' && k.period ? `${k.period} ms` : k.type.toLowerCase(), () => k.programs.forEach((p) => leaf(3, p, () => { opened.add('programs'); opened.add(`prog:${p}`); saveOpen(); drawTree(); })));
        }));
        leaf(1, 'Controller tags', () => openItem('tags', ''), { count: t.tags.controller });
    });
    group('programs', 'Programs', 0, t.programs.length, () => t.programs.forEach((p) => {
        group(`prog:${p.name}`, p.name, 1, null, () => {
            if (t.tags.programs[p.name]) leaf(2, 'Program tags', () => openItem('tags', p.name), { count: t.tags.programs[p.name] });
            p.routines.forEach((r) => leaf(2, r.name, () => openRoutine(p.name, r.name), {
                count: r.type === 'RLL' ? r.rungs : r.type, main: r.name === p.main, mono: true, key: `routine:${p.name}/${r.name}` }));
        });
    }));
    group('udts', 'UDTs', 0, t.udts.length, () => t.udts.forEach((u) => leaf(1, u, () => openItem('udt', u), { mono: true, key: `udt:${u}` })));
    group('aois', 'AOIs', 0, t.aois.length, () => t.aois.forEach((a) => leaf(1, a, () => openItem('aoi', a), { mono: true, key: `aoi:${a}` })));
    group('io', 'I/O tree', 0, t.modules.length, () => {
        const kids = new Map();
        t.modules.forEach((m) => { const k = m.parent && m.parent !== m.name ? m.parent : ''; if (!kids.has(k)) kids.set(k, []); kids.get(k).push(m); });
        const walk = (parent, depth) => (kids.get(parent) || []).forEach((m) => {
            const label = `${m.slot !== null && m.slot !== undefined ? `[${m.slot}] ` : ''}${m.name}`;
            if (kids.has(m.name)) group(`mod:${m.name}`, label, depth, m.catalog, () => { leaf(depth + 1, 'Properties', () => openItem('module', m.name)); walk(m.name, depth + 1); });
            else leaf(depth, label, () => openItem('module', m.name), { note: m.catalog, mono: true, key: `module:${m.name}` });
        });
        walk('', 1);
    });
    rows.forEach((r) => box.appendChild(r));
}
function row({ depth, label, count, note, group, open, onclick, main, mono, key }) {
    const r = el('button', { cls: `tree-row ${group ? 'group' : 'leaf'}${mono ? '' : ' plain'}` },
        el('span', { cls: 'tw', text: group ? (open ? '▾' : '▸') : '' }), el('span', { cls: 'tl', text: label }),
        main ? el('span', { cls: 'main', text: 'main', title: 'The main routine of this program' }) : null,
        (count !== null && count !== undefined && count !== '') || note ? el('span', { cls: 'tn', text: String(count ?? note) }) : null);
    r.style.setProperty('--depth', depth);
    r.setAttribute('role', 'treeitem');
    if (group) r.setAttribute('aria-expanded', String(!!open));
    if (key && tabs.has(key)) r.classList.add('selected');
    r.onclick = () => {
        if (!group) { if (selectedRow) selectedRow.classList.remove('selected'); r.classList.add('selected'); selectedRow = r; }
        onclick();
    };
    return r;
}
function toggle(id) { if (opened.has(id)) opened.delete(id); else opened.add(id); saveOpen(); drawTree(); }
function saveOpen() { try { sessionStorage.setItem(OPEN_KEY, JSON.stringify([...opened])); } catch { /* storage unavailable */ } }

// ---------------------------------------------------------------- explorer items in the editor
async function getJSON(url) {
    const res = await fetch(url);
    const d = await res.json();
    if (!res.ok) throw new Error(d.message || `${res.status}`);
    return d;
}

async function openRoutine(program, name, rung) {
    const key = `routine:${program}/${name}`;
    const show = (doc) => {
        if (rung === undefined) return;
        const b = doc.querySelector(`[data-rung="${rung}"]`);
        if (b) { b.scrollIntoView({ block: 'center' }); b.classList.remove('flash'); void b.offsetWidth; b.classList.add('flash'); }
    };
    if (tabs.has(key)) { activateTab(key); show(tabs.get(key).doc); return; }
    let d;
    try { d = await getJSON(`/api/project/routine?program=${encodeURIComponent(program)}&name=${encodeURIComponent(name)}`); }
    catch (e) { log(`Could not open ${program} / ${name}: ${e.message}`); return; }
    const doc = openTab(key, name, 'Routine', (doc) => {
        doc.appendChild(el('div', { cls: 'doc-head' }, el('h2', { text: name }), el('span', { cls: 'doc-path', text: `${program} · ${n_(d.rows.length, 'rung')}` })));
        if (!d.rows.length) doc.appendChild(el('div', { cls: 'muted', text: 'Not a ladder routine, or no rungs: nothing to show here.' }));
    }, { item: { type: 'routine', program, name } });
    await rungBlocks(doc, d.rows);
    drawTree();
    show(doc);
}

// a routine's rungs, as Studio 5000 puts words above the rung: its comment, what it does, then the ladder
async function rungBlocks(doc, rows) {
    const PAGE = 40;
    let shown = 0;
    const more = el('button', { cls: 'show-more' });
    doc.appendChild(more);
    async function next() {
        const page = rows.slice(shown, shown + PAGE);
        shown += page.length;
        const svgs = await ladders(page.map((r) => ({ text: r.text, number: r.number })));
        page.forEach((r, i) => {
            const b = el('div', { cls: 'rung-block' });
            b.dataset.rung = r.number;
            if (r.comment) b.appendChild(el('div', { cls: 'own-comment', text: r.comment }));
            b.appendChild(r.english
                ? el('div', { cls: 'rung-comment explained' }, el('span', { cls: 'explained-label', text: r.comment ? 'What it does' : 'Generated' }), el('span', { text: r.english.join(' ') }))
                : el('div', { cls: 'warn small', text: `Not explained: ${r.why}` }));
            b.appendChild(svgs[i] ? drawing(svgs[i]) : code(r.text));
            doc.insertBefore(b, more);
        });
        more.textContent = `Show the next ${Math.min(PAGE, rows.length - shown)} of ${rows.length - shown} rungs`;
        more.hidden = shown >= rows.length;
    }
    more.onclick = next;
    await next();
}

async function openItem(kind, name) {
    const key = `${kind}:${name}`;
    if (tabs.has(key)) { activateTab(key); return; }
    let d;
    try { d = await getJSON(`/api/project/item?kind=${kind}&name=${encodeURIComponent(name)}`); }
    catch (e) { log(`Could not open ${name}: ${e.message}`); return; }
    const title = kind === 'tags' ? `${d.scope} tags` : name;
    const label = { udt: 'UDT', aoi: 'AOI', module: 'Module', tags: 'Tags' }[kind];
    const doc = openTab(key, title, label, (doc) => {
        doc.appendChild(el('div', { cls: 'doc-head' }, el('h2', { text: title }),
            el('span', { cls: 'doc-path', text: kind === 'module' ? d.catalog : kind === 'tags' ? n_(d.tags.length, 'tag') : '' })));
        if (d.description) doc.appendChild(el('div', { cls: 'rung-comment', text: d.description }));
        if (kind === 'udt') {
            doc.appendChild(table(['Member', 'Data type', 'Description'], d.members.map((m) => [m.name, m.type + (m.dimension ? `[${m.dimension}]` : ''), m.description]), [0, 1]));
            const row = el('div', { cls: 'btn-row' });
            row.appendChild(button('Optimize the UDTs of this file', () => send('optimize')));
            doc.appendChild(row);
        }
        if (kind === 'aoi') {
            if (d.protected) { doc.appendChild(el('div', { cls: 'warn', text: 'Source-protected: its parameters and logic cannot be read.' })); return; }
            doc.appendChild(title_('Parameters', d.params.length));
            doc.appendChild(table(['Parameter', 'Data type', 'Usage', 'Required', 'Description'], d.params.map((p) => [p.name, p.type, p.usage, p.required ? 'yes' : '', p.description]), [0, 1]));
            if (d.locals.length) {
                doc.appendChild(title_('Local tags', d.locals.length));
                doc.appendChild(table(['Tag', 'Data type'], d.locals.map((t) => [t.name, t.type]), [0, 1]));
            }
            doc.appendChild(title_('Logic', d.rows.length));
        }
        if (kind === 'module') {
            doc.appendChild(table(['', ''], [['Catalog', d.catalog], ['Parent', d.parent], ['Slot', d.slot], ['Port', d.port], ['Electronic keying', d.ekey]], [1]));
            if (d.io.length) doc.appendChild(table(['I/O tag', 'Kind', 'Point comments'], d.io.map((x) => [x.tag, x.kind, String(x.comments)]), [0]));
        }
        if (kind === 'tags') {
            const filter = el('input');
            filter.type = 'search';
            filter.placeholder = 'Filter';
            filter.className = 'tag-filter';
            filter.setAttribute('aria-label', 'Filter tags');
            const holder = el('div');
            const draw = () => {
                const q = filter.value.trim().toLowerCase();
                const rows = d.tags.filter((t) => !q || t.name.toLowerCase().includes(q) || (t.description || '').toLowerCase().includes(q));
                holder.replaceChildren(table(['Tag', 'Data type', 'Alias for', 'Description'],
                    rows.slice(0, 500).map((t) => [t.name + (t.dims ? `[${t.dims}]` : ''), t.type, t.alias, t.description]), [0, 1]));
                if (rows.length > 500) holder.appendChild(el('div', { cls: 'muted', text: `${rows.length - 500} more: filter to find them` }));
            };
            filter.oninput = draw;
            doc.append(filter, holder);
            draw();
        }
    }, { item: { type: 'item', kind, name } });
    if (kind === 'aoi' && d.rows && d.rows.length) await rungBlocks(doc, d.rows);
    drawTree();
}
function title_(text, count) { return title(text, count); }

async function openSummary() {
    if (tabs.has('summary')) { activateTab('summary'); return; }
    const res = await fetch('/api/process', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: 'summary', settings: loadSettings() }),
    });
    const d = await res.json();
    if (d.kind !== 'project') return;
    route = { title: d.filename, kind: 'Summary', summary: '', key: 'summary', quiet: true };
    try { render.project(d); } finally { route = null; }
}

// reopen the explorer's tabs from before a reload, once the file is known to be attached
async function restoreTabs() {
    if (!tree || !tree.attached) return;
    for (const t of savedTabs) {
        if (t.type === 'routine') await openRoutine(t.program, t.name);
        else if (t.type === 'item') await openItem(t.kind, t.name);
    }
}

// below 1100 px the explorer folds away: this button in the tab bar brings it back
const explorerToggle = el('button', { cls: 'pane-btn explorer-toggle', title: 'Show or hide the explorer' });
explorerToggle.setAttribute('aria-label', 'Show or hide the explorer');
explorerToggle.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16"/></svg>';
explorerToggle.onclick = () => ide.classList.toggle('show-explorer');
tabsBar.prepend(explorerToggle);
$('explorerAttach').onclick = () => $('fileInput').click();
