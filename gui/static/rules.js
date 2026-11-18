// Rules page: switch validation rules on and off (stored with the settings).
'use strict';

let settings = loadSettings();
let rules = [];
let sevFilter = '';

function disabled() { return new Set(settings.disabled_rules); }
function setDisabled(set) {
    settings.disabled_rules = [...set].sort();
    saveSettings(settings);
    flashSaved();
    updateCount();
}
function updateCount() {
    const off = rules.filter((r) => disabled().has(r.code)).length;
    $('ruleCount').textContent = `${rules.length - off} of ${rules.length} rules on.`;
}

function ruleRow(r) {
    const row = el('label', { cls: 'rule-row' });
    const sw = el('input');
    sw.type = 'checkbox';
    sw.className = 'switch';
    sw.checked = !disabled().has(r.code);
    sw.onchange = () => {
        const d = disabled();
        if (sw.checked) d.delete(r.code); else d.add(r.code);
        row.classList.toggle('off', !sw.checked);
        setDisabled(d);
    };
    row.classList.toggle('off', !sw.checked);
    row.appendChild(sw);
    row.appendChild(el('span', { cls: `code ${r.severity}`, text: r.code }));
    const body = el('span', { cls: 'rule-body' },
        el('span', { cls: 'rule-title', text: r.title }),
        el('span', { cls: `badge ${r.scope}`, text: r.scope, title: r.scope === 'rung'
            ? 'Also checks new and pasted rungs' : 'Needs a full controller export' }),
        el('span', { cls: 'rule-desc', text: r.description }));
    row.appendChild(body);
    return row;
}

function draw() {
    const q = $('ruleSearch').value.trim().toLowerCase();
    const shown = rules.filter((r) => (!sevFilter || r.severity === sevFilter)
        && (!q || `${r.code} ${r.title} ${r.description}`.toLowerCase().includes(q)));
    const groups = new Map();
    shown.forEach((r) => { if (!groups.has(r.group)) groups.set(r.group, []); groups.get(r.group).push(r); });
    const out = [];
    for (const [g, list] of groups) {
        const sec = el('section', { cls: 'card rule-group' });
        const head = el('div', { cls: 'rule-group-head' }, el('h2', { text: g }), el('span', { cls: 'muted', text: `${list.length}` }));
        const onBtn = el('button', { cls: 'btn small', text: 'On' });
        const offBtn = el('button', { cls: 'btn small', text: 'Off' });
        onBtn.onclick = () => { const d = disabled(); list.forEach((r) => d.delete(r.code)); setDisabled(d); draw(); };
        offBtn.onclick = () => { const d = disabled(); list.forEach((r) => d.add(r.code)); setDisabled(d); draw(); };
        head.appendChild(el('span', { cls: 'group-btns' }, onBtn, offBtn));
        sec.appendChild(head);
        list.forEach((r) => sec.appendChild(ruleRow(r)));
        out.push(sec);
    }
    if (!out.length) out.push(el('p', { cls: 'muted', text: 'No rule matches.' }));
    $('ruleGroups').replaceChildren(...out);
}

$('ruleSearch').oninput = draw;
document.querySelectorAll('.sev-btn').forEach((b) => {
    b.onclick = () => {
        sevFilter = b.dataset.sev;
        document.querySelectorAll('.sev-btn').forEach((x) => x.classList.toggle('active', x === b));
        draw();
    };
});
$('enableAll').onclick = () => { setDisabled(new Set()); draw(); };
$('disableAll').onclick = () => { setDisabled(new Set(rules.map((r) => r.code))); draw(); };

(async () => {
    try {
        rules = (await (await fetch('/api/rules')).json()).rules;
    } catch (e) {
        $('ruleGroups').replaceChildren(el('p', { cls: 'err', text: `Cannot load the rules: ${e.message}` }));
        return;
    }
    updateCount();
    draw();
})();
