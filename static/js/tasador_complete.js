// Sistema completo de análisis catastral
const AppState = {
    currentRef: null,
    batchFile: null,
    kmlFiles: [],
    analysisResults: [],
    isProcessing: false
};

const UI = {
    log(msg, type = 'info') {
        const panel = document.getElementById('log-panel');
        if (!panel) return;
        const entry = document.createElement('div');
        entry.className = `log-entry log-${type}`;
        entry.innerHTML = `<span class="log-time">[${new Date().toLocaleTimeString()}]</span> ${msg}`;
        panel.prepend(entry);
    },

    updateStatus(message, type = 'info') {
        const badge = document.getElementById('status-badge');
        if (badge) {
            badge.textContent = message;
            badge.className = `badge badge-${type}`;
        }
    }
};

// Tabs functionality
function switchTab(tabName) {
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
    
    event.target.classList.add('active');
    document.getElementById(`tab-${tabName}`).classList.add('active');
}

// Análisis individual
async function analyzeSingle() {
    const ref = document.getElementById('ref-input').value.trim();
    if (!ref) {
        UI.log('⚠️ Introduce una referencia catastral', 'warning');
        return;
    }

    AppState.currentRef = ref;
    UI.log(`🔍 Analizando referencia: ${ref}`);
    UI.updateStatus('Procesando...', 'warning');

    try {
        const response = await fetch('/api/catastro/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ referencia: ref })
        });

        const data = await response.json();
        if (data.status === 'success') {
            UI.log(`✅ Análisis completado: ${data.analisis.resumen.capas_afectan} capas afectan`, 'success');
            updateResultsTable([data]);
            UI.updateStatus('Análisis completado', 'success');
        }
    } catch (error) {
        UI.log(`❌ Error: ${error.message}`, 'error');
        UI.updateStatus('Error', 'danger');
    }
}

// Procesamiento por lotes
function handleBatchFile(input) {
    const file = input.files[0];
    if (!file) return;

    AppState.batchFile = file;
    document.getElementById('batch-file-name').textContent = file.name;
    document.getElementById('batch-file-size').textContent = (file.size / 1024).toFixed(1) + ' KB';
    document.getElementById('batch-file-info').classList.remove('hidden');
    document.getElementById('btn-process-batch').disabled = false;
}

function clearBatchFile() {
    AppState.batchFile = null;
    document.getElementById('batch-file-input').value = '';
    document.getElementById('batch-file-info').classList.add('hidden');
    document.getElementById('btn-process-batch').disabled = true;
}

async function processBatch() {
    if (!AppState.batchFile) return;

    const text = await AppState.batchFile.text();
    const references = text.split('\n').filter(line => line.trim()).map(line => line.trim());
    
    if (references.length === 0) {
        UI.log('⚠️ El archivo no contiene referencias válidas', 'warning');
        return;
    }

    UI.log(`📋 Iniciando procesamiento de ${references.length} referencias`);
    document.getElementById('batch-progress').classList.remove('hidden');
    document.getElementById('batch-results').classList.remove('hidden');

    const results = [];
    for (let i = 0; i < references.length; i++) {
        const ref = references[i];
        updateBatchProgress(i + 1, references.length, ref);
        
        try {
            const response = await fetch('/api/catastro/query', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ referencia: ref })
            });
            
            const data = await response.json();
            results.push({ ref, status: data.status, data });
            addBatchResult(ref, data.status === 'success' ? 'success' : 'error', data);
        } catch (error) {
            results.push({ ref, status: 'error', error: error.message });
            addBatchResult(ref, 'error', { error: error.message });
        }
    }

    AppState.analysisResults = results;
    document.getElementById('btn-download-batch').disabled = false;
    UI.log(`✅ Procesamiento completado: ${results.filter(r => r.status === 'success').length} exitosos`, 'success');
}

function updateBatchProgress(current, total, ref) {
    const percent = (current / total) * 100;
    document.getElementById('batch-progress-fill').style.width = percent + '%';
    document.getElementById('batch-progress-text').textContent = `Procesando ${current} de ${total} referencias... (${ref})`;
}

function addBatchResult(ref, status, data) {
    const list = document.getElementById('batch-results-list');
    const item = document.createElement('div');
    item.className = `batch-item ${status}`;
    
    item.innerHTML = `
        <div>
            <strong>${ref}</strong>
            <div class="text-muted">${status === 'success' ? 'Completado' : 'Error'}</div>
        </div>
        <div>
            ${status === 'success' ? 
                `<i class="fas fa-check text-success"></i>` : 
                `<i class="fas fa-times text-danger"></i>`
            }
        </div>
    `;
    
    list.appendChild(item);
}

async function downloadBatchResults() {
    if (AppState.analysisResults.length === 0) return;

    UI.log('📦 Preparando descarga de resultados...');
    
    // Crear ZIP con resultados organizados por tipo
    const formData = new FormData();
    formData.append('results', JSON.stringify(AppState.analysisResults));
    
    try {
        const response = await fetch('/api/batch/download', {
            method: 'POST',
            body: formData
        });
        
        if (response.ok) {
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'resultados_lote.zip';
            a.click();
            window.URL.revokeObjectURL(url);
            
            UI.log('✅ Descarga completada', 'success');
        }
    } catch (error) {
        UI.log(`❌ Error en descarga: ${error.message}`, 'error');
    }
}

// KML Analysis
function handleKMLFiles(input) {
    AppState.kmlFiles = Array.from(input.files);
    const list = document.getElementById('kml-file-items');
    
    list.innerHTML = AppState.kmlFiles.map(file => `
        <div class="file-item">
            <div class="file-info">
                <i class="fas fa-map-marked file-icon"></i>
                <div>
                    <div class="file-name">${file.name}</div>
                    <div class="file-size">${(file.size / 1024).toFixed(1)} KB</div>
                </div>
            </div>
        </div>
    `).join('');
    
    document.getElementById('kml-files-list').classList.remove('hidden');
    document.getElementById('btn-analyze-kml').disabled = AppState.kmlFiles.length < 2;
}

async function analyzeKMLIntersection() {
    if (AppState.kmlFiles.length < 2) return;

    UI.log('🔍 Analizando cruces entre KML...');
    
    const formData = new FormData();
    AppState.kmlFiles.forEach(file => {
        formData.append('kml_files', file);
    });

    try {
        const response = await fetch('/api/kml/intersection', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        displayKMLResults(data);
        UI.log('✅ Análisis de cruces completado', 'success');
    } catch (error) {
        UI.log(`❌ Error: ${error.message}`, 'error');
    }
}

function displayKMLResults(data) {
    const container = document.getElementById('kml-intersection-results');
    container.innerHTML = data.intersections.map(inter => `
        <div class="analysis-item">
            <div class="analysis-label">${inter.layer1} ∩ ${inter.layer2}</div>
            <div class="analysis-value">${inter.percentage.toFixed(2)}% solapado</div>
        </div>
    `).join('');
    
    document.getElementById('kml-results').classList.remove('hidden');
}

// Ortofotos
async function generateOrtophotos() {
    const ref = document.getElementById('ortho-ref').value.trim();
    if (!ref) return;

    UI.log(`🛰️ Generando ortofotos para ${ref}`);
    
    try {
        const response = await fetch('/api/ortophotos/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ referencia: ref })
        });
        
        const data = await response.json();
        displayOrtophotos(data);
        UI.log('✅ Ortofotos generadas', 'success');
    } catch (error) {
        UI.log(`❌ Error: ${error.message}`, 'error');
    }
}

function displayOrtophotos(data) {
    const container = document.getElementById('ortho-preview');
    container.innerHTML = data.ortophotos.map(ortho => `
        <div class="ortho-item">
            <div class="ortho-img">
                <img src="${ortho.url}" style="width: 100%; height: 100%; object-fit: cover;">
            </div>
            <div class="ortho-info">
                <div class="ortho-title">${ortho.title}</div>
                <div class="ortho-desc">${ortho.description}</div>
            </div>
        </div>
    `).join('');
}

// Análisis Urbanístico
async function performUrbanAnalysis() {
    const ref = document.getElementById('urban-ref').value.trim();
    if (!ref) return;

    UI.log(`🏙️ Realizando análisis urbanístico para ${ref}`);
    
    try {
        const response = await fetch('/api/urban/analysis', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ referencia: ref })
        });
        
        const data = await response.json();
        displayUrbanResults(data);
        UI.log('✅ Análisis urbanístico completado', 'success');
    } catch (error) {
        UI.log(`❌ Error: ${error.message}`, 'error');
    }
}

function displayUrbanResults(data) {
    const container = document.getElementById('urban-analysis-content');
    container.innerHTML = `
        <div class="analysis-item">
            <div class="analysis-label">Zonificación</div>
            <div class="analysis-value">${data.zoning}</div>
        </div>
        <div class="analysis-item">
            <div class="analysis-label">Edificabilidad</div>
            <div class="analysis-value">${data.buildability}</div>
        </div>
        <div class="analysis-item">
            <div class="analysis-label">Ocupación</div>
            <div class="analysis-value">${data.occupation}</div>
        </div>
        <div class="analysis-item">
            <div class="analysis-label">Altura Máxima</div>
            <div class="analysis-value">${data.max_height}</div>
        </div>
        <div class="analysis-item">
            <div class="analysis-label">Retirada</div>
            <div class="analysis-value">${data.setback}</div>
        </div>
    `;
    
    document.getElementById('urban-results').classList.remove('hidden');
}

function updateResultsTable(results) {
    const tbody = document.getElementById('results-table-body');
    tbody.innerHTML = results.map(result => {
        const data = result.data || result;
        return `
            <tr>
                <td>${data.ref}</td>
                <td><span class="badge badge-success">Completado</span></td>
                <td>${data.analisis?.resumen?.capas_afectan || 0}</td>
                <td>${data.analisis?.resumen?.superficie_total_afectada || '0 m²'}</td>
                <td>
                    <button class="btn btn-ghost btn-sm" onclick="window.open('/static/viewer.html', '_blank')">
                        <i class="fas fa-eye"></i> Ver
                    </button>
                </td>
            </tr>
        `;
    }).join('');
}

// Inicialización
document.addEventListener('DOMContentLoaded', () => {
    UI.updateStatus('Sistema Listo', 'success');
});
