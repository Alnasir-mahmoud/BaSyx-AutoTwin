<template>
    <div class="grafana-panel-container">
        <div class="panel-header">
            <div class="panel-info">
                <v-icon class="mr-2" color="orange">mdi-chart-line</v-icon>
                <span class="panel-title">{{ panelTitle }}</span>
                <v-chip class="ml-2" size="small" color="orange" variant="outlined">
                    <v-icon size="small" class="mr-1">mdi-chart-box</v-icon>
                    Grafana Panel
                </v-chip>
                <v-chip v-if="connectionStatus" class="ml-2" size="small"
                        :color="getStatusColor()" variant="outlined">
                    {{ connectionStatus }}
                </v-chip>
            </div>
            <div class="panel-actions">
                <v-select
                    v-model="selectedTimeRange"
                    :items="timeRanges"
                    item-title="label"
                    item-value="value"
                    density="compact"
                    variant="outlined"
                    hide-details
                    style="width: 140px;"
                    @update:model-value="rebuild">
                    <template v-slot:prepend-inner>
                        <v-icon size="small">mdi-clock-outline</v-icon>
                    </template>
                </v-select>
                <v-select
                    v-model="refreshInterval"
                    :items="refreshIntervals"
                    item-title="label"
                    item-value="value"
                    density="compact"
                    variant="outlined"
                    hide-details
                    style="width: 110px;"
                    class="ml-2"
                    @update:model-value="rebuild">
                    <template v-slot:prepend-inner>
                        <v-icon size="small">mdi-refresh</v-icon>
                    </template>
                </v-select>
                <v-btn size="small" variant="outlined" @click="refresh"
                       :disabled="loading" class="ml-2" title="Aktualisieren">
                    <v-icon>mdi-refresh</v-icon>
                </v-btn>
                <v-btn size="small" variant="outlined" @click="toggleTheme"
                       class="ml-2" :title="isDarkTheme ? 'Hell' : 'Dunkel'">
                    <v-icon>{{ isDarkTheme ? 'mdi-weather-sunny' : 'mdi-weather-night' }}</v-icon>
                </v-btn>
                <v-btn size="small" variant="outlined" @click="toggleFullscreen"
                       class="ml-2" :title="kioskMode ? 'Verkleinern' : 'Vollbild'">
                    <v-icon>{{ kioskMode ? 'mdi-fullscreen-exit' : 'mdi-fullscreen' }}</v-icon>
                </v-btn>
                <v-btn size="small" variant="outlined" @click="openExternal"
                       class="ml-2" title="In Grafana öffnen">
                    <v-icon>mdi-open-in-new</v-icon>
                </v-btn>
            </div>
        </div>

        <div class="panel-wrapper" :class="{ 'kiosk-mode': kioskMode }">
            <div v-if="loading" class="loading-overlay">
                <v-progress-circular indeterminate color="orange" size="64"></v-progress-circular>
                <p class="mt-3">{{ loadingMessage }}</p>
            </div>
            <div v-else-if="error" class="error-container">
                <v-alert type="error" variant="outlined" class="ma-4">
                    <v-alert-title>Grafana Panel Fehler</v-alert-title>
                    <div>{{ error }}</div>
                    <template v-slot:append>
                        <v-btn variant="outlined" size="small" @click="retry">
                            Erneut versuchen
                        </v-btn>
                    </template>
                </v-alert>
            </div>
            <iframe
                v-show="!error"
                ref="iframeEl"
                :src="iframeSrc"
                :style="iframeStyle"
                @load="onLoad"
                @error="onError"
                frameborder="0"
                allowfullscreen
                sandbox="allow-same-origin allow-scripts allow-forms allow-popups allow-top-navigation"
            ></iframe>
        </div>
    </div>
</template>

<script lang="ts" setup>
import { defineOptions, onMounted, ref, computed, onUnmounted, watch } from 'vue';

defineOptions({
    name: 'GrafanaDashboardViewer',
    semanticId: 'https://mein-unternehmen.de/grafana-plugin',
});

const props = defineProps({
    submodelElementData: {
        type: Object as any,
        default: {} as any,
    },
});

// ─── Parsed input URL state ──────────────────────────────────────────
const baseUrl       = ref<string>('');
const dashboardUid  = ref<string>('');
const dashboardSlug = ref<string>('');
const panelId       = ref<string>('');
const orgId         = ref<string>('1');

// ─── User-controlled state ───────────────────────────────────────────
const selectedTimeRange = ref<string>('now-15m');
const refreshInterval   = ref<string>('5s');
const isDarkTheme       = ref<boolean>(false);
const kioskMode         = ref<boolean>(false);
const refreshKey        = ref<number>(0);

// ─── UI state ────────────────────────────────────────────────────────
const loading           = ref<boolean>(true);
const error             = ref<string>('');
const connectionStatus  = ref<string>('Lädt');
const loadingMessage    = ref<string>('Verbinde mit Grafana...');
const iframeEl          = ref<HTMLIFrameElement>();

const timeRanges = [
    { label: 'Letzte 5m',   value: 'now-5m' },
    { label: 'Letzte 15m',  value: 'now-15m' },
    { label: 'Letzte 30m',  value: 'now-30m' },
    { label: 'Letzte 1h',   value: 'now-1h' },
    { label: 'Letzte 3h',   value: 'now-3h' },
    { label: 'Letzte 6h',   value: 'now-6h' },
    { label: 'Letzte 24h',  value: 'now-24h' },
    { label: 'Letzte 7d',   value: 'now-7d' },
    { label: 'Letzte 30d',  value: 'now-30d' },
];

const refreshIntervals = [
    { label: 'Aus',  value: '' },
    { label: '5s',   value: '5s' },
    { label: '10s',  value: '10s' },
    { label: '30s',  value: '30s' },
    { label: '1m',   value: '1m' },
    { label: '5m',   value: '5m' },
    { label: '15m',  value: '15m' },
];

const panelTitle = computed(() => {
    const sm = props.submodelElementData;
    // Use the wrapping property's idShort when available — that's the
    // datapoint name (e.g. "BatterySoc"). Fall back to "Panel #N".
    if (sm && sm.idShort && sm.idShort !== 'Dashboard') return sm.idShort;
    return panelId.value ? `Panel #${panelId.value}` : 'Live Panel';
});

const iframeStyle = computed(() => ({
    width: '100%',
    height: kioskMode.value ? '100vh' : '500px',
    border: 'none',
    borderRadius: kioskMode.value ? '0' : '0 0 8px 8px',
    background: '#111',
}));

// ─── URL handling ─────────────────────────────────────────────────────
//
// Parse any Grafana URL — full dashboard ``/d/<uid>/<slug>?...`` or
// solo-panel ``/d-solo/<uid>?panelId=N`` — and pull out the parts we
// need to rebuild it as a single-panel embed.

function parse(rawUrl: string) {
    const u = new URL(rawUrl);
    const parts = u.pathname.split('/').filter(Boolean);
    const dIdx = parts.findIndex(p => p === 'd' || p === 'd-solo');
    baseUrl.value       = `${u.protocol}//${u.host}`;
    dashboardUid.value  = (dIdx !== -1 && parts[dIdx + 1]) ? parts[dIdx + 1] : '';
    dashboardSlug.value = (dIdx !== -1 && parts[dIdx + 2]) ? parts[dIdx + 2] : '';
    orgId.value         = u.searchParams.get('orgId') || '1';
    // Both ``panelId`` (solo URL) and ``viewPanel`` (full-dash zoom URL)
    // identify the same thing — take whichever is present.
    panelId.value =
        u.searchParams.get('panelId') ||
        u.searchParams.get('viewPanel') ||
        '';
    if (!dashboardUid.value) {
        throw new Error('Keine Dashboard-UID in URL gefunden');
    }
}

function buildSoloUrl(): string {
    // Always render single-panel via /d-solo/ — that's the whole point
    // of this plugin's binding to a SubmodelElement that represents one
    // signal.
    if (!dashboardUid.value || !panelId.value) {
        throw new Error(
            'Kein panelId in der Dashboard-URL — solo-Embedding nicht möglich.'
        );
    }
    const params = new URLSearchParams();
    params.set('orgId',   orgId.value);
    params.set('panelId', panelId.value);
    params.set('from',    selectedTimeRange.value);
    params.set('to',      'now');
    if (refreshInterval.value) params.set('refresh', refreshInterval.value);
    params.set('theme',   isDarkTheme.value ? 'dark' : 'light');
    if (refreshKey.value) params.set('_t', String(refreshKey.value));
    return `${baseUrl.value}/d-solo/${dashboardUid.value}?${params.toString()}`;
}

const iframeSrc = computed(() => {
    try { return buildSoloUrl(); } catch { return ''; }
});

// ─── Actions ──────────────────────────────────────────────────────────
function rebuild() {
    connectionStatus.value = 'Lädt';
    loadingMessage.value   = 'Panel wird aktualisiert...';
    refreshKey.value = Date.now();
}
function refresh()         { rebuild(); }
function toggleTheme()     { isDarkTheme.value = !isDarkTheme.value; rebuild(); }
function toggleFullscreen() {
    kioskMode.value = !kioskMode.value;
    document.body.style.overflow = kioskMode.value ? 'hidden' : '';
}
function openExternal() {
    // Open the full dashboard (with this panel zoomed-in) in a new tab.
    if (!dashboardUid.value) return;
    const params = new URLSearchParams();
    params.set('orgId', orgId.value);
    if (panelId.value) params.set('viewPanel', panelId.value);
    params.set('from', selectedTimeRange.value);
    params.set('to', 'now');
    const slug = dashboardSlug.value ? `/${dashboardSlug.value}` : '';
    window.open(
        `${baseUrl.value}/d/${dashboardUid.value}${slug}?${params.toString()}`,
        '_blank',
    );
}
function retry() {
    error.value = '';
    initializePlugin();
}

function onLoad() {
    loading.value = false;
    error.value   = '';
    connectionStatus.value = 'Verbunden';
}
function onError() {
    loading.value = false;
    error.value   = 'Panel konnte nicht geladen werden.';
    connectionStatus.value = 'Fehler';
}

function getStatusColor(): string {
    switch (connectionStatus.value) {
        case 'Verbunden': return 'success';
        case 'Fehler':    return 'error';
        case 'Lädt':      return 'warning';
        default:          return 'grey';
    }
}

// ─── Init ────────────────────────────────────────────────────────────
function initializePlugin() {
    const data = props.submodelElementData;
    if (!data || Object.keys(data).length === 0) {
        error.value = 'Keine SubmodelElement-Daten verfügbar';
        return;
    }
    let url = '';
    if (data.modelType === 'Property' && data.value) url = data.value;
    else if (typeof data.value === 'string')         url = data.value;
    if (!url) {
        error.value = 'Keine Grafana-URL im SubmodelElement gefunden';
        return;
    }
    try {
        parse(url);
        loading.value = true;
        connectionStatus.value = 'Lädt';
    } catch (err) {
        error.value = err instanceof Error ? err.message : String(err);
        connectionStatus.value = 'Fehler';
    }
}

onMounted(() => {
    initializePlugin();
});
onUnmounted(() => {
    if (kioskMode.value) document.body.style.overflow = '';
});

// Re-parse if the bound element changes (BaSyx UI may reuse the plugin
// instance across selections).
watch(() => props.submodelElementData, () => initializePlugin(), {
    deep: true,
});
</script>

<style scoped>
.grafana-panel-container { max-width: 100%; margin: 0 auto; }
.panel-header {
    display: flex; justify-content: space-between; align-items: center;
    padding: 12px 16px;
    background: linear-gradient(135deg, #ff9800 0%, #f57c00 100%);
    color: white;
    border-radius: 8px 8px 0 0;
    flex-wrap: wrap;
    gap: 12px;
}
.panel-info { display: flex; align-items: center; flex: 1; min-width: 0; }
.panel-title { font-weight: 600; font-size: 16px; }
.panel-actions { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.panel-wrapper {
    position: relative;
    border: 1px solid #e0e0e0;
    border-top: none;
    border-radius: 0 0 8px 8px;
    overflow: hidden;
    transition: all 0.2s ease;
}
.panel-wrapper.kiosk-mode {
    position: fixed; top: 0; left: 0; width: 100vw; height: 100vh;
    z-index: 9999; border-radius: 0; border: none;
}
.loading-overlay {
    position: absolute; inset: 0;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    background: rgba(255, 152, 0, 0.08);
    z-index: 10;
}
.error-container { min-height: 200px; display: flex; align-items: center; justify-content: center; }
</style>
