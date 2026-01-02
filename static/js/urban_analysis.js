// Análisis Urbanístico
let currentUrbanRef = null;

async function performUrbanAnalysis() {
    const ref = document.getElementById('urban-ref-input').value.trim();
    if (!ref) {
        alert('Por favor, introduce una referencia catastral');
        return;
    }

    currentUrbanRef = ref;
    
    // Mostrar loading
    document.getElementById('urban-loading').style.display = 'block';
    document.getElementById('urban-results-content').innerHTML = '';
    
    try {
        const response = await fetch('/api/urban/analysis', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ referencia: ref })
        });
        
        const data = await response.json();
        
        if (data.status === 'success') {
            displayUrbanResults(data);
        } else {
            showError('No se pudo realizar el análisis urbanístico');
        }
    } catch (error) {
        console.error('Error en análisis urbanístico:', error);
        showError('Error al realizar el análisis');
    } finally {
        document.getElementById('urban-loading').style.display = 'none';
    }
}

function displayUrbanResults(data) {
    const content = document.getElementById('urban-results-content');
    
    // Determinar indicadores de impacto
    const buildabilityValue = parseFloat(data.buildability);
    const occupationValue = parseFloat(data.occupation);
    const heightValue = parseInt(data.max_height);
    
    let buildabilityIndicator = 'indicator-low';
    let occupationIndicator = 'indicator-low';
    let heightIndicator = 'indicator-low';
    
    if (buildabilityValue > 1.5) buildabilityIndicator = 'indicator-high';
    else if (buildabilityValue > 1.0) buildabilityIndicator = 'indicator-medium';
    
    if (occupationValue > 70) occupationIndicator = 'indicator-high';
    else if (occupationValue > 50) occupationIndicator = 'indicator-medium';
    
    if (heightValue > 15) heightIndicator = 'indicator-high';
    else if (heightValue > 8) heightIndicator = 'indicator-medium';
    
    let html = `
        <div class="result-item">
            <div class="result-label">
                <i class="fas fa-map"></i> Zonificación
            </div>
            <div class="result-value">
                ${data.zoning}
                <span class="urban-indicator indicator-medium">Zona</span>
            </div>
        </div>
        
        <div class="result-item">
            <div class="result-label">
                <i class="fas fa-building"></i> Edificabilidad
            </div>
            <div class="result-value">
                ${data.buildability}
                <span class="urban-indicator ${buildabilityIndicator}">${buildabilityIndicator === 'indicator-high' ? 'Alta' : buildabilityIndicator === 'indicator-medium' ? 'Media' : 'Baja'}</span>
            </div>
        </div>
        
        <div class="result-item">
            <div class="result-label">
                <i class="fas fa-chart-area"></i> Ocupación
            </div>
            <div class="result-value">
                ${data.occupation}
                <span class="urban-indicator ${occupationIndicator}">${occupationIndicator === 'indicator-high' ? 'Alta' : occupationIndicator === 'indicator-medium' ? 'Media' : 'Baja'}</span>
            </div>
        </div>
        
        <div class="result-item">
            <div class="result-label">
                <i class="fas fa-arrows-alt-v"></i> Altura Máxima
            </div>
            <div class="result-value">
                ${data.max_height}
                <span class="urban-indicator ${heightIndicator}">${heightIndicator === 'indicator-high' ? 'Alta' : heightIndicator === 'indicator-medium' ? 'Media' : 'Baja'}</span>
            </div>
        </div>
        
        <div class="result-item">
            <div class="result-label">
                <i class="fas fa-ruler"></i> Retirada
            </div>
            <div class="result-value">${data.setback}</div>
        </div>
        
        <div class="result-item">
            <div class="result-label">
                <i class="fas fa-gavel"></i> Normativa Aplicable
            </div>
            <div class="result-value">${data.regulations}</div>
        </div>
    `;
    
    // Añadir observaciones si existen
    if (data.observations) {
        html += `
            <div class="result-item" style="flex-direction: column; align-items: flex-start;">
                <div class="result-label">
                    <i class="fas fa-exclamation-triangle"></i> Observaciones
                </div>
                <div class="result-value" style="margin-top: 10px; font-size: 0.9rem; line-height: 1.4;">
                    ${data.observations}
                </div>
            </div>
        `;
    }
    
    // Añadir botones de acción
    html += `
        <div style="margin-top: 20px; display: flex; gap: 10px;">
            <button class="btn btn-primary" onclick="generateUrbanReport()">
                <i class="fas fa-file-pdf"></i> Generar Informe
            </button>
            <button class="btn btn-info" onclick="viewInMap()">
                <i class="fas fa-map-marked-alt"></i> Ver en Mapa
            </button>
        </div>
    `;
    
    content.innerHTML = html;
}

function showError(message) {
    const content = document.getElementById('urban-results-content');
    content.innerHTML = `
        <div class="no-results">
            <i class="fas fa-exclamation-triangle"></i>
            <h3>Error</h3>
            <p>${message}</p>
        </div>
    `;
}

function generateUrbanReport() {
    if (!currentUrbanRef) return;
    
    // Redirigir al generador de informes con la referencia
    window.location.href = `/static/report_complete.html?ref=${currentUrbanRef}&type=urban`;
}

function viewInMap() {
    if (!currentUrbanRef) return;
    
    // Abrir visor GIS con la referencia
    window.open(`/static/viewer_hybrid.html?ref=${currentUrbanRef}`, '_blank');
}

// Permitir análisis con Enter
document.getElementById('urban-ref-input').addEventListener('keypress', function(e) {
    if (e.key === 'Enter') {
        performUrbanAnalysis();
    }
});

// Funciones globales
window.performUrbanAnalysis = performUrbanAnalysis;
window.generateUrbanReport = generateUrbanReport;
window.viewInMap = viewInMap;
