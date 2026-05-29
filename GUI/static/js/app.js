// State Management
const state = {
    currentStep: 1,
    assetInfo: {},
    submodels: ['OperationalData'],
    activeSM: 'OperationalData',
    submodelConfigs: {},   // { smName: { protocol, protocolData: { modbus: {source,targetData}, mqtt: {...}, ... } } }
    deploymentMode: 'custom',
    globalSinks: {}        // Shared sink config (shown in Deploy page for Custom mode)
};

// Navigation
function nextStep(step) {
    showStep(step);
}

function prevStep(step) {
    showStep(step);
}

function showStep(stepNumber) {
    // Auto-save current step before leaving
    if (state.currentStep === 1) {
        state.assetInfo = {
            name: document.getElementById('assetName')?.value || '',
            id: document.getElementById('assetId')?.value || '',
            desc: document.getElementById('assetDesc')?.value || ''
        };
    }
    if (state.currentStep === 3) savePropConfig();
    if (state.currentStep === 4) state.globalSinks = collectPropSinkConfig();
    saveToStorage();

    document.querySelectorAll('.view-section').forEach(el => {
        el.style.display = 'none';
        el.classList.remove('fade-in');
    });

    const target = document.getElementById(`view-step-${stepNumber}`);
    if (target) {
        target.style.display = 'block';
        target.classList.add('fade-in');
    }

    document.querySelectorAll('.nav-tab').forEach(el => {
        el.classList.remove('active');
        if (el.dataset.step == stepNumber) el.classList.add('active');
    });

    state.currentStep = stepNumber;

    // Restore data when entering a step
    if (stepNumber === 1) {
        if (state.assetInfo.name) document.getElementById('assetName').value = state.assetInfo.name;
        if (state.assetInfo.id) document.getElementById('assetId').value = state.assetInfo.id;
        if (state.assetInfo.desc) document.getElementById('assetDesc').value = state.assetInfo.desc;
    }
    if (stepNumber === 2) renderSubmodels();
    if (stepNumber === 3) {
        renderSubmodelTabs();
        loadSubmodelConfig(state.activeSM);
    }
    if (stepNumber === 4) {
        const wrapper = document.getElementById('deploy-sink-wrapper');
        if (wrapper) renderPropSinkConfig(state.globalSinks);
    }
}

// Logic: Submodels
function addNewSubmodel() {
    const input = document.getElementById('newSubmodelName');
    const name = input.value.trim();
    if (name) {
        if (!state.submodels.includes(name)) {
            state.submodels.push(name);
            input.value = '';
            renderSubmodels();
            saveToStorage();
        }
    }
}

function quickAddSubmodel(name) {
    if (!state.submodels.includes(name)) {
        state.submodels.push(name);
        renderSubmodels();
        saveToStorage();
    }
}

function removeSubmodel(name) {
    state.submodels = state.submodels.filter(s => s !== name);
    state.properties = state.properties.filter(p => p.parentSM !== name);
    if (state.activeSM === name) state.activeSM = state.submodels[0] || '';
    renderSubmodels();
    saveToStorage();
}

function renderSubmodels() {
    const container = document.getElementById('submodel-list');
    if (!container) return;
    container.innerHTML = '';
    state.submodels.forEach(s => {
        const div = document.createElement('div');
        div.className = 'list-item fade-in';
        div.innerHTML = `
            <span>${s}</span>
            <button class="btn btn-sm btn-secondary" onclick="removeSubmodel('${s}')">
                <i data-feather="trash-2" style="width: 14px; height: 14px;"></i>
            </button>
        `;
        container.appendChild(div);
    });
    feather.replace();
}

// ─── Properties Page (Inline 4-Step Config) ──────────────────────────────────

let currentPropProtocol = 'modbus';
let propTargetRows = [];

function renderSubmodelTabs() {
    const container = document.getElementById('submodel-tabs-container');
    if (!container) return;
    container.innerHTML = '';

    if (state.submodels.length === 0) {
        const panel = document.getElementById('prop-config-panel');
        const noSM = document.getElementById('prop-no-submodel');
        if (panel) panel.style.display = 'none';
        if (noSM) noSM.style.display = 'block';
        container.innerHTML = '<span style="color: var(--warning);">Kein Submodell. Gehen Sie zu Schritt 2.</span>';
        return;
    }

    if (!state.activeSM || !state.submodels.includes(state.activeSM)) {
        state.activeSM = state.submodels[0];
    }

    state.submodels.forEach(s => {
        const btn = document.createElement('button');
        btn.className = `btn btn-sm ${state.activeSM === s ? 'btn-primary' : 'btn-secondary'}`;
        btn.textContent = s;
        btn.onclick = () => {
            savePropConfig();           // Save current SM before switching
            state.activeSM = s;
            renderSubmodelTabs();
            loadSubmodelConfig(s);
        };
        container.appendChild(btn);
    });
}

// ─── Canonical W3C-WoT-Modbus data types (kept in sync with
//     GUI/datatype_translate.py CANONICAL_TYPES). These are what the user
//     sees and what gets stored in the AAS Qualifier; each consumer
//     translates to its native flavour (PLC4X for official BaSyx,
//     lowercase IEC for the Custom DataBridge).
const PLC4X_TYPES = [
    'BOOL',
    'INT16', 'UINT16',
    'INT32', 'UINT32',
    'INT64', 'UINT64',
    'FLOAT32', 'FLOAT64',
    'STRING', 'BYTE',
];

// ─── Target Data Schema (per protocol) ──────────────────────────────────────
// Each schema defines the columns of the Target Data table.
//
// The ``direction`` column is uniform across all protocols: it tells the
// Custom DataBridge whether to **read** the value from the device (sensor
// signal, default), **write** values from the AAS back to the device
// (control / setpoint), or do both (``ReadWrite``). For writable
// data points the bridge subscribes to AAS-server MQTT events and pushes
// each new value into the device through the matching protocol.
const DIRECTION_OPTIONS = ['Read', 'Write', 'ReadWrite'];
const TRANSFORM_COL = { id: 'transform', label: 'Umrechnung', type: 'text', placeholder: 'x / 10', tooltip: 'Formel mit x = Rohwert. Beispiele: x/10  |  x*0.001  |  (x-32)/1.8  |  leer = kein Transform' };
const VIZ_COL = { id: 'vizType', label: 'Dashboard-Typ', type: 'select', options: ['timeseries', 'gauge', 'stat', 'bargauge'], default: 'timeseries', tooltip: 'Grafana-Panel-Typ: timeseries=Liniendiagramm · gauge=Zeigermesser · stat=Einzelwert · bargauge=Balken' };

const SEMANTIC_ID_COL = { id: 'semanticId', label: 'Semantic ID', type: 'text', placeholder: 'https://admin-shell.io/...', tooltip: 'IRI der semantischen Referenz — muss mit http(s):// beginnen', pattern: 'https?://.+' };

const TARGET_DATA_SCHEMA = {
    modbus: [
        { id: 'addr', label: 'Register-Adresse', type: 'text', placeholder: '30001', tooltip: 'Read: 30001–39999 (Input, FC4) · Write: 40001–49999 (Holding, FC6/FC16)' },
        { id: 'type', label: 'Datentyp', type: 'select', options: PLC4X_TYPES },
        { id: 'byteOrder', label: 'Byte-Order', type: 'select', options: ['AB CD', 'CD AB', 'BA DC', 'DC BA'] },
        { id: 'direction', label: 'Richtung', type: 'select', options: DIRECTION_OPTIONS, default: 'Read', tooltip: 'Read = Sensor (lesen), Write = Setpoint (schreiben), ReadWrite = beides' },
        { id: 'description', label: 'Name / Beschreibung', type: 'text', placeholder: 'z.B. Spannung L1' },
        SEMANTIC_ID_COL,
        { id: 'unit', label: 'Einheit', type: 'text', placeholder: 'V' },
        TRANSFORM_COL,
        VIZ_COL
    ],
    mqtt: [
        { id: 'addr', label: 'Topic', type: 'text', placeholder: 'simulation/solar/power' },
        { id: 'jsonPath', label: 'JSON-Pfad', type: 'text', placeholder: '$.value' },
        { id: 'type', label: 'Datentyp', type: 'select', options: PLC4X_TYPES },
        { id: 'direction', label: 'Richtung', type: 'select', options: DIRECTION_OPTIONS, default: 'Read', tooltip: 'Read = Subscribe, Write = Publish bei AAS-Update' },
        { id: 'description', label: 'Name / Beschreibung', type: 'text', placeholder: 'z.B. Solarleistung' },
        SEMANTIC_ID_COL,
        { id: 'unit', label: 'Einheit', type: 'text', placeholder: 'W' },
        TRANSFORM_COL,
        VIZ_COL
    ],
    http: [
        { id: 'addr', label: 'Pfad (relativ)', type: 'text', placeholder: '/api/weather/temperature', tooltip: 'Relativ zur Basis-URL' },
        { id: 'jsonPath', label: 'JSON-Pfad', type: 'text', placeholder: '$.value' },
        { id: 'type', label: 'Datentyp', type: 'select', options: PLC4X_TYPES },
        { id: 'direction', label: 'Richtung', type: 'select', options: DIRECTION_OPTIONS, default: 'Read', tooltip: 'Read = GET, Write = PUT/POST bei AAS-Update' },
        { id: 'description', label: 'Name / Beschreibung', type: 'text', placeholder: 'z.B. Temperatur' },
        SEMANTIC_ID_COL,
        { id: 'unit', label: 'Einheit', type: 'text', placeholder: '°C' },
        TRANSFORM_COL,
        VIZ_COL
    ],
    opcua: [
        { id: 'addr', label: 'Node-ID', type: 'text', placeholder: 'ns=2;i=1001', tooltip: 'Format: ns=<idx>;i=<num> oder ns=<idx>;s=<name>' },
        { id: 'type', label: 'Datentyp', type: 'select', options: PLC4X_TYPES },
        { id: 'samplingInterval', label: 'Sampling [ms]', type: 'text', placeholder: '250' },
        { id: 'direction', label: 'Richtung', type: 'select', options: DIRECTION_OPTIONS, default: 'Read', tooltip: 'Read = Subscription, Write = OPC-UA-Write bei AAS-Update' },
        { id: 'description', label: 'Name / Beschreibung', type: 'text', placeholder: 'z.B. Gelenkwinkel 1' },
        SEMANTIC_ID_COL,
        { id: 'unit', label: 'Einheit', type: 'text', placeholder: '°' },
        TRANSFORM_COL,
        VIZ_COL
    ],
    kafka: [
        { id: 'addr', label: 'Topic', type: 'text', placeholder: 'simulation.ev.soc' },
        { id: 'jsonPath', label: 'JSON-Pfad', type: 'text', placeholder: '$.value' },
        { id: 'type', label: 'Datentyp', type: 'select', options: PLC4X_TYPES },
        { id: 'description', label: 'Name / Beschreibung', type: 'text', placeholder: 'z.B. EV State of Charge' },
        SEMANTIC_ID_COL,
        { id: 'unit', label: 'Einheit', type: 'text', placeholder: '%' },
        TRANSFORM_COL,
        VIZ_COL
    ],
    bacnet: [
        { id: 'addr', label: 'Objekt-ID', type: 'text', placeholder: 'analog-input:1' },
        { id: 'propertyId', label: 'Property', type: 'select', options: ['PresentValue', 'StatusFlags', 'OutOfService', 'Units', 'MinPresValue', 'MaxPresValue'] },
        { id: 'type', label: 'Datentyp', type: 'select', options: PLC4X_TYPES },
        { id: 'direction', label: 'Richtung', type: 'select', options: DIRECTION_OPTIONS, default: 'Read' },
        { id: 'description', label: 'Name / Beschreibung', type: 'text', placeholder: 'z.B. Vorlauftemperatur' },
        SEMANTIC_ID_COL,
        { id: 'unit', label: 'Einheit', type: 'text', placeholder: '°C' },
        TRANSFORM_COL,
        VIZ_COL
    ],
    ocpp: [
        { id: 'addr', label: 'Measurand', type: 'select', options: ['Energy.Active.Import.Register','Energy.Active.Export.Register','Power.Active.Import','Power.Active.Export','Current.Import','Current.Export','Voltage','SoC','Temperature','RPM'] },
        { id: 'phase', label: 'Phase', type: 'select', options: ['', 'L1', 'L2', 'L3', 'N', 'L1-N', 'L2-N', 'L3-N', 'L1-L2', 'L2-L3', 'L1-L3'] },
        { id: 'type', label: 'Datentyp', type: 'select', options: PLC4X_TYPES },
        { id: 'description', label: 'Name / Beschreibung', type: 'text', placeholder: 'z.B. Energie-Zähler' },
        SEMANTIC_ID_COL,
        { id: 'unit', label: 'Einheit', type: 'text', placeholder: 'kWh' },
        TRANSFORM_COL,
        VIZ_COL
    ],
    dlms: [
        { id: 'addr', label: 'OBIS-Code', type: 'text', placeholder: '1.0.1.8.0.255' },
        { id: 'attribute', label: 'Attribut-Nr.', type: 'text', placeholder: '2', default: '2' },
        { id: 'type', label: 'Datentyp', type: 'select', options: PLC4X_TYPES },
        { id: 'description', label: 'Name / Beschreibung', type: 'text', placeholder: 'z.B. Wirkenergie Import' },
        SEMANTIC_ID_COL,
        { id: 'unit', label: 'Einheit', type: 'text', placeholder: 'kWh' },
        TRANSFORM_COL,
        VIZ_COL
    ],
};

function renderPropTargetHeader() {
    const header = document.getElementById('prop-target-header');
    if (!header) return;
    const schema = TARGET_DATA_SCHEMA[currentPropProtocol] || TARGET_DATA_SCHEMA.modbus;
    header.innerHTML = schema.map(col =>
        `<span title="${col.tooltip || ''}">${col.label}</span>`
    ).join('') + `<span style="text-align:right;"><button class="btn-add-row" onclick="addPropTargetRow()">+</button></span>`;
}

function selectPropProtocol(proto) {
    // Save current protocol's data before switching
    if (state.activeSM) {
        const cfg = state.submodelConfigs[state.activeSM] || {};
        if (!cfg.protocolData) cfg.protocolData = {};
        cfg.protocolData[currentPropProtocol] = {
            source: collectPropProtocolConfig(),
            targetData: collectPropTargetData()
        };
        cfg.protocol = proto;
        state.submodelConfigs[state.activeSM] = cfg;
    }

    currentPropProtocol = proto;
    document.querySelectorAll('#prop-protocol-selector .protocol-card').forEach(c => {
        c.classList.toggle('active', c.dataset.proto === proto);
    });

    // Load saved data for the new protocol (fall back to defaults)
    const saved = state.submodelConfigs[state.activeSM]?.protocolData?.[proto] || {};
    renderPropProtocolConfig(proto, saved.source || {});
    propTargetRows = JSON.parse(JSON.stringify(
        saved.targetData?.length ? saved.targetData : (PROTOCOL_DEFAULT_ROWS[proto] || [])
    ));
    renderPropTargetHeader();
    renderPropTargetData();
}

function renderPropProtocolConfig(proto, savedValues) {
    const container = document.getElementById('prop-protocol-config-body');
    if (!container) return;
    const fields = PROTOCOL_FIELDS[proto] || [];

    let html = '';
    let inGrid = false;

    fields.forEach(f => {
        if (f.sectionTitle) {
            if (inGrid) { html += '</div>'; inGrid = false; }
            html += `<p class="proto-section-label">${f.sectionTitle}</p><div class="proto-fields-grid">`;
            inGrid = true;
            return;
        }

        const saved = savedValues[f.id];
        const isDefault = (saved === undefined || saved === '');
        const val = isDefault ? (f.default !== undefined ? String(f.default) : '') : saved;
        const tip = f.tooltip ? `title="${f.tooltip}"` : '';
        const span = f.half ? '' : ' style="grid-column:1/-1"';
        const condAttr = f.conditional ? `data-cond-field="${f.conditional.field}" data-cond-values="${f.conditional.values.join(',')}"` : '';
        const defAttr = (f.default !== undefined && f.type !== 'select' && f.type !== 'checkbox') ? `data-default-val="${f.default}"` : '';

        let input = '';
        if (f.type === 'select') {
            const opts = f.options.map(o => `<option value="${o}"${o === val ? ' selected' : ''}>${o}</option>`).join('');
            input = `<select data-field="${f.id}" onchange="updateAllConditionalFields()" ${tip}>${opts}</select>`;
        } else if (f.type === 'checkbox') {
            input = `<label class="checkbox-label"><input type="checkbox" data-field="${f.id}" ${val === 'true' || val === true ? 'checked' : ''} ${tip}> aktiviert</label>`;
        } else {
            const dimClass = isDefault && val !== '' ? ' input-is-default' : '';
            input = `<input type="${f.type}" data-field="${f.id}" placeholder="${f.placeholder || ''}" value="${val}" class="proto-input${dimClass}" ${defAttr} ${tip} oninput="onProtoInputChange(this)">`;
        }

        html += `<div class="form-group${f.conditional ? ' conditional-field' : ''}"${span} ${condAttr}><label>${f.label}${f.tooltip ? ' <span class="field-hint">ⓘ</span>' : ''}:</label>${input}</div>`;
    });

    if (inGrid) html += '</div>';
    container.innerHTML = html;
    updateAllConditionalFields();
}

function onProtoInputChange(el) {
    const def = el.dataset.defaultVal;
    if (def === undefined) return;
    el.classList.toggle('input-is-default', el.value === def);
}

function collectPropProtocolConfig() {
    const result = {};
    document.getElementById('prop-protocol-config-body')
        ?.querySelectorAll('[data-field]')
        .forEach(el => {
            if (el.type === 'checkbox') {
                result[el.dataset.field] = el.checked;
            } else {
                result[el.dataset.field] = el.value;
            }
        });
    return result;
}

function addPropTargetRow(data = {}) {
    propTargetRows.push(data);
    renderPropTargetData();
}

function removePropTargetRow(idx) {
    propTargetRows.splice(idx, 1);
    renderPropTargetData();
}

function renderPropTargetData() {
    const container = document.getElementById('prop-target-data-rows');
    if (!container) return;
    const schema = TARGET_DATA_SCHEMA[currentPropProtocol] || TARGET_DATA_SCHEMA.modbus;
    if (propTargetRows.length === 0) {
        container.innerHTML = `<p style="color:var(--text-muted);font-size:0.85rem;padding:0.75rem;">
            Klicken Sie '+' um einen Datenpunkt hinzuzufügen.</p>`;
        return;
    }
    container.innerHTML = propTargetRows.map((row, i) => `
        <div class="target-data-row">
            ${schema.map(col => {
        if (col.type === 'select') {
            return `<select data-col="${col.id}">${col.options.map(o =>
                `<option${o === row[col.id] ? ' selected' : ''}>${o}</option>`
            ).join('')}</select>`;
        } else {
            const patternAttr = col.pattern ? ` pattern="${col.pattern}"` : '';
            const titleAttr   = col.tooltip  ? ` title="${col.tooltip}"`   : '';
            return `<input type="text" data-col="${col.id}" placeholder="${col.placeholder || ''}" value="${row[col.id] || ''}"${patternAttr}${titleAttr}>`;
        }
    }).join('')}
            <button class="btn-row-delete" onclick="removePropTargetRow(${i})">×</button>
        </div>`).join('');
}

function collectPropTargetData() {
    const schema = TARGET_DATA_SCHEMA[currentPropProtocol] || TARGET_DATA_SCHEMA.modbus;
    return Array.from(document.querySelectorAll('#prop-target-data-rows .target-data-row')).map(row => {
        const result = {};
        schema.forEach(col => {
            const el = row.querySelector(`[data-col="${col.id}"]`);
            result[col.id] = el?.value || '';
        });
        return result;
    });
}

function toggleAutoConfig(service) {
    const box = document.getElementById(`auto-config-${service}`);
    if (!box) return;
    box.style.display = box.style.display === 'none' ? 'block' : 'none';
}

function renderPropSinkConfig(savedSinks) {
    const container = document.getElementById('deploy-sink-config-body');
    if (!container) return;

    const sa = savedSinks?.auto || {};

    container.innerHTML = `
    <!-- ── Auto-Routing Info Banner ────────────────────────────── -->
    <div class="datasink-auto-banner">
        <div class="banner-title">✅ Automatische Datenziele <span class="banner-badge">immer aktiv</span></div>
        <p class="banner-note">Der Databridge Service sendet alle Messwerte automatisch an:</p>
        <div class="auto-tags">
            <span class="auto-tag clickable" onclick="toggleAutoConfig('mqtt')" title="Verbindung konfigurieren">
                📡 MQTT (internes Topic) <span class="auto-tag-gear">⚙</span>
            </span>
            <span class="auto-tag clickable" onclick="toggleAutoConfig('aas')" title="Verbindung konfigurieren">
                🏷️ AAS Property-Wert <span class="auto-tag-gear">⚙</span>
            </span>
        </div>
        <div id="auto-config-mqtt" class="auto-port-box" style="display:none;">
            <div style="display:grid;grid-template-columns:1fr auto;gap:0.6rem;width:100%;align-items:end;">
                <div><label>Host:</label>
                    <input type="text" id="auto-mqtt-host" placeholder="mosquitto" value="${sa.mqttHost || 'mosquitto'}"></div>
                <div><label>Port:</label>
                    <input type="number" id="auto-mqtt-port" placeholder="1883" style="width:90px;" value="${sa.mqttPort || '1883'}"></div>
            </div>
        </div>
        <div id="auto-config-aas" class="auto-port-box" style="display:none;">
            <div style="display:grid;grid-template-columns:1fr auto;gap:0.6rem;width:100%;align-items:end;">
                <div><label>Host:</label>
                    <input type="text" id="auto-aas-host" placeholder="aas-env" value="${sa.aasHost || 'aas-env'}"></div>
                <div><label>Port:</label>
                    <input type="number" id="auto-aas-port" placeholder="8081" style="width:90px;" value="${sa.aasPort || '8081'}"></div>
            </div>
        </div>
    </div>

    <p class="banner-note" style="margin-top:0.75rem;font-size:0.8rem;">
        💡 Weitere Datasinks (InfluxDB, ext. MQTT, HTTP) werden pro Submodell in Schritt 3 konfiguriert.
    </p>`;
}

function collectPropSinkConfig() {
    return {
        auto: {
            mqttHost: document.getElementById('auto-mqtt-host')?.value || 'mosquitto',
            mqttPort: document.getElementById('auto-mqtt-port')?.value || '1883',
            aasHost: document.getElementById('auto-aas-host')?.value || 'aas-env',
            aasPort: document.getElementById('auto-aas-port')?.value || '8081',
        }
    };
}


function loadSubmodelConfig(smName) {
    const panel = document.getElementById('prop-config-panel');
    const noSM = document.getElementById('prop-no-submodel');
    if (!smName || !state.submodels.includes(smName)) {
        if (panel) panel.style.display = 'none';
        if (noSM) noSM.style.display = 'block';
        return;
    }
    if (panel) panel.style.display = 'block';
    if (noSM) noSM.style.display = 'none';

    const cfg = state.submodelConfigs[smName] || {};
    const proto = cfg.protocol || 'modbus';
    currentPropProtocol = proto;
    document.querySelectorAll('#prop-protocol-selector .protocol-card').forEach(c => {
        c.classList.toggle('active', c.dataset.proto === proto);
    });

    const protoData = cfg.protocolData?.[proto] || {};
    renderPropProtocolConfig(proto, protoData.source || {});

    renderPropTargetHeader();
    propTargetRows = JSON.parse(JSON.stringify(
        protoData.targetData?.length ? protoData.targetData : (PROTOCOL_DEFAULT_ROWS[proto] || [])
    ));
    renderPropTargetData();

    // Restore sink config for this submodel
    renderSmSinkConfig(cfg.sinks || {});
}


function savePropConfig() {
    if (!state.activeSM) return;
    const cfg = state.submodelConfigs[state.activeSM] || {};
    if (!cfg.protocolData) cfg.protocolData = {};
    cfg.protocol = currentPropProtocol;
    cfg.protocolData[currentPropProtocol] = {
        source: collectPropProtocolConfig(),
        targetData: collectPropTargetData()
    };
    cfg.sinks = collectSmSinkConfig();
    state.submodelConfigs[state.activeSM] = cfg;
    saveToStorage();
}

// ─── JSON Import ─────────────────────────────────────────────────────────────

function handleJsonFileSelect(input) {
    const file = input.files[0];
    if (!file) return;

    const nameEl   = document.getElementById('json-import-filename');
    const statusEl = document.getElementById('json-import-status');
    nameEl.textContent   = file.name;
    statusEl.textContent = 'Parsing...';
    statusEl.style.color = 'var(--text-muted)';

    const reader = new FileReader();
    reader.onload = async (e) => {
        try {
            const resp = await fetch('/api/parse_device_config', {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({ content: e.target.result }),
            });
            const data = await resp.json();
            if (data.status !== 'success') throw new Error(data.message || 'Parse-Fehler');
            _applyImportedConfigs(data.configs);
            const total  = data.configs.reduce((s, c) => s + (c.targetData?.length || 0), 0);
            const protos = data.configs.map(c => c.protocol).join(' + ');
            statusEl.textContent = protos + ' — ' + total + ' Datenpunkt(e) importiert';
            statusEl.style.color = 'var(--success, #60cd90)';
        } catch (err) {
            statusEl.textContent = 'Fehler: ' + err.message;
            statusEl.style.color = 'var(--error, #f87171)';
        }
    };
    reader.readAsText(file);
    input.value = '';   // reset so same file can be re-selected
}

function _applyImportedConfigs(configs) {
    if (!configs || configs.length === 0) return;
    const smName = state.activeSM;
    if (!smName) return;

    const cfg = state.submodelConfigs[smName] || {};
    if (!cfg.protocolData) cfg.protocolData = {};

    let firstProto = null;
    for (const entry of configs) {
        const { protocol, source, targetData } = entry;
        cfg.protocolData[protocol] = { source: source || {}, targetData: targetData || [] };
        if (!firstProto) firstProto = protocol;
    }

    if (firstProto) {
        cfg.protocol = firstProto;
        state.submodelConfigs[smName] = cfg;
        currentPropProtocol = firstProto;

        // Highlight the matching protocol card
        document.querySelectorAll('#prop-protocol-selector .protocol-card').forEach(c => {
            c.classList.toggle('active', c.dataset.proto === firstProto);
        });

        // Populate connection params + target data table
        renderPropProtocolConfig(firstProto, cfg.protocolData[firstProto].source);
        propTargetRows = JSON.parse(JSON.stringify(cfg.protocolData[firstProto].targetData));
        renderPropTargetHeader();
        renderPropTargetData();
    }

    saveToStorage();
    feather.replace();
}

// ─── Protocol Config Templates ───────────────────────────────────────────────
// ─── Protocol Configuration Fields (full industrial config) ──────────────────
// sectionTitle: renders a section header
// half: renders in half-width column
// type: text | number | select | password | checkbox
// conditional: { field: 'fieldId', value: 'matchValue' } — shown only when condition met
// tooltip: shown as title attribute

const PROTOCOL_FIELDS = {
    modbus: [
        { sectionTitle: 'Verbindung' },
        { id: 'host', label: 'Host / IP-Adresse', type: 'text', placeholder: 'ext-simulator', default: 'ext-simulator', tooltip: 'IP-Adresse oder Hostname des Modbus-Geräts' },
        { id: 'port', label: 'Port', type: 'number', placeholder: '5020', default: '5020', half: true, tooltip: 'Standard: 502 (root), 5020 (Simulator)' },
        { id: 'slaveId', label: 'Slave-ID / Unit-ID', type: 'number', placeholder: '1', default: '1', half: true, tooltip: 'Geräteadresse im RS485-Bus (1–247)' },
        { sectionTitle: 'Timing & Zuverlässigkeit' },
        { id: 'polling', label: 'Polling-Intervall', type: 'text', placeholder: '1000 ms', default: '1000', half: true, tooltip: 'Wie oft wird das Register gelesen?' },
        { id: 'timeout', label: 'Timeout', type: 'text', placeholder: '3000 ms', default: '3000', half: true, tooltip: 'Verbindungs-Timeout' },
        { sectionTitle: 'Datenformat' },
        { id: 'byteOrder', label: 'Byte-Reihenfolge', type: 'select', options: ['AB CD (Big-Endian)', 'CD AB (Little-Endian)', 'BA DC (Byte-Swap)', 'DC BA (Word+Byte-Swap)'], default: 'AB CD (Big-Endian)', tooltip: 'Für FLOAT32/INT32: Wort-Reihenfolge der 2 Register' },
    ],
    mqtt: [
        { sectionTitle: 'Broker-Verbindung' },
        { id: 'broker', label: 'Broker Host', type: 'text', placeholder: 'mosquitto', default: 'mosquitto', tooltip: 'Hostname oder IP des MQTT-Brokers' },
        { id: 'port', label: 'Port', type: 'number', placeholder: '1883', default: '1883', half: true, tooltip: '1883 = unverschlüsselt, 8883 = TLS/SSL' },
        { id: 'clientId', label: 'Client-ID', type: 'text', placeholder: 'databridge-001', default: 'databridge-001', half: true, tooltip: 'Eindeutige Client-ID (leer = automatisch)' },
        { id: 'qos', label: 'QoS-Level', type: 'select', options: ['0 — At most once', '1 — At least once', '2 — Exactly once'], default: '0 — At most once', half: true, tooltip: 'QoS 0: Sensordaten, QoS 1: Alarme' },
        { id: 'keepAlive', label: 'Keep Alive', type: 'text', placeholder: '60 s', default: '60', half: true, tooltip: 'Heartbeat-Intervall' },
        { sectionTitle: 'Authentifizierung & Sicherheit' },
        { id: 'tlsEnabled', label: 'TLS/SSL aktivieren', type: 'checkbox', default: false, tooltip: 'Verschlüsselte Verbindung (Port 8883)' },
        { id: 'username', label: 'Benutzername', type: 'text', placeholder: '(optional)', half: true },
        { id: 'password', label: 'Passwort', type: 'password', placeholder: '(optional)', half: true },
    ],
    http: [
        { sectionTitle: 'Endpunkt' },
        { id: 'baseUrl', label: 'Basis-URL', type: 'text', placeholder: 'https://api.example.com  oder  http://192.168.1.50', default: '', tooltip: 'Basis-URL des REST-Endpoints. http:// für lokale Geräte, https:// für Cloud-APIs (z.B. myPowerGrid, Azure)' },
        { id: 'method', label: 'HTTP-Methode', type: 'select', options: ['GET', 'POST', 'PUT'], default: 'GET', half: true },
        { id: 'contentType', label: 'Content-Type', type: 'select', options: ['application/json', 'text/plain', 'application/xml'], default: 'application/json', half: true },
        { sectionTitle: 'Timing' },
        { id: 'polling', label: 'Polling-Intervall', type: 'text', placeholder: '5000 ms', default: '5000', half: true },
        { id: 'timeout', label: 'Timeout', type: 'text', placeholder: '5000 ms', default: '5000', half: true },
        { sectionTitle: 'Authentifizierung' },
        { id: 'authType', label: 'Auth-Typ', type: 'select',
          options: ['None', 'Bearer Token', 'Basic Auth',
                    'API Key (Header)', 'API Key (Query)',
                    'OAuth2 Client-Credentials'],
          default: 'None',
          tooltip: 'Wähle die Authentifizierungs-Strategie. OAuth2 Client-Credentials cached + refreshed automatisch.' },
        // Bearer
        { id: 'bearerToken', label: 'Bearer Token', type: 'password', placeholder: 'eyJhbGciOi...',
          conditional: { field: 'authType', values: ['Bearer Token'] } },
        // Basic
        { id: 'username', label: 'Benutzername', type: 'text', placeholder: 'admin', half: true,
          conditional: { field: 'authType', values: ['Basic Auth'] } },
        { id: 'password', label: 'Passwort', type: 'password', placeholder: '***', half: true,
          conditional: { field: 'authType', values: ['Basic Auth'] } },
        // API Key in header
        { id: 'apiKey', label: 'API-Key', type: 'password', placeholder: 'sk_live_...',
          conditional: { field: 'authType', values: ['API Key (Header)', 'API Key (Query)'] } },
        { id: 'apiKeyHeader', label: 'Header-Name', type: 'text', placeholder: 'X-API-Key', default: 'X-API-Key',
          conditional: { field: 'authType', values: ['API Key (Header)'] } },
        { id: 'apiKeyQuery', label: 'Query-Param-Name', type: 'text', placeholder: 'apikey', default: 'apikey',
          conditional: { field: 'authType', values: ['API Key (Query)'] } },
        // OAuth2 Client Credentials (RFC 6749 §4.4)
        { id: 'oauthTokenUrl', label: 'Token-Endpoint URL', type: 'text',
          placeholder: 'https://auth.mypowergrid.de/realms/wendeware/protocol/openid-connect/token',
          conditional: { field: 'authType', values: ['OAuth2 Client-Credentials'] } },
        { id: 'clientId', label: 'Client-ID', type: 'text', placeholder: 'your-api-client-id', half: true,
          conditional: { field: 'authType', values: ['OAuth2 Client-Credentials'] } },
        { id: 'clientSecret', label: 'Client-Secret', type: 'password', placeholder: '****', half: true,
          conditional: { field: 'authType', values: ['OAuth2 Client-Credentials'] } },
        { id: 'scope', label: 'Scope (optional)', type: 'text', placeholder: 'email',
          conditional: { field: 'authType', values: ['OAuth2 Client-Credentials'] } },
        { sectionTitle: 'Query-Parameter (optional)' },
        { id: 'queryParams', label: 'Filter / Query-Params',
          type: 'text',
          placeholder: 'filter[resolution]=1 minute&filter[tz]=Europe/Berlin',
          tooltip: 'Werden bei jedem Request mitgeschickt (URL-encoded).' },
    ],
    opcua: [
        { sectionTitle: 'Server-Verbindung' },
        { id: 'serverUrl', label: 'Server-Endpoint URL', type: 'text', placeholder: 'opc.tcp://ext-simulator:4840', default: 'opc.tcp://ext-simulator:4840', tooltip: 'Vollständige OPC-UA Endpoint-URL' },
        { sectionTitle: 'Sicherheit' },
        { id: 'securityPolicy', label: 'Security Policy', type: 'select', options: ['None', 'Basic128Rsa15', 'Basic256', 'Basic256Sha256', 'Aes128_Sha256_RsaOaep'], default: 'None', half: true },
        { id: 'securityMode', label: 'Message Security Mode', type: 'select', options: ['None', 'Sign', 'SignAndEncrypt'], default: 'None', half: true },
        { sectionTitle: 'Authentifizierung' },
        { id: 'authType', label: 'Auth-Typ', type: 'select', options: ['Anonymous', 'Username', 'Certificate'], default: 'Anonymous' },
        { id: 'username', label: 'Benutzername', type: 'text', placeholder: 'opcuser', half: true, conditional: { field: 'authType', values: ['Username'] } },
        { id: 'password', label: 'Passwort', type: 'password', placeholder: '***', half: true, conditional: { field: 'authType', values: ['Username'] } },
        { sectionTitle: 'Subscription' },
        { id: 'publishingInterval', label: 'Publishing Interval', type: 'text', placeholder: '500 ms', default: '500', half: true, tooltip: 'Wie oft sendet der Server Änderungen?' },
        { id: 'samplingInterval', label: 'Sampling Interval', type: 'text', placeholder: '250 ms', default: '250', half: true, tooltip: 'Wie oft wird der Wert am Gerät abgetastet?' },
    ],
    kafka: [
        { sectionTitle: 'Broker-Verbindung' },
        { id: 'brokerUrl', label: 'Broker URL', type: 'text', placeholder: 'kafka:9092', default: 'kafka:9092', tooltip: 'host:port des Kafka-Brokers' },
        { id: 'securityProto', label: 'Security Protocol', type: 'select', options: ['PLAINTEXT', 'SSL', 'SASL_PLAINTEXT', 'SASL_SSL'], default: 'PLAINTEXT', half: true },
        { sectionTitle: 'Consumer-Konfiguration' },
        { id: 'groupId', label: 'Consumer Group ID', type: 'text', placeholder: 'databridge', default: 'databridge', half: true, tooltip: 'Eindeutige Gruppe — mehrere DataBridges brauchen verschiedene IDs' },
        { id: 'maxPollRecords', label: 'Max Poll Records', type: 'number', placeholder: '5000', default: '5000', half: true },
        { id: 'seekTo', label: 'Start-Position', type: 'select', options: ['latest', 'earliest', 'beginning'], default: 'latest', half: true, tooltip: 'latest: nur neue Nachrichten, earliest: ab Anfang' },
        { id: 'sessionTimeout', label: 'Session Timeout', type: 'text', placeholder: '30000 ms', default: '30000', half: true },
    ],
    bacnet: [
        { sectionTitle: 'Netzwerk-Verbindung' },
        { id: 'host', label: 'IP-Adresse / Host', type: 'text', placeholder: '192.168.1.100', default: '192.168.1.100', tooltip: 'IP-Adresse des BACnet/IP-Geräts' },
        { id: 'port', label: 'UDP-Port', type: 'number', placeholder: '47808', default: '47808', half: true },
        { id: 'deviceInstance', label: 'Device Instance', type: 'number', placeholder: '1234', default: '1234', half: true, tooltip: 'Eindeutige Gerätenummer (0–4194303)' },
        { id: 'network', label: 'Netzwerk-Nr.', type: 'number', placeholder: '0', default: '0', half: true, tooltip: '0 = lokales Netzwerk' },
        { sectionTitle: 'Timing' },
        { id: 'polling', label: 'Polling-Intervall', type: 'text', placeholder: '5000 ms', default: '5000', half: true },
        { id: 'timeout', label: 'Timeout', type: 'text', placeholder: '3000 ms', default: '3000', half: true },
    ],
    ocpp: [
        { sectionTitle: 'OCPP-Server' },
        { id: 'serverUrl', label: 'WebSocket-URL', type: 'text', placeholder: 'ws://ocpp-server:9000', default: 'ws://ocpp-server:9000', tooltip: 'URL des OCPP Central System' },
        { id: 'chargePointId', label: 'Charge Point ID', type: 'text', placeholder: 'CP001', default: 'CP001', half: true, tooltip: 'Eindeutige ID der Ladestation' },
        { id: 'ocppVersion', label: 'OCPP Version', type: 'select', options: ['OCPP 1.6', 'OCPP 2.0.1'], default: 'OCPP 1.6', half: true },
        { sectionTitle: 'Authentifizierung' },
        { id: 'password', label: 'Passwort (optional)', type: 'password', placeholder: '(leer = kein Auth)' },
        { sectionTitle: 'Timing' },
        { id: 'polling', label: 'Polling-Intervall', type: 'text', placeholder: '10000 ms', default: '10000', half: true, tooltip: 'Intervall zum Abrufen von MeterValues' },
    ],
    dlms: [
        { sectionTitle: 'Verbindung' },
        { id: 'host', label: 'IP-Adresse / Host', type: 'text', placeholder: '192.168.1.200', default: '192.168.1.200' },
        { id: 'port', label: 'Port', type: 'number', placeholder: '4059', default: '4059', half: true, tooltip: 'Standard-Port für DLMS over TCP' },
        { id: 'logicalDevice', label: 'Logical Device Addr.', type: 'text', placeholder: '1', default: '1', half: true },
        { id: 'clientAddress', label: 'Client Address', type: 'number', placeholder: '16', default: '16', half: true, tooltip: '16 = öffentlicher Client' },
        { sectionTitle: 'Authentifizierung' },
        { id: 'authType', label: 'Auth-Level', type: 'select', options: ['None', 'Low', 'High'], default: 'None', half: true },
        { id: 'password', label: 'Passwort', type: 'password', placeholder: '(optional)', half: true, conditional: { field: 'authType', values: ['Low', 'High'] } },
        { sectionTitle: 'Timing' },
        { id: 'polling', label: 'Polling-Intervall', type: 'text', placeholder: '60000 ms', default: '60000', half: true, tooltip: 'Typisch 1 min für Zähler' },
        { id: 'timeout', label: 'Timeout', type: 'text', placeholder: '10000 ms', default: '10000', half: true },
    ],
};

// Default target data rows shown when a protocol is first selected (no saved data)
const PROTOCOL_DEFAULT_ROWS = {
    modbus: [
        { addr: '40001', type: 'FLOAT32', byteOrder: 'AB CD', description: 'Spannung L1', unit: 'V' },
        { addr: '40003', type: 'FLOAT32', byteOrder: 'AB CD', description: 'Strom L1', unit: 'A' },
        { addr: '40005', type: 'FLOAT32', byteOrder: 'AB CD', description: 'Wirkleistung', unit: 'W' },
    ],
    mqtt: [
        { addr: 'sensor/temperature', jsonPath: '$.value', type: 'FLOAT32', description: 'Temperatur', unit: '°C' },
        { addr: 'sensor/humidity', jsonPath: '$.value', type: 'FLOAT32', description: 'Luftfeuchtigkeit', unit: '%' },
    ],
    http: [
        { addr: '/api/data/temperature', jsonPath: '$.value', type: 'FLOAT32', description: 'Temperatur', unit: '°C' },
        { addr: '/api/data/status', jsonPath: '$.status', type: 'STRING', description: 'Status', unit: '' },
    ],
    opcua: [
        { addr: 'ns=2;i=1001', type: 'FLOAT32', samplingInterval: '250', description: 'Gelenkwinkel 1', unit: '°' },
        { addr: 'ns=2;i=1002', type: 'FLOAT32', samplingInterval: '250', description: 'Gelenkwinkel 2', unit: '°' },
        { addr: 'ns=2;i=1003', type: 'BOOL', samplingInterval: '500', description: 'Betriebsstatus', unit: '' },
    ],
    kafka: [
        { addr: 'sensor.data', jsonPath: '$.value', type: 'FLOAT32', description: 'Messwert', unit: '' },
    ],
    bacnet: [
        { addr: 'analog-input:1', propertyId: 'PresentValue', type: 'FLOAT32', direction: 'Read', description: 'Vorlauftemperatur', unit: '°C' },
        { addr: 'analog-input:2', propertyId: 'PresentValue', type: 'FLOAT32', direction: 'Read', description: 'Rücklauftemperatur', unit: '°C' },
        { addr: 'analog-output:1', propertyId: 'PresentValue', type: 'FLOAT32', direction: 'Write', description: 'Solltemperatur', unit: '°C' },
    ],
    ocpp: [
        { addr: 'Energy.Active.Import.Register', phase: '', type: 'FLOAT32', description: 'Energie Gesamt Import', unit: 'kWh' },
        { addr: 'Power.Active.Import', phase: 'L1', type: 'FLOAT32', description: 'Leistung L1', unit: 'W' },
        { addr: 'SoC', phase: '', type: 'FLOAT32', description: 'Ladezustand', unit: '%' },
    ],
    dlms: [
        { addr: '1.0.1.8.0.255', attribute: '2', type: 'FLOAT32', description: 'Wirkenergie Import', unit: 'kWh' },
        { addr: '1.0.2.8.0.255', attribute: '2', type: 'FLOAT32', description: 'Wirkenergie Export', unit: 'kWh' },
        { addr: '1.0.1.7.0.255', attribute: '2', type: 'FLOAT32', description: 'Wirkleistung', unit: 'W' },
    ],
};

let currentProtocol = 'modbus';
let targetDataRows = [];

function selectProtocol(proto) {
    currentProtocol = proto;
    document.querySelectorAll('.protocol-card').forEach(c => {
        c.classList.toggle('active', c.dataset.proto === proto);
    });
    renderProtocolConfig(proto, {});
}

function renderProtocolConfig(proto, savedValues) {
    const container = document.getElementById('protocol-config-body');
    if (!container) return;
    const fields = PROTOCOL_FIELDS[proto] || [];

    let html = '';
    let inGrid = false;

    fields.forEach(f => {
        if (f.sectionTitle) {
            if (inGrid) { html += '</div>'; inGrid = false; }
            html += `<p class="proto-section-label">${f.sectionTitle}</p><div class="proto-fields-grid">`;
            inGrid = true;
            return;
        }

        const saved = savedValues[f.id];
        const isDefault = (saved === undefined || saved === '');
        const val = isDefault ? (f.default !== undefined ? String(f.default) : '') : saved;
        const tip = f.tooltip ? `title="${f.tooltip}"` : '';
        const span = f.half ? '' : ' style="grid-column:1/-1"';
        const condAttr = f.conditional ? `data-cond-field="${f.conditional.field}" data-cond-values="${f.conditional.values.join(',')}"` : '';
        const defAttr = (f.default !== undefined && f.type !== 'select' && f.type !== 'checkbox') ? `data-default-val="${f.default}"` : '';

        let input = '';
        if (f.type === 'select') {
            const opts = f.options.map(o => `<option value="${o}"${o === val ? ' selected' : ''}>${o}</option>`).join('');
            input = `<select data-field="${f.id}" onchange="updateConditionalFields()" ${tip}>${opts}</select>`;
        } else if (f.type === 'checkbox') {
            input = `<label class="checkbox-label"><input type="checkbox" data-field="${f.id}" ${val === 'true' || val === true ? 'checked' : ''} ${tip}> aktiviert</label>`;
        } else {
            const dimClass = isDefault && val !== '' ? ' input-is-default' : '';
            input = `<input type="${f.type}" data-field="${f.id}" placeholder="${f.placeholder || ''}" value="${val}" class="proto-input${dimClass}" ${defAttr} ${tip} oninput="onProtoInputChange(this)">`;
        }

        html += `<div class="form-group${f.conditional ? ' conditional-field' : ''}"${span} ${condAttr}>${'<label>' + f.label + (f.tooltip ? ' <span class="field-hint">ⓘ</span>' : '') + ':</label>'}${input}</div>`;
    });

    if (inGrid) html += '</div>';
    container.innerHTML = html;
    updateAllConditionalFields();
}

function updateConditionalFields() {
    updateAllConditionalFields();
}

function updateAllConditionalFields() {
    const container = document.getElementById('protocol-config-body') || document.getElementById('prop-protocol-config-body');
    if (!container) return;
    // Collect current values of all select fields
    const vals = {};
    container.querySelectorAll('[data-field]').forEach(el => { vals[el.dataset.field] = el.value; });

    container.querySelectorAll('.conditional-field').forEach(div => {
        const condField = div.dataset.condField;
        const condValues = (div.dataset.condValues || '').split(',');
        const visible = condValues.includes(vals[condField]);
        div.style.display = visible ? '' : 'none';
    });
}

function collectProtocolConfig() {
    const result = {};
    const containers = [
        document.getElementById('protocol-config-body'),
        document.getElementById('prop-protocol-config-body')
    ];
    containers.forEach(c => {
        if (!c) return;
        c.querySelectorAll('[data-field]').forEach(el => {
            if (el.type === 'checkbox') {
                result[el.dataset.field] = el.checked;
            } else {
                result[el.dataset.field] = el.value;
            }
        });
    });
    return result;
}

// ─── Target Data ─────────────────────────────────────────────────────────────

function addTargetDataRow(data = {}) {
    targetDataRows.push(data);
    renderTargetData();
}

function removeTargetDataRow(idx) {
    targetDataRows.splice(idx, 1);
    renderTargetData();
}

function renderTargetData() {
    const container = document.getElementById('target-data-rows');
    if (!container) return;
    if (targetDataRows.length === 0) {
        container.innerHTML = `<p style="color:var(--text-muted);font-size:0.85rem;padding:0.75rem;">
            Keine Einträge — klicken Sie '+' um eine Zeile hinzuzufügen.</p>`;
        return;
    }
    const typeOpts = PLC4X_TYPES;
    const fmtOpts = ['ENUM', 'RAW', 'JSON', 'SCALED'];
    container.innerHTML = targetDataRows.map((row, i) => `
        <div class="target-data-row">
            <input type="text" placeholder="Enter Address"     value="${row.addr || ''}">
            <select>${typeOpts.map(o => `<option${o === row.type ? ' selected' : ''}>${o}</option>`).join('')}</select>
            <select>${fmtOpts.map(o => `<option${o === row.format ? ' selected' : ''}>${o}</option>`).join('')}</select>
            <input type="text" placeholder="Enter Description" value="${row.description || ''}">
            <input type="text" placeholder="Enter Unit"        value="${row.unit || ''}">
            <button class="btn-row-delete" onclick="removeTargetDataRow(${i})">×</button>
        </div>`).join('');
}

function collectTargetData() {
    return Array.from(document.querySelectorAll('#target-data-rows .target-data-row')).map(row => {
        const inp = row.querySelectorAll('input');
        const sel = row.querySelectorAll('select');
        return {
            addr: inp[0]?.value || '',
            type: sel[0]?.value || 'FLOAT32',
            format: sel[1]?.value || 'ENUM',
            description: inp[1]?.value || '',
            unit: inp[2]?.value || ''
        };
    });
}

// ─── Data Sink ────────────────────────────────────────────────────────────────

function renderSinkConfig(savedSinks) {
    const container = document.getElementById('sink-config-body');
    if (!container) return;
    const mqttOn = document.getElementById('sink-mqtt-active')?.checked;
    const influxOn = document.getElementById('sink-influx-active')?.checked;
    const httpOn = document.getElementById('sink-http-active')?.checked;
    const sm = savedSinks?.mqtt || {};
    const si = savedSinks?.influx || {};
    const sh = savedSinks?.http || {};
    let html = '';
    if (mqttOn || influxOn || httpOn) {
        html = '<div class="sink-fields-grid">';
        if (mqttOn) html += `
            <div class="sink-section">
                <p class="sink-section-title">📡 MQTT</p>
                <div class="form-group"><label>Broker:</label>
                    <input type="text" id="sink-mqtt-broker" placeholder="192.168.1.20" value="${sm.broker || ''}"></div>
                <div class="form-group" style="display:grid;grid-template-columns:1fr 1fr;gap:1rem">
                    <div><label>Port:</label><input type="number" id="sink-mqtt-port" value="${sm.port || '1883'}"></div>
                    <div><label>QoS:</label><select id="sink-mqtt-qos">
                        <option${(sm.qos || '1') === '0' ? ' selected' : ''}>0</option>
                        <option${(sm.qos || '1') === '1' ? ' selected' : ''}>1</option>
                        <option${(sm.qos || '1') === '2' ? ' selected' : ''}>2</option>
                    </select></div>
                </div>
                <div class="form-group"><label>Topic:</label>
                    <input type="text" id="sink-mqtt-topic" placeholder="aas/sensor/value" value="${sm.topic || ''}"></div>
            </div>`;
        if (influxOn) html += `
            <div class="sink-section">
                <p class="sink-section-title">📊 InfluxDB</p>
                <div class="form-group"><label>Endpoint:</label>
                    <input type="text" id="sink-influx-endpoint" placeholder="http://192.168.1.50:8086" value="${si.endpoint || ''}"></div>
                <div class="form-group"><label>Database:</label>
                    <input type="text" id="sink-influx-db" placeholder="hems_data" value="${si.database || ''}"></div>
                <div class="form-group"><label>Measurement:</label>
                    <input type="text" id="sink-influx-measurement" placeholder="sensor_value" value="${si.measurement || ''}"></div>
            </div>`;
        if (httpOn) html += `
            <div class="sink-section">
                <p class="sink-section-title">🌐 HTTP POST</p>
                <div class="form-group"><label>URL:</label>
                    <input type="text" id="sink-http-url" placeholder="http://api.example.com/data" value="${sh.url || ''}"></div>
                <div class="form-group"><label>Auth Token:</label>
                    <input type="text" id="sink-http-token" placeholder="Bearer ..." value="${sh.token || ''}"></div>
            </div>`;
        html += '</div>';
    }
    container.innerHTML = html;
}

function collectSinkConfig() {
    return {
        mqtt: {
            active: !!document.getElementById('sink-mqtt-active')?.checked,
            broker: document.getElementById('sink-mqtt-broker')?.value || '',
            port: document.getElementById('sink-mqtt-port')?.value || '1883',
            qos: document.getElementById('sink-mqtt-qos')?.value || '1',
            topic: document.getElementById('sink-mqtt-topic')?.value || ''
        },
        influx: {
            active: !!document.getElementById('sink-influx-active')?.checked,
            endpoint: document.getElementById('sink-influx-endpoint')?.value || '',
            database: document.getElementById('sink-influx-db')?.value || '',
            measurement: document.getElementById('sink-influx-measurement')?.value || ''
        },
        http: {
            active: !!document.getElementById('sink-http-active')?.checked,
            url: document.getElementById('sink-http-url')?.value || '',
            token: document.getElementById('sink-http-token')?.value || ''
        }
    };
}

// ─── Step-3 Submodel Sink Config (per-submodel, moves from Deploy page) ───────

async function renderSmSinkConfig(savedSinks) {
    const container = document.getElementById('sm-sink-body');
    if (!container) return;

    const si  = savedSinks?.extra?.influx || {};
    const sem = savedSinks?.extra?.mqtt   || {};
    const sh  = savedSinks?.extra?.http   || {};

    const influxOn = document.getElementById('sm-sink-influx')?.checked ?? !!savedSinks?.extra?.influx?.active;
    const mqttOn   = document.getElementById('sm-sink-mqtt')?.checked   ?? !!savedSinks?.extra?.mqtt?.active;
    const httpOn   = document.getElementById('sm-sink-http')?.checked   ?? !!savedSinks?.extra?.http?.active;

    // Pre-fill empty InfluxDB fields with system defaults so the user
    // doesn't have to type host/token/org. Defaults come from
    // /api/influxdb/defaults (resolved via connection.json).
    if (influxOn && !window._influxDefaults) {
        try {
            const r = await fetch('/api/influxdb/defaults');
            window._influxDefaults = await r.json();
        } catch (_) { window._influxDefaults = {}; }
    }
    const D = window._influxDefaults || {};

    container.innerHTML = `
    <div class="sink-toggle-row">
        <label class="sink-toggle-label">
            <input type="checkbox" id="sm-sink-influx" ${influxOn ? 'checked' : ''}
                   onchange="renderSmSinkConfig(null)"> 📊 InfluxDB
        </label>
        <label class="sink-toggle-label">
            <input type="checkbox" id="sm-sink-mqtt" ${mqttOn ? 'checked' : ''}
                   onchange="renderSmSinkConfig(null)"> 📡 Ext. MQTT
        </label>
        <label class="sink-toggle-label">
            <input type="checkbox" id="sm-sink-http" ${httpOn ? 'checked' : ''}
                   onchange="renderSmSinkConfig(null)"> 🌐 HTTP POST
        </label>
    </div>
    ${influxOn || mqttOn || httpOn ? `<div class="sink-fields-grid">` : ''}

    ${influxOn ? `
    <div class="sink-section">
        <p class="sink-section-title">📊 InfluxDB <span class="text-muted" style="font-size:0.72rem;font-weight:400;">(Defaults from /api/influxdb/defaults)</span></p>
        <div class="form-group" style="display:grid;grid-template-columns:1fr auto;gap:0.75rem;align-items:end;">
            <div><label>Host:</label>
                <input type="text" id="sm-influx-host" placeholder="${D.host || 'influxdb'}" value="${si.host || D.host || ''}"></div>
            <div><label>Port:</label>
                <input type="number" id="sm-influx-port" placeholder="${D.port || 8086}" style="width:90px;" value="${si.port || D.port || '8086'}"></div>
        </div>
        <div class="form-group">
            <label>Version:</label>
            <select id="sm-influx-version">
                <option ${(si.version || 'v2') === 'v1' ? 'selected' : ''}>v1</option>
                <option ${(si.version || 'v2') === 'v2' ? 'selected' : ''}>v2</option>
            </select>
        </div>
        <div class="form-group" style="display:grid;grid-template-columns:1fr 1fr;gap:0.75rem">
            <div><label>Database / Bucket:</label>
                <input type="text" id="sm-influx-db" placeholder="${D.bucket || 'hems'}" value="${si.database || D.bucket || ''}"></div>
            <div><label>Measurement:</label>
                <input type="text" id="sm-influx-measurement" placeholder="sensor_value" value="${si.measurement || ''}"></div>
        </div>
        <div class="form-group" style="display:grid;grid-template-columns:1fr 1fr;gap:0.75rem">
            <div><label>Organization (v2):</label>
                <input type="text" id="sm-influx-org" placeholder="${D.org || 'basyx'}" value="${si.org || D.org || ''}"></div>
            <div><label>Token:</label>
                <input type="text" id="sm-influx-token" placeholder="auto" value="${si.token || D.token || ''}"></div>
        </div>
    </div>` : ''}

    ${mqttOn ? `
    <div class="sink-section">
        <p class="sink-section-title">📡 Ext. MQTT</p>
        <div class="form-group" style="display:grid;grid-template-columns:1fr auto;gap:0.75rem;align-items:end;">
            <div><label>Broker Host:</label>
                <input type="text" id="sm-mqtt-broker" placeholder="192.168.1.20" value="${sem.broker || ''}"></div>
            <div><label>Port:</label>
                <input type="number" id="sm-mqtt-port" placeholder="1883" style="width:90px;" value="${sem.port || '1883'}"></div>
        </div>
        <div class="form-group" style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:0.75rem">
            <div><label>QoS:</label>
                <select id="sm-mqtt-qos">
                    <option ${(sem.qos || '1') === '0' ? 'selected' : ''}>0</option>
                    <option ${(sem.qos || '1') === '1' ? 'selected' : ''}>1</option>
                    <option ${(sem.qos || '1') === '2' ? 'selected' : ''}>2</option>
                </select></div>
            <div><label>Username:</label>
                <input type="text" id="sm-mqtt-user" placeholder="optional" value="${sem.username || ''}"></div>
            <div><label>Password:</label>
                <input type="password" id="sm-mqtt-pass" placeholder="optional" value="${sem.password || ''}"></div>
        </div>
        <div class="form-group"><label>Topic:</label>
            <input type="text" id="sm-mqtt-topic" placeholder="aas/sensor/value" value="${sem.topic || ''}">
        </div>
        <div class="form-group" style="display:grid;grid-template-columns:1fr 1fr;gap:0.75rem">
            <div><label>Client ID:</label>
                <input type="text" id="sm-mqtt-clientid" placeholder="databridge-01" value="${sem.clientId || ''}"></div>
            <div style="display:flex;align-items:center;gap:0.5rem;margin-top:1.6rem;">
                <input type="checkbox" id="sm-mqtt-tls" ${sem.tls ? 'checked' : ''} style="width:16px;height:16px;">
                <label style="margin:0;">TLS aktivieren</label></div>
        </div>
    </div>` : ''}

    ${httpOn ? `
    <div class="sink-section">
        <p class="sink-section-title">🌐 HTTP POST</p>
        <div class="form-group"><label>URL:</label>
            <input type="text" id="sm-http-url" placeholder="http://api.example.com/data" value="${sh.url || ''}">
        </div>
        <div class="form-group" style="display:grid;grid-template-columns:1fr 1fr;gap:0.75rem">
            <div><label>Methode:</label>
                <select id="sm-http-method">
                    <option ${(sh.method || 'POST') === 'POST' ? 'selected' : ''}>POST</option>
                    <option ${(sh.method || 'POST') === 'PUT' ? 'selected' : ''}>PUT</option>
                    <option ${(sh.method || 'POST') === 'PATCH' ? 'selected' : ''}>PATCH</option>
                </select></div>
            <div><label>Content-Type:</label>
                <select id="sm-http-content-type">
                    <option ${(sh.contentType || 'application/json') === 'application/json' ? 'selected' : ''}>application/json</option>
                    <option ${(sh.contentType || '') === 'text/plain' ? 'selected' : ''}>text/plain</option>
                    <option ${(sh.contentType || '') === 'application/x-www-form-urlencoded' ? 'selected' : ''}>application/x-www-form-urlencoded</option>
                </select></div>
        </div>
        <div class="form-group" style="display:grid;grid-template-columns:1fr 1fr;gap:0.75rem">
            <div><label>Auth-Typ:</label>
                <select id="sm-http-auth-type" onchange="renderSmSinkConfig(null)">
                    <option ${(sh.authType || 'none') === 'none' ? 'selected' : ''}>none</option>
                    <option ${(sh.authType || '') === 'bearer' ? 'selected' : ''}>bearer</option>
                    <option ${(sh.authType || '') === 'basic' ? 'selected' : ''}>basic</option>
                </select></div>
            ${(sh.authType || 'none') === 'bearer' ? `
            <div><label>Token:</label>
                <input type="text" id="sm-http-token" placeholder="Bearer ..." value="${sh.token || ''}"></div>` : ''}
            ${(sh.authType || 'none') === 'basic' ? `
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.4rem;">
                <div><label>Username:</label>
                    <input type="text" id="sm-http-user" placeholder="user" value="${sh.username || ''}"></div>
                <div><label>Password:</label>
                    <input type="password" id="sm-http-pass" placeholder="pass" value="${sh.password || ''}"></div>
            </div>` : ''}
        </div>
    </div>` : ''}

    ${influxOn || mqttOn || httpOn ? `</div>` : ''}`;
}

function collectSmSinkConfig() {
    return {
        extra: {
            influx: {
                active: !!document.getElementById('sm-sink-influx')?.checked,
                host: document.getElementById('sm-influx-host')?.value || '',
                port: document.getElementById('sm-influx-port')?.value || '8086',
                version: document.getElementById('sm-influx-version')?.value || 'v2',
                database: document.getElementById('sm-influx-db')?.value || '',
                measurement: document.getElementById('sm-influx-measurement')?.value || '',
                org: document.getElementById('sm-influx-org')?.value || '',
                token: document.getElementById('sm-influx-token')?.value || '',
            },
            mqtt: {
                active: !!document.getElementById('sm-sink-mqtt')?.checked,
                broker: document.getElementById('sm-mqtt-broker')?.value || '',
                port: document.getElementById('sm-mqtt-port')?.value || '1883',
                qos: document.getElementById('sm-mqtt-qos')?.value || '1',
                topic: document.getElementById('sm-mqtt-topic')?.value || '',
                username: document.getElementById('sm-mqtt-user')?.value || '',
                password: document.getElementById('sm-mqtt-pass')?.value || '',
                clientId: document.getElementById('sm-mqtt-clientid')?.value || '',
                tls: !!document.getElementById('sm-mqtt-tls')?.checked,
            },
            http: {
                active: !!document.getElementById('sm-sink-http')?.checked,
                url: document.getElementById('sm-http-url')?.value || '',
                method: document.getElementById('sm-http-method')?.value || 'POST',
                contentType: document.getElementById('sm-http-content-type')?.value || 'application/json',
                authType: document.getElementById('sm-http-auth-type')?.value || 'none',
                token: document.getElementById('sm-http-token')?.value || '',
                username: document.getElementById('sm-http-user')?.value || '',
                password: document.getElementById('sm-http-pass')?.value || '',
            }
        }
    };
}

// ─── Modal Logic ──────────────────────────────────────────────────────────────

function openPropertyConfigModal(propName) {
    const modal = document.getElementById('property-modal');
    document.getElementById('modal-title').textContent = `Property: ${propName}`;
    const prop = state.properties.find(p => p.name === propName && p.parentSM === state.activeSM);
    const cfg = prop?.config || {};

    // 1. Restore protocol selection
    const proto = cfg.protocol || 'modbus';
    currentProtocol = proto;
    document.querySelectorAll('.protocol-card').forEach(c => {
        c.classList.toggle('active', c.dataset.proto === proto);
    });
    renderProtocolConfig(proto, cfg.source || {});

    // 2. Restore target data rows (default: one empty row)
    targetDataRows = JSON.parse(JSON.stringify(cfg.targetData || []));
    if (targetDataRows.length === 0) {
        targetDataRows.push({ addr: '', type: 'FLOAT32', format: 'ENUM', description: propName, unit: '' });
    }
    renderTargetData();

    // 3. Restore sink toggles + render config with saved values
    const sinks = cfg.sinks || {};
    const setChk = (id, val) => { const el = document.getElementById(id); if (el) el.checked = val; };
    setChk('sink-mqtt-active', sinks.mqtt?.active === true);
    setChk('sink-influx-active', sinks.influx?.active === true);
    setChk('sink-http-active', sinks.http?.active === true);
    renderSinkConfig(sinks);

    modal.classList.add('active');
}

function closeModal() {
    document.getElementById('property-modal').classList.remove('active');
}

function savePropertyConfig() {
    const title = document.getElementById('modal-title').textContent;
    const propName = title.split(': ')[1];
    const prop = state.properties.find(p => p.name === propName && p.parentSM === state.activeSM);
    if (prop) {
        const sourceConfig = collectProtocolConfig();
        const required = { modbus: 'register', http: 'url', opcua: 'serverUrl', mqtt: 'topic' };
        if (required[currentProtocol] && !sourceConfig[required[currentProtocol]]) {
            return alert(`Bitte "${required[currentProtocol]}" ausfüllen.`);
        }
        prop.status = 'Configured';
        prop.connection = { modbus: 'Modbus TCP', mqtt: 'MQTT', http: 'HTTP/REST', opcua: 'OPC-UA' }[currentProtocol] || currentProtocol;
        prop.config = {
            protocol: currentProtocol,
            source: sourceConfig,
            targetData: collectTargetData(),
            sinks: collectSinkConfig()
        };
    }
    closeModal();
    renderProperties();
}


function renderProperties() {
    const container = document.getElementById('property-table-body');
    if (!container) return;
    container.innerHTML = '';

    const filtered = state.properties.filter(p => p.parentSM === state.activeSM);
    filtered.forEach(p => {
        const tr = document.createElement('tr');
        const isConfigured = p.status === 'Configured';
        tr.innerHTML = `
            <td><input type="checkbox" checked></td>
            <td>${p.name}</td>
            <td>${p.type}</td>
            <td>${p.connection}</td>
            <td onclick="openPropertyConfigModal('${p.name}')" style="cursor: pointer;">
                <span class="${isConfigured ? 'status-configured' : 'status-pending'}">
                    ${isConfigured ? 'Configured' : 'Edit...'}
                </span>
                <i data-feather="edit-2" style="width: 12px; height: 12px; margin-left: 5px; opacity: 0.5;"></i>
            </td>
        `;
        container.appendChild(tr);
    });
    feather.replace();
}

// Logic: Deployment
function uploadAASToServer(btn) {
    const name = document.getElementById('assetName').value.trim();
    if (!name) return alert('Enter Asset Name in Step 1.');

    // Save current Properties page config before building payload
    savePropConfig();

    const originalText = btn.textContent;
    btn.textContent = 'Generating...';
    btn.disabled = true;

    const data = {
        asset: { name: name, id: document.getElementById('assetId').value },
        generateIDTA:           document.getElementById('generate-idta-checkbox')?.checked ?? false,
        influxAuto:             document.getElementById('influx-auto-checkbox')?.checked ?? false,
        grafanaAuto:            document.getElementById('grafana-auto-checkbox')?.checked ?? false,
        deployCustomDataBridge: false,
        submodels: state.submodels.map(s => {
            const cfg = state.submodelConfigs[s] || {};
            // Only emit protocols with at least one DataPoint. Otherwise
            // tab-state defaults (default broker, etc.) leak into the AAS
            // and produce phantom protocol blocks the user never selected.
            const protocols = {};
            for (const [proto, pd] of Object.entries(cfg.protocolData || {})) {
                const hasRows = pd.targetData && pd.targetData.length > 0;
                if (hasRows) {
                    protocols[proto] = { source: pd.source || {}, targetData: pd.targetData };
                }
            }
            return {
                name: s,
                config: {
                    activeProtocol: cfg.protocol || 'modbus',
                    protocols: protocols,
                    sinks: cfg.sinks || {}
                }
            };
        })
    };

    fetch('/api/create_aas', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    })
        .then(r => r.json())
        .then(json => {
            const resultEl = document.getElementById('deploy-result-section');

            // Build details lines
            const lines = [];
            const idta = json?.idta;
            if (idta && !idta.error) {
                const gen = idta.generated ?? 0;
                const upl = idta.uploaded ?? 0;
                const v   = idta.validation || {};
                lines.push(`IDTA Submodels: ${gen} generated, ${upl} uploaded — Validation: ${v.passed ?? '?'}/${v.total ?? '?'} passed`);
            } else if (idta?.error) {
                lines.push(`IDTA warning: ${idta.error}`);
            }
            const grf = json?.grafana;
            if (grf?.fullUrl || grf?.url) {
                lines.push(`Grafana dashboard: <a href="${grf.fullUrl || grf.url}" target="_blank" style="color:var(--accent-primary)">${grf.fullUrl || grf.url}</a>`);
            }

            // Build link buttons
            const linkBtns = [];
            if (json.aasUrl) {
                linkBtns.push(`<a href="${json.aasUrl}" target="_blank" class="btn btn-secondary" style="text-decoration:none;">Open AAS in BaSyx Web UI</a>`);
            }
            if (json.containerManagerUrl) {
                linkBtns.push(`<a href="${json.containerManagerUrl}" target="_blank" class="btn btn-secondary" style="text-decoration:none;">Open Container Manager</a>`);
            }
            linkBtns.push(`<a href="/api/download_aas" class="btn btn-primary" style="text-decoration:none;">Download AASX</a>`);

            resultEl.style.display = 'block';
            resultEl.innerHTML = `
                <div class="card" style="border-color:rgba(79,142,247,0.3);background:rgba(79,142,247,0.05);">
                    <p style="font-weight:600;margin-bottom:0.6rem;">AAS deployed successfully.</p>
                    ${lines.length ? `<p style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:0.75rem;">${lines.join('<br>')}</p>` : ''}
                    <div style="display:flex;gap:0.75rem;flex-wrap:wrap;">
                        ${linkBtns.join('')}
                    </div>
                </div>`;
            resultEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        })
        .catch(err => alert('Error: ' + err))
        .finally(() => {
            btn.textContent = originalText;
            btn.disabled = false;
        });
}

function selectDeployment(mode, card) {
    state.deploymentMode = mode;
    document.querySelectorAll('.deployment-option').forEach(c => c.classList.remove('selected'));
    card.classList.add('selected');
    document.getElementById('btn-deploy-bridge').textContent =
        `Deploy ${mode === 'official' ? 'Official BaSyx' : 'Custom'} DataBridge`;
    renderPropSinkConfig(state.globalSinks);
}

function executeBridgeDeployment() {
    const btn = document.getElementById('btn-deploy-bridge');
    const originalText = btn.textContent;
    btn.textContent = 'Deploying…';
    btn.disabled = true;

    const endpoint = state.deploymentMode === 'official'
        ? '/api/deploy_official_databridge'
        : '/api/deploy_databridge';

    fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: state.deploymentMode })
    })
        .then(r => r.json())
        .then(res => {
            const icon = res.status === 'success' ? '✅' : '❌';
            let msg = icon + ' ' + res.message;
            if (res.log) msg += '\n\n--- Log ---\n' + res.log.slice(-2000);
            alert(msg);
        })
        .catch(err => alert('Deployment Error: ' + err))
        .finally(() => {
            btn.textContent = originalText;
            btn.disabled = false;
        });
}

function downloadDatabridgeConfig(btn) {
    const orig = btn.textContent;
    btn.textContent = 'Generating…';
    btn.disabled = true;
    _suppressUnload = true;
    window.location.href = '/api/download_databridge_config';
    setTimeout(() => { btn.textContent = orig; btn.disabled = false; _suppressUnload = false; }, 3000);
}

function deployContainerManager(btn) {
    const orig = btn.innerHTML;
    btn.innerHTML = '<i data-feather="loader"></i> Deploying…';
    btn.disabled = true;
    feather.replace();
    const resultEl = document.getElementById('container-manager-result');
    resultEl.style.display = 'none';

    fetch('/api/deploy_container_manager', { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            btn.innerHTML = orig;
            btn.disabled = false;
            feather.replace();
            resultEl.style.display = 'block';
            if (data.status === 'success') {
                const link = data.aasUrl
                    ? `<br><a href="${data.aasUrl}" target="_blank" style="color:var(--accent)">Im BaSyx Web UI öffnen →</a>`
                    : '';
                resultEl.innerHTML = `<div class="alert alert-success" style="margin:0;">
                    ✅ ContainerManager AAS deployed.${link}
                </div>`;
            } else {
                resultEl.innerHTML = `<div class="alert alert-error" style="margin:0;">
                    ❌ Fehler: ${data.message || 'Unbekannt'}
                </div>`;
            }
        })
        .catch(err => {
            btn.innerHTML = orig;
            btn.disabled = false;
            feather.replace();
            resultEl.style.display = 'block';
            resultEl.innerHTML = `<div class="alert alert-error" style="margin:0;">❌ ${err}</div>`;
        });
}

// ─── localStorage Persistence ────────────────────────────────────────────────

function saveToStorage() {
    try {
        sessionStorage.setItem('aas_gui_state', JSON.stringify({
            assetInfo: state.assetInfo,
            submodels: state.submodels,
            activeSM: state.activeSM,
            submodelConfigs: state.submodelConfigs,
            deploymentMode: state.deploymentMode,
            globalSinks: state.globalSinks
        }));
    } catch (e) { }
}

function loadFromStorage() {
    try {
        const saved = sessionStorage.getItem('aas_gui_state');
        if (!saved) return;
        const data = JSON.parse(saved);
        if (data.assetInfo) state.assetInfo = data.assetInfo;
        if (data.submodels) state.submodels = data.submodels;
        if (data.activeSM) state.activeSM = data.activeSM;
        if (data.submodelConfigs) state.submodelConfigs = data.submodelConfigs;
        if (data.deploymentMode) state.deploymentMode = data.deploymentMode;
        if (data.globalSinks) state.globalSinks = data.globalSinks;
    } catch (e) { }
}

let _suppressUnload = false;

window.addEventListener('beforeunload', (e) => {
    if (_suppressUnload) return;
    e.preventDefault();
});

// ─── Enter-Taste Navigation ───────────────────────────────────────────────────
// Drückt man Enter in einem Input-Feld, geht es automatisch zum nächsten Schritt
document.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    const tag = document.activeElement?.tagName;
    if (tag === 'TEXTAREA' || tag === 'SELECT' || tag === 'BUTTON') return;

    const step = state.currentStep;

    if (step === 1) {
        e.preventDefault();
        nextStep(2);
    } else if (step === 2) {
        // Enter im Submodel-Name-Input → Submodel hinzufügen
        if (document.activeElement?.id === 'newSubmodelName') {
            e.preventDefault();
            addNewSubmodel();
        } else {
            e.preventDefault();
            showStep(3);
        }
    }
    // In Schritt 3 und 4 kein automatisches Weiter, da viele Felder vorhanden
});

// Init
// ── Connection Settings ───────────────────────────────────────────────
const _PORT_KEYS = ['aas','aas_registry','sm_registry','discovery',
                    'orchestrator','influxdb','mqtt','grafana','ui'];

let _connDefaults = null;

async function loadConnection() {
    try {
        const r = await fetch('/api/connection');
        const j = await r.json();
        _connDefaults = j.defaults;
        // Populate fields
        const data = j.data || {};
        document.getElementById('conn-host').value = data.host || '';
        for (const k of _PORT_KEYS) {
            const el = document.getElementById(`port-${k}`);
            if (el) el.value = (data.ports || {})[k] ?? '';
        }
        // Update nav badge
        const lbl = document.getElementById('conn-host-label');
        if (lbl) lbl.textContent = data.host ? data.host : 'Connection';
        // First-time auto-open
        if (!j.configured) openConnectionDialog();
    } catch (e) {
        console.error('loadConnection failed', e);
    }
}

function openConnectionDialog() {
    document.getElementById('connection-modal').classList.add('active');
    feather.replace();
}
function closeConnectionDialog() {
    document.getElementById('connection-modal').classList.remove('active');
}
function resetConnectionDefaults() {
    if (!_connDefaults) return;
    document.getElementById('conn-host').value = _connDefaults.host || 'localhost';
    for (const k of _PORT_KEYS) {
        const el = document.getElementById(`port-${k}`);
        if (el) el.value = _connDefaults.ports[k] ?? '';
    }
}
async function saveConnectionSettings() {
    const host = document.getElementById('conn-host').value.trim();
    const ports = {};
    for (const k of _PORT_KEYS) {
        const el = document.getElementById(`port-${k}`);
        if (el && el.value !== '') ports[k] = parseInt(el.value, 10);
    }
    try {
        const r = await fetch('/api/connection', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({host, ports}),
        });
        const j = await r.json();
        if (j.status === 'success') {
            const lbl = document.getElementById('conn-host-label');
            if (lbl) lbl.textContent = j.data.host || 'Connection';
            closeConnectionDialog();
        } else {
            alert('Save failed: ' + (j.message || 'unknown'));
        }
    } catch (e) {
        alert('Save failed: ' + e);
    }
}

function downloadTemplate(proto) {
    window.location.href = '/api/download_template/' + proto;
}

document.addEventListener('DOMContentLoaded', () => {
    loadFromStorage();
    loadConnection();

    // Restore Step 1 fields
    if (state.assetInfo.name) document.getElementById('assetName').value = state.assetInfo.name;
    if (state.assetInfo.id) document.getElementById('assetId').value = state.assetInfo.id;
    if (state.assetInfo.desc) document.getElementById('assetDesc').value = state.assetInfo.desc;

    feather.replace();
    renderSubmodels();
});