<template>
    <div class="web-iframe-container">
        <div class="iframe-header">
            <div class="url-info">
                <v-icon class="mr-2">mdi-web</v-icon>
                <span class="url-text">{{ displayUrl }}</span>
                <v-chip class="ml-2" size="small" :color="getStatusColor()" variant="outlined">
                    {{ connectionStatus }}
                </v-chip>
            </div>
            <div class="iframe-actions">
                <v-btn size="small" variant="outlined" @click="refreshIframe" :disabled="loading">
                    <v-icon>mdi-refresh</v-icon>
                    Aktualisieren
                </v-btn>
                <v-btn size="small" variant="outlined" @click="openInNewTab" class="ml-2">
                    <v-icon>mdi-open-in-new</v-icon>
                    Neuer Tab
                </v-btn>
                <v-btn size="small" variant="outlined" @click="toggleFullscreen" class="ml-2">
                    <v-icon>{{ isFullscreen ? 'mdi-fullscreen-exit' : 'mdi-fullscreen' }}</v-icon>
                </v-btn>
            </div>
        </div>

        <div class="iframe-wrapper" :class="{ 'fullscreen': isFullscreen }">
            <div v-if="loading" class="loading-overlay">
                <v-progress-circular indeterminate color="primary" size="64"></v-progress-circular>
                <p class="mt-3">{{ loadingMessage }}</p>
            </div>

            <div v-else-if="error" class="error-container">
                <v-alert type="error" variant="outlined" class="ma-4">
                    <v-alert-title>Verbindungsfehler</v-alert-title>
                    <div>{{ error }}</div>
                    <template v-slot:append>
                        <v-btn variant="outlined" size="small" @click="retryConnection">
                            Erneut versuchen
                        </v-btn>
                    </template>
                </v-alert>
            </div>

            <iframe
                v-show="!error"
                ref="iframeElement"
                :src="iframeUrl"
                :style="iframeStyle"
                @load="onIframeLoad"
                @error="onIframeError"
                frameborder="0"
                allowfullscreen
                :sandbox="getSandboxAttributes()"
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
            ></iframe>
        </div>
    </div>
</template>

<script lang="ts" setup>
import { defineOptions, onMounted, ref, computed, onUnmounted } from 'vue';

defineOptions({
    name: 'WebIframeViewer',
    semanticId: 'https://example.com/plugins/web-iframe-viewer',
});

const props = defineProps({
    submodelElementData: {
        type: Object as any,
        default: {} as any,
    },
});

const iframeUrl = ref<string>('');
const displayUrl = ref<string>('');
const loading = ref<boolean>(false);
const error = ref<string>('');
const connectionStatus = ref<string>('Nicht verbunden');
const loadingMessage = ref<string>('Lade Webseite...');
const isFullscreen = ref<boolean>(false);
const loadTime = ref<number>(0);
const lastUpdate = ref<string>('');
const iframeElement = ref<HTMLIFrameElement>();
const loadStartTime = ref<number>(0);

const iframeStyle = computed(() => ({
    width: '100%',
    height: isFullscreen.value ? '100vh' : '600px',
    border: 'none',
    borderRadius: '0 0 8px 8px',
}));

function getSandboxAttributes(): string {
    return 'allow-same-origin allow-scripts allow-forms allow-popups allow-top-navigation';
}

function getStatusColor(): string {
    switch (connectionStatus.value) {
        case 'Verbunden': return 'success';
        case 'Fehler': return 'error';
        case 'Lädt': return 'warning';
        default: return 'grey';
    }
}

function refreshIframe() {
    if (iframeElement.value) {
        loading.value = true;
        connectionStatus.value = 'Lädt';
        loadingMessage.value = 'Seite wird neu geladen...';
        const url = new URL(iframeUrl.value);
        url.searchParams.set('_t', Date.now().toString());
        iframeElement.value.src = url.toString();
        setTimeout(() => {
            if (loading.value) {
                loading.value = false;
                error.value = 'Timeout: Seite konnte nicht geladen werden';
                connectionStatus.value = 'Fehler';
            }
        }, 30000);
    }
}

function openInNewTab() {
    if (iframeUrl.value) {
        const url = new URL(iframeUrl.value);
        if (url.hostname.includes('grafana') || url.port === '3001') {
            url.searchParams.set('kiosk', 'tv');
            url.searchParams.set('refresh', '5s');
        }
        window.open(url.toString(), '_blank');
    }
}

function toggleFullscreen() {
    isFullscreen.value = !isFullscreen.value;
    if (isFullscreen.value) {
        document.body.style.overflow = 'hidden';
    } else {
        document.body.style.overflow = '';
    }
}

function onIframeLoad() {
    loading.value = false;
    error.value = '';
    connectionStatus.value = 'Verbunden';
    loadTime.value = Date.now() - loadStartTime.value;
    lastUpdate.value = new Date().toLocaleTimeString('de-DE');
}

function onIframeError() {
    loading.value = false;
    error.value = 'Die Webseite konnte nicht geladen werden.';
    connectionStatus.value = 'Fehler';
}

function retryConnection() {
    error.value = '';
    loadWebInterface(iframeUrl.value);
}

function normalizeUrl(url: string): string {
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
        url = 'http://' + url;
    }
    try {
        const urlObj = new URL(url);
        if (urlObj.hostname.includes('grafana') || urlObj.port === '3001') {
            urlObj.searchParams.set('orgId', '1');
            urlObj.searchParams.set('refresh', '5s');
            urlObj.searchParams.set('timezone', 'browser');
            if (!urlObj.searchParams.has('kiosk')) {
                urlObj.searchParams.set('kiosk', 'tv');
            }
        }
        return urlObj.toString();
    } catch {
        throw new Error('Ungültige URL-Format');
    }
}

async function loadWebInterface(url: string) {
    if (!url) {
        error.value = 'Keine URL verfügbar';
        return;
    }
    error.value = '';
    connectionStatus.value = 'Lädt';
    loadingMessage.value = 'Verbinde mit Webservice...';
    loadStartTime.value = Date.now();
    try {
        const normalizedUrl = normalizeUrl(url);
        iframeUrl.value = normalizedUrl;
        displayUrl.value = normalizedUrl;
    } catch (err) {
        error.value = err instanceof Error ? err.message : 'Unbekannter Fehler';
        connectionStatus.value = 'Fehler';
    }
}

async function initializePlugin() {
    if (!props.submodelElementData || Object.keys(props.submodelElementData).length === 0) {
        error.value = 'Keine SubmodelElement-Daten verfügbar';
        return;
    }
    try {
        const data = props.submodelElementData;
        let url = '';
        if (data.modelType === 'Property' && data.value) {
            url = data.value;
        } else if (data.value && typeof data.value === 'string') {
            url = data.value;
        } else {
            throw new Error('Keine URL in SubmodelElement gefunden');
        }
        await loadWebInterface(url);
    } catch (err) {
        error.value = err instanceof Error ? err.message : 'Fehler bei der Plugin-Initialisierung';
    }
}

onMounted(() => {
    initializePlugin();
});

onUnmounted(() => {
    if (isFullscreen.value) {
        document.body.style.overflow = '';
    }
});
</script>

<style scoped>
.web-iframe-container { max-width: 100%; margin: 0 auto; }
.iframe-header { display: flex; justify-content: space-between; align-items: center; padding: 16px; background-color: #f5f5f5; border-radius: 8px 8px 0 0; border: 1px solid #e0e0e0; }
.url-info { display: flex; align-items: center; flex: 1; min-width: 0; }
.url-text { font-family: monospace; font-size: 14px; color: #666; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 300px; }
.iframe-actions { display: flex; gap: 8px; flex-shrink: 0; }
.iframe-wrapper { position: relative; border: 1px solid #e0e0e0; border-top: none; border-radius: 0 0 8px 8px; overflow: hidden; }
.iframe-wrapper.fullscreen { position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; z-index: 9999; border-radius: 0; border: none; background: white; }
.loading-overlay { position: absolute; top: 0; left: 0; right: 0; bottom: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; background-color: rgba(255, 255, 255, 0.9); z-index: 10; }
.error-container { min-height: 200px; display: flex; align-items: center; justify-content: center; }
.v-theme--dark .iframe-header { background-color: #424242; border-color: #616161; }
.v-theme--dark .iframe-wrapper { border-color: #616161; }
.v-theme--dark .loading-overlay { background-color: rgba(66, 66, 66, 0.9); }
.v-theme--dark .url-text { color: #bbb; }
.v-theme--dark .iframe-wrapper.fullscreen { background: #121212; }
</style>
