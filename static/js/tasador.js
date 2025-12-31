/**
 * ══════════════════════════════════════════════════════════════════════════
 * CATASTRO SaaS Pro - Sistema Integrado de Tasación
 * ══════════════════════════════════════════════════════════════════════════
 */

const AppState = {
    currentRef: localStorage.getItem('catastro_current_ref') || null,
    isProcessing: false,
    selectedMaps: []
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
    }
};

// ─── MÓDULO DE INFORMES (ReportBuilder) ───
const ReportBuilder = {

    // Carga los mapas generados por el Punto 3 en el selector
    async cargarMapasDisponibles() {
        if (!AppState.currentRef) return;

        const grid = document.getElementById('maps-selector-grid');
        if (!grid) return;

        // Estos nombres deben coincidir con los que genera tu 'vector_analyzer.py'
        const tiposMapas = [
            { id: 'situacion', nombre: 'Plano de Situación' },
            { id: 'urbanismo', nombre: 'Calificación Urbanística' },
            { id: 'afecciones', nombre: 'Mapa de Afecciones' },
            { id: 'catastro', nombre: 'Capa Catastral' }
        ];

        grid.innerHTML = tiposMapas.map(mapa => {
            const path = `/outputs/${AppState.currentRef}/${AppState.currentRef}_${mapa.id}.png`;
            return `
                <div class="map-selectable" onclick="ReportBuilder.toggleMapSelection('${path}', this)">
                    <img src="${path}" onerror="this.parentElement.style.display='none'">
                    <div class="map-label">${mapa.nombre}</div>
                    <div class="check-badge">✓</div>
                </div>
            `;
        }).join('');
    },

    toggleMapSelection(path, element) {
        if (AppState.selectedMaps.includes(path)) {
            AppState.selectedMaps = AppState.selectedMaps.filter(p => p !== path);
            element.classList.remove('active');
        } else {
            AppState.selectedMaps.push(path);
            element.classList.add('active');
        }
    },

    async generarPDF() {
        const btn = document.getElementById('btn-generate-pdf');
        const ref = AppState.currentRef;

        if (!ref) return alert("No hay una referencia activa analizada.");
        if (AppState.selectedMaps.length === 0) return alert("Selecciona al menos un plano para el informe.");

        btn.disabled = true;
        btn.innerHTML = "⏳ Procesando documento...";

        const formData = new FormData();
        formData.append('ref', ref);
        formData.append('empresa', document.getElementById('company-name').value);
        formData.append('tecnico', document.getElementById('tech-name').value);
        formData.append('colegiado', document.getElementById('tech-id').value);
        formData.append('notas', document.getElementById('additional-notes').value);
        formData.append('incluir_archivos', JSON.stringify(AppState.selectedMaps));

        const logo = document.getElementById('logo-input').files[0];
        if (logo) formData.append('logo', logo);

        try {
            const res = await fetch('/api/report/generate', { method: 'POST', body: formData });
            const data = await res.json();
            if (data.pdf_url) {
                UI.log("Informe PDF generado correctamente", "success");
                window.open(data.pdf_url, '_blank');
            }
        } catch (err) {
            UI.log("Error al generar el PDF", "error");
        } finally {
            btn.disabled = false;
            btn.innerHTML = "📄 GENERAR INFORME FINAL";
        }
    }
};

// ─── ACCIONES PRINCIPALES (Módulo 1 y 2) ───
const Actions = {
    async analizarReferencia() {
        const ref = document.getElementById('ref-input').value.trim();
        if (!ref) return;

        UI.log(`Iniciando análisis de ${ref}...`);
        AppState.currentRef = ref;
        localStorage.setItem('catastro_current_ref', ref);

        try {
            const res = await fetch('/api/catastro/query', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ referencia: ref })
            });
            const data = await res.json();
            UI.log("Análisis completado y planos generados", "success");

            // Si estamos en la página de reporte, refrescar mapas
            if (window.location.pathname.includes('report.html')) {
                ReportBuilder.cargarMapasDisponibles();
            }
        } catch (e) {
            UI.log("Error en el proceso", "error");
        }
    }
};

// Inicialización al cargar la página
document.addEventListener('DOMContentLoaded', () => {
    if (document.getElementById('maps-selector-grid')) {
        ReportBuilder.cargarMapasDisponibles();
    }
});