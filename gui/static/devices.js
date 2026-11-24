// Devices page: the device models, kept on the server with the program Energize runs.
// All text goes in with textContent: tag names come from files.
'use strict';

const DEV_DRAFT = 'llm4l5x.devices.draft';  // typed but not saved, kept if the page is left
let savedDevices = '';

function dvMsg(text, bad) {
    $('dvMsg').textContent = text;
    $('dvMsg').classList.toggle('err', !!bad);
}

function cell(text, cls) {
    const td = document.createElement('td');
    td.textContent = text;
    if (cls) td.className = cls;
    return td;
}

function showList(list) {
    $('dvList').replaceChildren(...list.map((d) => {
        const tr = document.createElement('tr');
        const time = Object.entries(d.timing).map(([k, v]) => `${k.replace(/_ms$/, '').replace('_', ' ')} ${v} ms`);
        const name = cell(`${d.name} `, 'ts-id');
        const kind = document.createElement('span');
        kind.className = 'muted';
        kind.textContent = d.kind;
        name.append(kind);
        tr.append(name, cell(d.reads.join(', ') || '-', 'ts-reqs'), cell(d.answers.join(', ') || '-', 'ts-reqs'),
            cell(time.join(', ') || '-'));
        return tr;
    }));
    $('dvEmpty').hidden = list.length > 0;
}

$('dvSave').onclick = async () => {
    try {
        const r = await fetch('/api/devices/save', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ devices: $('dvText').value }),
        });
        const j = await r.json();
        if (!r.ok || j.error) throw new Error(j.error || `HTTP ${r.status}`);
        savedDevices = $('dvText').value;
        store.set(DEV_DRAFT, null);
        showList(j.device_list);
        dvMsg(`Saved: ${j.devices} device model${j.devices === 1 ? '' : 's'}`
            + (j.loaded ? '; the loaded program answers with them now.' : '.'));
    } catch (e) { dvMsg(e.message, true); }
};

$('dvText').addEventListener('input', () => store.set(DEV_DRAFT, $('dvText').value));

(async () => {
    try {
        const j = await (await fetch('/api/energize/state')).json();
        savedDevices = j.device_text || '';
        $('dvProgram').textContent = j.loaded ? `${(j.names || []).join(', ')}: ${j.rungs.length} rungs`
            : 'No program loaded (load one on Energize or Tests)';
        showList(j.device_list || []);
    } catch { /* server not ready */ }
    const draft = store.get(DEV_DRAFT, null);
    $('dvText').value = typeof draft === 'string' ? draft : savedDevices;
    if (typeof draft === 'string' && draft !== savedDevices) dvMsg('Not saved yet: the text from before you left the page.');
})();
