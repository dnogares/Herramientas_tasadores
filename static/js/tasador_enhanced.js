/**
 * ══════════════════════════════════════════════════════════════════════════
 * CATASTRO SaaS Pro - Sistema Integrado de Tasación (Enhanced)
 * ══════════════════════════════════════════════════════════════════════════
 */

const AppState = {
    currentRef: localStorage.getItem('catastro_current_ref') || null,
    isProcessing: false,
    selectedMaps: [],
    analysisData: null
};

// ─── UTILIDADES ───
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
    },

    showLoading(show = true) {
        const loader = document.getElementById('loading-overlay');
        if (loader) {
            loader.style.display = show ? 'flex' : 'none';
        }
    },

    updateResultsTable(data) {
        const tbody = document.getElementById('results-table-body');
        if (!tbody || !data) return;

        tbody.innerHTML = data.capas_procesadas.map(capa => `
            <tr>
                <td>${capa.nombre}</td>
                <td><span class="badge badge-${capa.estado === 'Solapado' ? 'warning' : 'success'}">${capa.estado}</span></td>
                <td>${capa.superficie}</td>
                <td>
                    <button class="btn btn-ghost btn-sm" onclick="UI.previewFile('${capa.png_url}')">
                        <i class="fas fa-eye"></i> Vista
                    </button>
                    <button class="btn btn-ghost btn-sm" onclick="UI.downloadFile('${capa.kml_url}')">
                        <i class="fas fa-download"></i> KML
                    </button>
                </td>
            </tr>
        `).join('');

        // Actualizar resumen
        const summaryDiv = document.getElementById('analysis-summary');
        if (summaryDiv && data.resumen) {
            summaryDiv.innerHTML = `
                <div class="summary-stats">
                    <div class="stat-item">
                        <span class="stat-number">${data.resumen.total_capas}</span>
                        <span class="stat-label">Capas Totales</span>
                    </div>
                    <div class="stat-item">
                        <span class="stat-number">${data.resumen.capas_afectan}</span>
                        <span class="stat-label">Capas Afectan</span>
                    </div>
                    <div class="stat-item">
                        <span class="stat-number">${data.resumen.superficie_total_afectada}</span>
                        <span class="stat-label">Superficie Afectada</span>
                    </div>
                </div>
            `;
        }
    },

    previewFile(url) {
        window.open(url, '_blank');
    },

    downloadFile(url) {
        const a = document.createElement('a');
        a.href = url;
        a.download = url.split('/').pop();
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    }
};

// ─── MÓDULO DE ANÁLISIS ───
const AnalysisModule = {
    async analizarReferencia() {
        const ref = document.getElementById('ref-input').value.trim();
        if (!ref) {
            UI.log("⚠️ Debes introducir una referencia catastral", "warning");
            return;
        }

        AppState.isProcessing = true;
        AppState.currentRef = ref;
        localStorage.setItem('catastro_current_ref', ref);
        
        UI.updateStatus("Procesando...", "warning");
        UI.showLoading(true);
        UI.log(`🔍 Iniciando análisis de ${ref}...`);

        try {
            const res = await fetch('/api/catastro/query', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ referencia: ref })
            });

            const data = await res.json();
            
            if (data.status === 'success') {
                AppState.analysisData = data;
                UI.updateStatus("Análisis completado", "success");
                UI.log("✅ Análisis completado y planos generados", "success");
                UI.updateResultsTable(data.analisis);
                
                // Actualizar módulo de informes
                ReportBuilder.cargarMapasDisponibles();
                
                // Habilitar botón de informes
                const reportBtn = document.getElementById('btn-go-to-report');
                if (reportBtn) {
                    reportBtn.disabled = false;
                    reportBtn.classList.remove('btn-disabled');
                }
            } else {
                throw new Error(data.error || 'Error desconocido');
            }
        } catch (error) {
            UI.updateStatus("Error en análisis", "error");
            UI.log(`❌ Error: ${error.message}`, "error");
        } finally {
            AppState.isProcessing = false;
            UI.showLoading(false);
        }
    },

    async downloadAllFiles() {
        if (!AppState.analysisData) return;
        
        UI.log("📦 Preparando descarga de todos los archivos...");
        
        const files = [
            AppState.analysisData.kml_url,
            ...AppState.analysisData.analisis.capas_procesadas.map(c => c.png_url),
            ...AppState.analysisData.analisis.capas_procesadas.map(c => c.kml_url)
        ];

        files.forEach((file, index) => {
            setTimeout(() => UI.downloadFile(file), index * 500);
        });
    }
};

// ─── MÓDULO DE INFORMES (ReportBuilder) ───
const ReportBuilder = {
    async cargarMapasDisponibles() {
        if (!AppState.currentRef || !AppState.analysisData) return;

        const grid = document.getElementById('maps-selector-grid');
        if (!grid) return;

        const capas = AppState.analysisData.analisis.capas_procesadas;
        
        grid.innerHTML = capas.map((capa, index) => `
            <div class="map-selectable" data-path="${capa.png_url}" onclick="ReportBuilder.toggleMapSelection('${capa.png_url}', this)">
                <div class="map-header">
                    <img src="${capa.png_url}" onerror="this.src='data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTAwIiBoZWlnaHQ9IjEwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMTAwIiBoZWlnaHQ9IjEwMCIgZmlsbD0iI2Y0ZjRmNCIvPjx0ZXh0IHg9IjUwIiB5PSI1MCIgZm9udC1mYW1pbHk9IkFyaWFsIiBmb250LXNpemU9IjEyIiBmaWxsPSIjOTk5IiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBkeT0iLjNlbSI+U2luIEltYWdlbjwvdGV4dD48L3N2Zz4='">
                    <div class="map-status ${capa.estado === 'Solapado' ? 'status-warning' : 'status-success'}">
                        ${capa.estado}
                    </div>
                </div>
                <div class="map-body">
                    <div class="map-title">${capa.nombre}</div>
                    <div class="map-info">
                        <span class="map-area">${capa.superficie}</span>
                        <div class="map-actions">
                            <button class="btn-icon" onclick="event.stopPropagation(); UI.previewFile('${capa.png_url}')" title="Vista previa">
                                <i class="fas fa-eye"></i>
                            </button>
                            <button class="btn-icon" onclick="event.stopPropagation(); UI.downloadFile('${capa.png_url}')" title="Descargar">
                                <i class="fas fa-download"></i>
                            </button>
                        </div>
                    </div>
                </div>
                <div class="selection-indicator">
                    <i class="fas fa-check"></i>
                </div>
            </div>
        `).join('');

        // Actualizar contador
        this.updateSelectionCounter();
    },

    toggleMapSelection(path, element) {
        if (AppState.selectedMaps.includes(path)) {
            AppState.selectedMaps = AppState.selectedMaps.filter(p => p !== path);
            element.classList.remove('active');
        } else {
            AppState.selectedMaps.push(path);
            element.classList.add('active');
        }
        this.updateSelectionCounter();
    },

    updateSelectionCounter() {
        const counter = document.getElementById('selection-counter');
        if (counter) {
            counter.textContent = `${AppState.selectedMaps.length} mapa(s) seleccionado(s)`;
        }
    },

    selectAllMaps() {
        const mapElements = document.querySelectorAll('.map-selectable');
        mapElements.forEach(element => {
            const path = element.dataset.path;
            if (path && !AppState.selectedMaps.includes(path)) {
                AppState.selectedMaps.push(path);
                element.classList.add('active');
            }
        });
        this.updateSelectionCounter();
    },

    deselectAllMaps() {
        const mapElements = document.querySelectorAll('.map-selectable');
        mapElements.forEach(element => {
            element.classList.remove('active');
        });
        AppState.selectedMaps = [];
        this.updateSelectionCounter();
    },

    async generarPDF() {
        const btn = document.getElementById('btn-generate-pdf');
        const ref = AppState.currentRef;

        if (!ref) {
            UI.log("⚠️ No hay una referencia activa analizada", "warning");
            return;
        }
        
        if (AppState.selectedMaps.length === 0) {
            UI.log("⚠️ Selecciona al menos un plano para el informe", "warning");
            return;
        }

        // Validar campos obligatorios
        const empresa = document.getElementById('company-name')?.value.trim();
        const tecnico = document.getElementById('tech-name')?.value.trim();
        const colegiado = document.getElementById('tech-id')?.value.trim();

        if (!empresa || !tecnico || !colegiado) {
            UI.log("⚠️ Completa todos los campos obligatorios del técnico", "warning");
            return;
        }

        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Generando PDF...';
        UI.updateStatus("Generando PDF...", "warning");

        const formData = new FormData();
        formData.append('ref', ref);
        formData.append('empresa', empresa);
        formData.append('tecnico', tecnico);
        formData.append('colegiado', colegiado);
        formData.append('notas', document.getElementById('additional-notes')?.value || '');
        formData.append('incluir_archivos', JSON.stringify(AppState.selectedMaps));

        const logo = document.getElementById('logo-input')?.files[0];
        if (logo) formData.append('logo', logo);

        try {
            const res = await fetch('/api/report/generate', { 
                method: 'POST', 
                body: formData 
            });
            
            const data = await res.json();
            
            if (data.status === 'success' && data.pdf_url) {
                UI.log("📄 Informe PDF generado correctamente", "success");
                UI.updateStatus("PDF generado", "success");
                
                // Abrir PDF en nueva pestaña
                window.open(data.pdf_url, '_blank');
                
                // Opción de descarga directa
                setTimeout(() => {
                    if (confirm('¿Deseas descargar el PDF generado?')) {
                        UI.downloadFile(data.pdf_url);
                    }
                }, 1000);
            } else {
                throw new Error(data.error || 'Error al generar PDF');
            }
        } catch (err) {
            UI.log(`❌ Error al generar el PDF: ${err.message}`, "error");
            UI.updateStatus("Error en PDF", "error");
        } finally {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-file-pdf"></i> GENERAR INFORME FINAL';
        }
    }
};

// ─── ACCIONES PRINCIPALES ───
const Actions = {
    analizarReferencia: AnalysisModule.analizarReferencia,
    downloadAllFiles: AnalysisModule.downloadAllFiles,
    generarPDF: ReportBuilder.generarPDF,
    selectAllMaps: ReportBuilder.selectAllMaps,
    deselectAllMaps: ReportBuilder.deselectAllMaps
};

// Inicialización al cargar la página
document.addEventListener('DOMContentLoaded', () => {
    // Restaurar estado
    if (AppState.currentRef) {
        document.getElementById('ref-input').value = AppState.currentRef;
        UI.updateStatus("Referencia restaurada", "info");
    }

    // Cargar mapas si estamos en página de informes
    if (document.getElementById('maps-selector-grid') && AppState.currentRef) {
        // Intentar cargar datos del análisis anterior
        fetch(`/api/catastro/query`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ referencia: AppState.currentRef })
        }).then(res => res.json()).then(data => {
            if (data.status === 'success') {
                AppState.analysisData = data;
                ReportBuilder.cargarMapasDisponibles();
            }
        }).catch(() => {
            // Si falla, cargar mapas disponibles por defecto
            ReportBuilder.cargarMapasDisponibles();
        });
    }

    // Atajos de teclado
    document.addEventListener('keydown', (e) => {
        if (e.ctrlKey && e.key === 'Enter') {
            const refInput = document.getElementById('ref-input');
            if (refInput === document.activeElement) {
                Actions.analizarReferencia();
            }
        }
    });
});

// Exportar para uso global
window.Actions = Actions;
window.UI = UI;
window.ReportBuilder = ReportBuilder;
window.AppState = AppState;
