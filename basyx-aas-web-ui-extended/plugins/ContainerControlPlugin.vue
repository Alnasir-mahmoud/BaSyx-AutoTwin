<template>
    <div class="container-control-plugin">
        <!-- Header -->
        <div class="plugin-header">
            <div class="header-info">
                <v-icon class="mr-2">mdi-docker</v-icon>
                <span class="container-name">{{ containerName }}</span>
                <v-chip class="ml-2" size="small" :color="getStatusColor()" variant="outlined">
                    {{ containerStatus }}
                </v-chip>
            </div>
            <div class="header-actions">
                <v-btn 
                    size="small" 
                    variant="outlined" 
                    @click="refreshStatus"
                    :disabled="loading"
                >
                    <v-icon>mdi-refresh</v-icon>
                    Aktualisieren
                </v-btn>
            </div>
        </div>

        <!-- Control Panel -->
        <div class="control-panel">
            <!-- Status Card -->
            <v-card class="mb-4" variant="outlined">
                <v-card-title class="d-flex align-center">
                    <v-icon class="mr-2">mdi-information</v-icon>
                    Container Status
                </v-card-title>
                <v-card-text>
                    <v-row>
                        <v-col cols="6" md="3">
                            <div class="text-caption">Status</div>
                            <v-chip :color="getStatusColor()" size="small">
                                {{ containerStatus }}
                            </v-chip>
                        </v-col>
                        <v-col cols="6" md="3">
                            <div class="text-caption">Container ID</div>
                            <div class="text-body-2 font-mono">{{ containerInfo.id || 'N/A' }}</div>
                        </v-col>
                        <v-col cols="6" md="3">
                            <div class="text-caption">Image</div>
                            <div class="text-body-2">{{ containerInfo.image || 'N/A' }}</div>
                        </v-col>
                        <v-col cols="6" md="3">
                            <div class="text-caption">Health</div>
                            <v-chip 
                                size="small" 
                                :color="getHealthColor()"
                                v-if="containerInfo.health"
                            >
                                {{ containerInfo.health.status }}
                            </v-chip>
                            <span v-else class="text-body-2">N/A</span>
                        </v-col>
                    </v-row>
                </v-card-text>
            </v-card>

            <!-- Action Buttons -->
            <v-card class="mb-4" variant="outlined">
                <v-card-title class="d-flex align-center">
                    <v-icon class="mr-2">mdi-play-circle</v-icon>
                    Container Steuerung
                </v-card-title>
                <v-card-text>
                    <v-row>
                        <v-col cols="12" md="4">
                            <v-btn 
                                block
                                color="success"
                                variant="outlined"
                                @click="startContainer"
                                :disabled="loading || containerStatus === 'running'"
                                :loading="actionLoading === 'start'"
                            >
                                <v-icon class="mr-2">mdi-play</v-icon>
                                Starten
                            </v-btn>
                        </v-col>
                        <v-col cols="12" md="4">
                            <v-btn 
                                block
                                color="error"
                                variant="outlined"
                                @click="stopContainer"
                                :disabled="loading || containerStatus !== 'running'"
                                :loading="actionLoading === 'stop'"
                            >
                                <v-icon class="mr-2">mdi-stop</v-icon>
                                Stoppen
                            </v-btn>
                        </v-col>
                        <v-col cols="12" md="4">
                            <v-btn 
                                block
                                color="warning"
                                variant="outlined"
                                @click="restartContainer"
                                :disabled="loading"
                                :loading="actionLoading === 'restart'"
                            >
                                <v-icon class="mr-2">mdi-restart</v-icon>
                                Neustart
                            </v-btn>
                        </v-col>
                    </v-row>
                </v-card-text>
            </v-card>

            <!-- Logs -->
            <v-card variant="outlined">
                <v-card-title class="d-flex align-center justify-space-between">
                    <div class="d-flex align-center">
                        <v-icon class="mr-2">mdi-text-box</v-icon>
                        Container Logs
                    </div>
                    <v-btn 
                        size="small"
                        variant="outlined"
                        @click="refreshLogs"
                        :disabled="loading"
                    >
                        <v-icon>mdi-refresh</v-icon>
                    </v-btn>
                </v-card-title>
                <v-card-text>
                    <div class="logs-container">
                        <pre class="logs-text" v-if="containerLogs">{{ containerLogs }}</pre>
                        <div v-else class="text-center text-grey">
                            Keine Logs verfügbar
                        </div>
                    </div>
                </v-card-text>
            </v-card>
        </div>

        <!-- Error/Success Messages -->
        <v-snackbar
            v-model="showMessage"
            :color="messageType"
            :timeout="4000"
        >
            {{ message }}
            <template v-slot:actions>
                <v-btn variant="text" @click="showMessage = false">
                    Schließen
                </v-btn>
            </template>
        </v-snackbar>
    </div>
</template>

<script lang="ts" setup>
import { defineOptions, onMounted, ref, computed } from 'vue';

// Plugin-Definition
defineOptions({
    name: 'ContainerControlPlugin',
    semanticId: 'https://example.com/plugins/container-control',
});

// Props
const props = defineProps({
    submodelElementData: {
        type: Object as any,
        default: {} as any,
    },
});

// Reactive Variables
const containerName = ref<string>('');
const containerStatus = ref<string>('unknown');
const containerInfo = ref<any>({});
const containerLogs = ref<string>('');
const loading = ref<boolean>(false);
const actionLoading = ref<string>('');
const showMessage = ref<boolean>(false);
const message = ref<string>('');
const messageType = ref<string>('info');

// API Base URL — use same hostname as the browser so the correct host IP
// is picked up automatically when accessed from an external machine.
const API_BASE = `http://${window.location.hostname}:8090`;

// Methods
function getStatusColor(): string {
    switch (containerStatus.value) {
        case 'running': return 'success';
        case 'exited': return 'error';
        case 'paused': return 'warning';
        case 'restarting': return 'info';
        default: return 'grey';
    }
}

function getHealthColor(): string {
    const health = containerInfo.value.health?.status;
    switch (health) {
        case 'healthy': return 'success';
        case 'unhealthy': return 'error';
        case 'starting': return 'warning';
        default: return 'grey';
    }
}

function showNotification(msg: string, type: string = 'info') {
    message.value = msg;
    messageType.value = type;
    showMessage.value = true;
}

async function apiRequest(endpoint: string, method: string = 'GET'): Promise<any> {
    try {
        const response = await fetch(`${API_BASE}${endpoint}`, {
            method,
            headers: {
                'Content-Type': 'application/json',
            },
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.error || 'API-Fehler');
        }
        
        return data;
    } catch (error) {
        console.error('API-Fehler:', error);
        throw error;
    }
}

async function refreshStatus() {
    if (!containerName.value) return;
    
    loading.value = true;
    try {
        const data = await apiRequest(`/containers/${containerName.value}/status`);
        
        if (data.error) {
            containerStatus.value = 'not found';
            containerInfo.value = {};
            showNotification(data.error, 'error');
        } else {
            containerStatus.value = data.status;
            containerInfo.value = data;
        }
    } catch (error) {
        showNotification('Fehler beim Abrufen des Status', 'error');
        containerStatus.value = 'error';
    } finally {
        loading.value = false;
    }
}

async function startContainer() {
    if (!containerName.value) return;
    
    actionLoading.value = 'start';
    try {
        const data = await apiRequest(`/containers/${containerName.value}/start`, 'POST');
        
        if (data.success) {
            showNotification(data.message, 'success');
            await refreshStatus();
        } else {
            showNotification(data.error, 'error');
        }
    } catch (error) {
        showNotification('Fehler beim Starten des Containers', 'error');
    } finally {
        actionLoading.value = '';
    }
}

async function stopContainer() {
    if (!containerName.value) return;
    
    actionLoading.value = 'stop';
    try {
        const data = await apiRequest(`/containers/${containerName.value}/stop`, 'POST');
        
        if (data.success) {
            showNotification(data.message, 'success');
            await refreshStatus();
        } else {
            showNotification(data.error, 'error');
        }
    } catch (error) {
        showNotification('Fehler beim Stoppen des Containers', 'error');
    } finally {
        actionLoading.value = '';
    }
}

async function restartContainer() {
    if (!containerName.value) return;
    
    actionLoading.value = 'restart';
    try {
        const data = await apiRequest(`/containers/${containerName.value}/restart`, 'POST');
        
        if (data.success) {
            showNotification(data.message, 'success');
            await refreshStatus();
        } else {
            showNotification(data.error, 'error');
        }
    } catch (error) {
        showNotification('Fehler beim Neustarten des Containers', 'error');
    } finally {
        actionLoading.value = '';
    }
}

async function refreshLogs() {
    if (!containerName.value) return;
    
    loading.value = true;
    try {
        const data = await apiRequest(`/containers/${containerName.value}/logs?lines=100`);
        
        if (data.success) {
            containerLogs.value = data.logs;
        } else {
            containerLogs.value = `Fehler beim Laden der Logs: ${data.error}`;
        }
    } catch (error) {
        containerLogs.value = 'Fehler beim Laden der Logs';
        showNotification('Fehler beim Laden der Logs', 'error');
    } finally {
        loading.value = false;
    }
}

async function initializePlugin() {
    if (!props.submodelElementData || Object.keys(props.submodelElementData).length === 0) {
        showNotification('Keine SubmodelElement-Daten verfügbar', 'error');
        return;
    }

    try {
        const data = props.submodelElementData;
        
        // Container-Name aus Property extrahieren
        if (data.modelType === 'Property' && data.value) {
            containerName.value = data.value;
        } else if (data.value && typeof data.value === 'string') {
            containerName.value = data.value;
        } else {
            throw new Error('Kein Container-Name in SubmodelElement gefunden');
        }
        
        // Initial Status laden
        await refreshStatus();
        await refreshLogs();
        
    } catch (err) {
        showNotification(err instanceof Error ? err.message : 'Fehler bei der Plugin-Initialisierung', 'error');
        console.error('Plugin-Initialisierung fehlgeschlagen:', err);
    }
}

// Lifecycle
onMounted(() => {
    initializePlugin();
});
</script>

<style scoped>
.container-control-plugin {
    max-width: 100%;
    margin: 0 auto;
}

.plugin-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 16px;
    background-color: #f5f5f5;
    border-radius: 8px 8px 0 0;
    border: 1px solid #e0e0e0;
}

.header-info {
    display: flex;
    align-items: center;
    flex: 1;
    min-width: 0;
}

.container-name {
    font-family: monospace;
    font-size: 16px;
    font-weight: bold;
    color: #333;
}

.header-actions {
    display: flex;
    gap: 8px;
    flex-shrink: 0;
}

.control-panel {
    padding: 16px;
    border: 1px solid #e0e0e0;
    border-top: none;
    border-radius: 0 0 8px 8px;
}

.font-mono {
    font-family: monospace;
}

.logs-container {
    max-height: 300px;
    overflow-y: auto;
    background-color: #f8f9fa;
    border-radius: 4px;
    padding: 12px;
}

.logs-text {
    font-family: monospace;
    font-size: 12px;
    line-height: 1.4;
    margin: 0;
    white-space: pre-wrap;
    word-wrap: break-word;
}

/* Dark Theme Support */
.v-theme--dark .plugin-header {
    background-color: #424242;
    border-color: #616161;
}

.v-theme--dark .control-panel {
    border-color: #616161;
}

.v-theme--dark .container-name {
    color: #fff;
}

.v-theme--dark .logs-container {
    background-color: #2d2d2d;
}

.v-theme--dark .logs-text {
    color: #e0e0e0;
}

/* Responsive Design */
@media (max-width: 768px) {
    .plugin-header {
        flex-direction: column;
        gap: 12px;
        align-items: stretch;
    }
    
    .header-info {
        justify-content: center;
    }
    
    .header-actions {
        justify-content: center;
    }
}
</style>

