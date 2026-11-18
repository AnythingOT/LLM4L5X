// Settings page: every change is saved at once.
'use strict';

let settings = loadSettings();
const fields = {
    backend: 'setBackend', llm_url: 'setLlmUrl', think: 'setThink',
    rung_format: 'setRungFormat', output: 'setOutput', routine: 'setRoutine', program: 'setProgram',
    controller: 'setController', revision: 'setRevision', scope: 'setScope',
    display: 'setDisplay', prefix: 'setPrefix', comments: 'setComments',
};

function fill() {
    for (const [k, id] of Object.entries(fields)) {
        const e = $(id);
        if (e.type === 'checkbox') e.checked = !!settings[k]; else e.value = settings[k];
    }
    updateBackendUi();
}
function save() {
    for (const [k, id] of Object.entries(fields)) {
        const e = $(id);
        settings[k] = e.type === 'checkbox' ? e.checked : e.value.trim();
    }
    if (!settings.routine) settings.routine = DEFAULTS.routine;
    if (!settings.prefix) settings.prefix = DEFAULTS.prefix;
    saveSettings(settings);
    flashSaved();
}
for (const id of Object.values(fields)) $(id).addEventListener('change', save);

function updateBackendUi() {
    const info = BACKEND_INFO[$('setBackend').value];
    $('backendHelp').textContent = info.help;
    $('setLlmUrl').placeholder = info.url;
}
$('setBackend').addEventListener('change', () => {
    // a default address of another backend would be wrong here
    const url = $('setLlmUrl').value.trim();
    if (Object.values(BACKEND_INFO).some((i) => i.url === url)) { $('setLlmUrl').value = ''; save(); }
    updateBackendUi();
    refreshModels();
});
$('setLlmUrl').addEventListener('change', () => refreshModels());
$('refreshModels').onclick = () => refreshModels();

function showCustom(on) {
    document.querySelectorAll('.custom-row').forEach((e) => (e.hidden = !on));
}
$('setModelSelect').onchange = () => {
    const v = $('setModelSelect').value;
    showCustom(v === '__custom__');
    if (v === '__custom__') { $('setModelCustom').value = settings.model; $('setModelCustom').focus(); return; }
    settings.model = v; saveSettings(settings); flashSaved();
};
$('setModelCustom').onchange = () => {
    settings.model = $('setModelCustom').value.trim(); saveSettings(settings); flashSaved();
};

async function refreshModels() {
    const status = $('modelStatus');
    status.className = 'help full';
    status.textContent = 'Checking…';
    let d;
    try { d = await fetchModels(settings); } catch (e) { d = { ok: false, models: [], error: e.message }; }
    const sel = $('setModelSelect');
    let current = settings.model;
    if (current && !current.includes(':') && d.models.includes(`${current}:latest`)) current = `${current}:latest`;
    const opts = d.models.map((m) => { const o = el('option', { text: m }); o.value = m; return o; });
    if (current && !d.models.includes(current) && settings.backend !== 'llamacpp') {
        const o = el('option', { text: `${current} (not found)` }); o.value = current; opts.unshift(o);
    }
    const other = el('option', { text: 'Other (type a name)…' }); other.value = '__custom__'; opts.push(other);
    sel.replaceChildren(...opts);
    if (d.models.includes(current) || (current && settings.backend !== 'llamacpp')) sel.value = current;
    else if (d.models.length) sel.value = d.models[0];
    if (sel.value !== '__custom__' && sel.value !== settings.model) { settings.model = sel.value; saveSettings(settings); }
    showCustom(false);
    if (d.ok) {
        status.className = 'help full ok';
        status.textContent = `● Connected to ${d.backend} at ${d.url}: ${d.models.length} model${d.models.length === 1 ? '' : 's'}`
            + (d.grammar ? ' · answers are grammar-constrained' : '');
    } else {
        status.className = 'help full bad';
        status.textContent = `○ ${d.error}`;
    }
}

$('resetSettings').onclick = () => {
    const keepRules = settings.disabled_rules;  // the Rules page has its own reset
    settings = Object.assign({}, DEFAULTS, { disabled_rules: keepRules });
    saveSettings(settings);
    fill();
    refreshModels();
    flashSaved();
};

(async () => {
    fill();
    try {
        const s = await (await fetch('/api/status')).json();
        $('programList').replaceChildren(...(s.programs || []).map((p) => { const o = el('option'); o.value = p; return o; }));
    } catch { /* server not ready */ }
    refreshModels();
})();
