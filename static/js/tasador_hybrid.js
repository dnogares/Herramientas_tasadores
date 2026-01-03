// Sistema híbrido de análisis catastral - Mezcla de v2 y v3
const AppState = {
    currentRef: null,
    batchFile: null,
    kmlFiles: [],
    analysisResults: [],
    isProcessing: false,
    lastAnalysisData: null
};

const UI = {
    log(msg, type = 'info') {
        const panel = document.getElementById('log-panel');
        if (!panel) return;
        const entry = document.createElement('div');
        entry.className = `log-entry log-${type}`;
        entry.innerHTML = `<span class="log-time">[${new Date().toLocaleTimeString()}]</span> ${msg}`;
        panel.prepend(entry);

        // Limitar número de entradas
        while (panel.children.length > 50) {
            panel.removeChild(panel.lastChild);
        }
    },

    updateStatus(message, type = 'info') {
        const badge = document.getElementById('status-badge');
        if (badge) {
            badge.textContent = message;
            badge.className = `badge badge-${type}`;
        }
    },

    updateStats(data) {
        if (!data) return;

        const stats = document.getElementById('analysis-stats');
        stats.style.display = 'grid';

        document.getElementById('stat-layers').textContent = data.analisis?.resumen?.total_capas || 0;
        document.getElementById('stat-affected').textContent = data.analisis?.resumen?.capas_afectan || 0;
        document.getElementById('stat-area').textContent = data.analisis?.resumen?.superficie_total_afectada || '0 m²';

        // Calcular impacto principal
        const capas = data.analisis?.capas_procesadas || [];
        const afectadas = capas.filter(c => c.estado === 'Solapado');
        let impacto = 'Bajo';
        if (afectadas.length > 3) impacto = 'Alto';
        else if (afectadas.length > 1) impacto = 'Medio';

        document.getElementById('stat-impact').textContent = impacto;
    }
};

// Tabs functionality
function switchTab(tabName) {
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));

    event.target.classList.add('active');
    document.getElementById(`tab-${tabName}`).classList.add('active');
}

// Análisis individual (mejorado de v2)
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
            AppState.lastAnalysisData = data;
            const capas_afectan = data.analisis?.resumen?.capas_afectan || 0;
            UI.log(`✅ Análisis completado: ${capas_afectan} capas afectan`, 'success');
            UI.updateStats(data);
            updateResultsTable([data]);
            UI.updateStatus('Análisis completado', 'success');

            // Habilitar botón de informes
            const informeBtn = document.querySelector('button[onclick*="report_complete"]');
            if (informeBtn) {
                informeBtn.disabled = false;
                informeBtn.classList.remove('btn-disabled');
            }
        }
    } catch (error) {
        UI.log(`❌ Error: ${error.message}`, 'error');
        UI.updateStatus('Error', 'danger');
    }
}

// Procesamiento por lotes (v3)
function handleBatchFile(input) {
    const file = input.files[0];
    if (!file) return;

    AppState.batchFile = file;
    document.getElementById('batch-file-name').textContent = file.name;
    document.getElementById('batch-file-size').textContent = (file.size / 1024).toFixed(1) + ' KB';
    document.getElementById('batch-file-info').classList.remove('hidden');
    document.getElementById('btn-process-batch').disabled = false;

    UI.log(`📁 Archivo cargado: ${file.name}`);
}

function clearBatchFile() {
    AppState.batchFile = null;
    document.getElementById('batch-file-input').value = '';
    document.getElementById('batch-file-info').classList.add('hidden');
    document.getElementById('btn-process-batch').disabled = true;
    UI.log('🗑️ Archivo eliminado');
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
    let processed = 0;

    for (const ref of references) {
        updateBatchProgress(processed + 1, references.length, ref);

        try {
            const response = await fetch('/api/catastro/query', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ referencia: ref })
            });

            const data = await response.json();
            results.push({ ref, status: data.status, data });
            addBatchResult(ref, data.status === 'success' ? 'success' : 'error', data);

            if (data.status === 'success') {
                UI.log(`✅ ${ref}: ${data.analisis.resumen.capas_afectan} capas afectan`, 'success');
            } else {
                UI.log(`❌ ${ref}: Error en análisis`, 'error');
            }
        } catch (error) {
            results.push({ ref, status: 'error', error: error.message });
            addBatchResult(ref, 'error', { error: error.message });
            UI.log(`❌ ${ref}: ${error.message}`, 'error');
        }

        processed++;
    }

    AppState.analysisResults = results;
    document.getElementById('btn-download-batch').disabled = false;

    const exitosos = results.filter(r => r.status === 'success').length;
    UI.log(`✅ Procesamiento completado: ${exitosos}/${references.length} exitosos`, 'success');
    UI.updateStatus('Procesamiento completado', 'success');
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

    const icon = status === 'success' ? 'fa-check' : 'fa-times';
    const details = status === 'success' ?
        `Completado - ${data.analisis?.resumen?.capas_afectan || 0} capas afectan` :
        `Error - ${data.error || 'Error desconocido'}`;

    item.innerHTML = `
        <div>
            <strong>${ref}</strong>
            <div class="text-muted">${details}</div>
        </div>
        <div>
            <i class="fas ${icon}"></i>
        </div>
    `;

    list.appendChild(item);
}

async function downloadBatchResults() {
    if (AppState.analysisResults.length === 0) return;

    UI.log('📦 Preparando descarga de resultados...');

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
            a.download = `resultados_lote_${new Date().toISOString().slice(0, 10)}.zip`;
            a.click();
            window.URL.revokeObjectURL(url);

            UI.log('✅ Descarga completada', 'success');
            UI.updateStatus('Descarga completada', 'success');
        }
    } catch (error) {
        UI.log(`❌ Error en descarga: ${error.message}`, 'error');
    }
}

// KML Analysis (v3)
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

    UI.log(`📂 ${AppState.kmlFiles.length} archivos KML cargados`);
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
        UI.updateStatus('Análisis KML completado', 'success');
    } catch (error) {
        UI.log(`❌ Error: ${error.message}`, 'error');
    }
}

function displayKMLResults(data) {
    const container = document.getElementById('kml-intersection-results');

    let html = '';

    if (data.intersections && data.intersections.length > 0) {
        html += data.intersections.map(inter => `
            <div class="analysis-item">
                <div class="analysis-label">
                    <i class="fas fa-project-diagram"></i> ${inter.layer1} ∩ ${inter.layer2}
                </div>
                <div class="analysis-value">
                    ${inter.percentage.toFixed(2)}% solapado 
                    <small class="text-muted">(${inter.area_m2.toFixed(0)} m²)</small>
                </div>
            </div>
        `).join('');
    } else {
        html += '<div class="text-center p-3 text-muted">No se encontraron intersecciones entre las capas.</div>';
    }

    if (data.errors && data.errors.length > 0) {
        html += `
            <div class="mt-3 p-2 bg-light border-danger rounded">
                <small class="text-danger">
                    <strong>Errores detectados:</strong><br>
                    ${data.errors.join('<br>')}
                </small>
            </div>
        `;
    }

    container.innerHTML = html;
    document.getElementById('kml-results').classList.remove('hidden');
}

// Ortofotos (v3)
async function generateOrtophotos() {
    const ref = document.getElementById('ortho-ref').value.trim();
    if (!ref) {
        UI.log('⚠️ Introduce una referencia catastral', 'warning');
        return;
    }

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
        UI.updateStatus('Ortofotos generadas', 'success');
    } catch (error) {
        UI.log(`❌ Error: ${error.message}`, 'error');
    }
}

function displayOrtophotos(data) {
    if (!data.ortophotos || data.ortophotos.length === 0) return;

    // 1. Cargar el Zoom 4 (Parcela) en el Visor Principal
    const zoom4 = data.ortophotos.find(o => o.zoom === "Parcela") || data.ortophotos[data.ortophotos.length - 1]; // Fallback al último
    if (zoom4 && zoom4.layers) {
        document.getElementById('layer-base').src = zoom4.layers.base || '';
        document.getElementById('layer-overlay').src = zoom4.layers.overlay || '';
        document.getElementById('layer-labels').src = zoom4.layers.labels || ''; // Si existiese
        document.getElementById('layer-viewer').classList.remove('hidden');
    }

    // 2. Generar Galería de Miniaturas
    const container = document.getElementById('ortho-preview');
    container.innerHTML = data.ortophotos.map(ortho => `
        <div class="ortho-item" onclick="loadViewerLayer('${ortho.layers.base}', '${ortho.layers.overlay}')" style="cursor: pointer;">
            <div class="ortho-img">
                <img src="${ortho.url}" style="width: 100%; height: 100%; object-fit: cover;">
            </div>
            <div class="ortho-info">
                <div class="ortho-title">${ortho.title}</div>
                <div class="ortho-desc">${ortho.description}</div>
                <small><i class="fas fa-search-plus"></i> Zoom: ${ortho.zoom}</small>
                <div class="text-primary mt-2"><small>Click para ver en grande</small></div>
            </div>
        </div>
    `).join('');
}

function updateOpacity(val) {
    document.getElementById('layer-overlay').style.opacity = val / 100;
    document.getElementById('opacity-val').textContent = val + '%';
}

function loadViewerLayer(base, overlay) {
    document.getElementById('layer-base').src = base;
    document.getElementById('layer-overlay').src = overlay;
    document.getElementById('layer-viewer').scrollIntoView({ behavior: 'smooth' });
}

// Análisis Urbanístico (v3)
async function performUrbanAnalysis() {
    const ref = document.getElementById('urban-ref').value.trim();
    if (!ref) {
        UI.log('⚠️ Introduce una referencia catastral', 'warning');
        return;
    }

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
        UI.updateStatus('Análisis urbanístico completado', 'success');
    } catch (error) {
        UI.log(`❌ Error: ${error.message}`, 'error');
    }
}

function displayUrbanResults(data) {
    const container = document.getElementById('urban-analysis-content');
    const analisis = data.analisis || {};

    container.innerHTML = `
        <div class="analysis-item">
            <div class="analysis-label">
                <i class="fas fa-map"></i> Calificación
            </div>
            <div class="analysis-value">${analisis.calificacion || 'N/A'}</div>
        </div>
        <div class="analysis-item">
            <div class="analysis-label">
                <i class="fas fa-building"></i> Edificabilidad
            </div>
            <div class="analysis-value">${analisis.edificabilidad || 'N/A'}</div>
        </div>
        <div class="analysis-item">
            <div class="analysis-label">
                <i class="fas fa-chart-pie"></i> Ocupación
            </div>
            <div class="analysis-value">${analisis.ocupacion || 'N/A'}</div>
        </div>
        <div class="analysis-item">
            <div class="analysis-label">
                <i class="fas fa-arrows-alt-v"></i> Alturas
            </div>
            <div class="analysis-value">${analisis.alturas || 'N/A'}</div>
        </div>
        <div class="analysis-item">
            <div class="analysis-label">
                <i class="fas fa-home"></i> Uso
            </div>
            <div class="analysis-value">${analisis.uso || 'N/A'}</div>
        </div>
        <div class="analysis-item">
            <div class="analysis-label">
                <i class="fas fa-gavel"></i> Normativa
            </div>
            <div class="analysis-value">${analisis.normativa || 'N/A'}</div>
        </div>
    `;

    // Mostrar afectaciones si existen
    if (analisis.afectaciones && analisis.afectaciones.length > 0) {
        const afectacionesHtml = analisis.afectaciones.map(afect => `
            <div class="affectation-item">
                <div class="affectation-type">${afect.tipo}</div>
                <div class="affectation-impact impact-${afect.impacto.toLowerCase()}">${afect.impacto}</div>
                <div class="affectation-desc">${afect.descripcion}</div>
            </div>
        `).join('');

        container.innerHTML += `
            <h4><i class="fas fa-exclamation-triangle"></i> Afectaciones Detectadas</h4>
            <div class="affectations-list">
                ${afectacionesHtml}
            </div>
        `;
    }

    document.getElementById('urban-results').classList.remove('hidden');
}

function updateResultsTable(results) {
    const tbody = document.getElementById('results-table-body');
    tbody.innerHTML = results.map(result => {
        const data = result.data || result;
        return `
            <tr>
                <td><strong>${data.ref}</strong></td>
                <td><span class="badge badge-success">Completado</span></td>
                <td>${data.analisis?.resumen?.capas_afectan || 0}</td>
                <td>${data.analisis?.resumen?.superficie_total_afectada || '0 m²'}</td>
                <td>
                    <button class="btn btn-ghost btn-sm" onclick="viewResults('${data.ref}')">
                        <i class="fas fa-eye"></i> Ver
                    </button>
                    <button class="btn btn-ghost btn-sm" onclick="downloadResults('${data.ref}')">
                        <i class="fas fa-download"></i> Descargar
                    </button>
                </td>
            </tr>
        `;
    }).join('');
}

function viewResults(ref) {
    window.open(`/static/viewer_hybrid.html?ref=${ref}`, '_blank');
}

function downloadResults(ref) {
    window.open(`/outputs/pdfs/${ref}/catastro_${ref}.pdf`, '_blank');
}

// Drag and drop mejorado
document.addEventListener('DOMContentLoaded', () => {
    // Configurar drag and drop para archivos batch
    const batchArea = document.querySelector('.file-upload-area');
    if (batchArea) {
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            batchArea.addEventListener(eventName, preventDefaults, false);
        });

        ['dragenter', 'dragover'].forEach(eventName => {
            batchArea.addEventListener(eventName, () => batchArea.classList.add('dragover'), false);
        });

        ['dragleave', 'drop'].forEach(eventName => {
            batchArea.addEventListener(eventName, () => batchArea.classList.remove('dragover'), false);
        });

        batchArea.addEventListener('drop', handleDrop, false);
    }

    // Configurar drag and drop para KML
    const kmlArea = document.querySelector('.kml-drop-zone');
    if (kmlArea) {
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            kmlArea.addEventListener(eventName, preventDefaults, false);
        });

        ['dragenter', 'dragover'].forEach(eventName => {
            kmlArea.addEventListener(eventName, () => kmlArea.classList.add('dragover'), false);
        });

        ['dragleave', 'drop'].forEach(eventName => {
            kmlArea.addEventListener(eventName, () => kmlArea.classList.remove('dragover'), false);
        });

        kmlArea.addEventListener('drop', handleKMLDrop, false);
    }

    UI.updateStatus('Sistema Listo', 'success');
});

function preventDefaults(e) {
    e.preventDefault();
    e.stopPropagation();
}

function handleDrop(e) {
    const dt = e.dataTransfer;
    const files = dt.files;

    if (files.length > 0) {
        const file = files[0];
        if (file.name.endsWith('.txt') || file.name.endsWith('.csv')) {
            document.getElementById('batch-file-input').files = files;
            handleBatchFile(document.getElementById('batch-file-input'));
        }
    }
}

function handleKMLDrop(e) {
    const dt = e.dataTransfer;
    const files = dt.files;

    if (files.length > 0) {
        document.getElementById('kml-input').files = files;
        handleKMLFiles(document.getElementById('kml-input'));
    }
}

// Atajos de teclado
document.addEventListener('keydown', (e) => {
    if (e.ctrlKey && e.key === 'Enter') {
        const activeElement = document.activeElement;
        if (activeElement && activeElement.id === 'ref-input') {
            analyzeSingle();
        } else if (activeElement && activeElement.id === 'ortho-ref') {
            generateOrtophotos();
        } else if (activeElement && activeElement.id === 'urban-ref') {
            performUrbanAnalysis();
        }
    }
});

// Exportar para uso global
window.switchTab = switchTab;
window.analyzeSingle = analyzeSingle;
window.handleBatchFile = handleBatchFile;
window.clearBatchFile = clearBatchFile;
window.processBatch = processBatch;
window.downloadBatchResults = downloadBatchResults;
window.handleKMLFiles = handleKMLFiles;
window.analyzeKMLIntersection = analyzeKMLIntersection;
window.generateOrtophotos = generateOrtophotos;
window.performUrbanAnalysis = performUrbanAnalysis;
window.viewResults = viewResults;
window.downloadResults = downloadResults;
