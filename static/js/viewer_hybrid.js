// Visor GIS Híbrido - Con datos reales del análisis
let map;
let currentLayers = {};
let currentReference = null;
let analysisData = null;

// Inicialización
document.addEventListener('DOMContentLoaded', async () => {
    initializeMap();
    await loadReferences();
    
    // Verificar si hay referencia en URL
    const urlParams = new URLSearchParams(window.location.search);
    const ref = urlParams.get('ref');
    if (ref) {
        document.getElementById('reference-select').value = ref;
        await loadReferenceData();
    }
});

function initializeMap() {
    // Inicializar mapa centrado en España
    map = L.map('map').setView([40.4, -3.7], 6);
    
    // Capa base de OpenStreetMap
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors',
        maxZoom: 19
    }).addTo(map);
}

async function loadReferences() {
    try {
        const response = await fetch('/api/references/list');
        const data = await response.json();
        
        if (data.status === 'success' && data.references.length > 0) {
            const select = document.getElementById('reference-select');
            select.innerHTML = '<option value="">Selecciona una referencia...</option>' +
                data.references.map(ref => `<option value="${ref}">${ref}</option>`).join('');
        }
    } catch (error) {
        console.error('Error cargando referencias:', error);
    }
}

async function loadReferenceData() {
    const select = document.getElementById('reference-select');
    const ref = select.value;
    
    if (!ref) {
        showNoAnalysis();
        return;
    }
    
    currentReference = ref;
    
    try {
        // Cargar datos del análisis
        const response = await fetch('/api/catastro/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ referencia: ref })
        });
        
        const data = await response.json();
        
        if (data.status === 'success') {
            analysisData = data;
            displayAnalysisData(data);
            updateMapWithLayers(data);
        } else {
            showError('No se encontraron datos para esta referencia');
        }
    } catch (error) {
        console.error('Error cargando datos:', error);
        showError('Error al cargar los datos del análisis');
    }
}

function displayAnalysisData(data) {
    const content = document.getElementById('viewer-content');
    
    // Resumen del análisis
    const resumen = data.analisis.resumen;
    const coordenadas = data.coordenadas;
    
    let html = `
        <div class="analysis-summary">
            <div class="summary-title">
                <i class="fas fa-chart-pie"></i> Resumen del Análisis
            </div>
            <div class="summary-stats">
                <div class="summary-stat">
                    <span class="summary-label">Capas totales</span>
                    <span class="summary-value">${resumen.total_capas}</span>
                </div>
                <div class="summary-stat">
                    <span class="summary-label">Con afectación</span>
                    <span class="summary-value">${resumen.capas_afectan}</span>
                </div>
                <div class="summary-stat">
                    <span class="summary-label">Superficie afectada</span>
                    <span class="summary-value">${resumen.superficie_total_afectada}</span>
                </div>
                <div class="summary-stat">
                    <span class="summary-label">Archivos generados</span>
                    <span class="summary-value">${resumen.archivos_generados || 0}</span>
                </div>
            </div>
            
            ${coordenadas ? `
                <div class="coordinates-info">
                    <h4><i class="fas fa-map-marker-alt"></i> Coordenadas</h4>
                    <div class="coord-item">
                        <span class="coord-label">Longitud:</span>
                        <span class="coord-value">${coordenadas.lon.toFixed(6)}°</span>
                    </div>
                    <div class="coord-item">
                        <span class="coord-label">Latitud:</span>
                        <span class="coord-value">${coordenadas.lat.toFixed(6)}°</span>
                    </div>
                    <div class="coord-item">
                        <span class="coord-label">SRS:</span>
                        <span class="coord-value">${coordenadas.srs || 'EPSG:4326'}</span>
                    </div>
                </div>
            ` : ''}
        </div>
        
        <div class="layers-list">
            <h3><i class="fas fa-layer-group"></i> Capas Generadas</h3>
    `;
    
    // Lista de capas
    data.analisis.capas_procesadas.forEach((capa, index) => {
        const statusClass = getStatusClass(capa.estado);
        const hasImage = capa.png_url;
        const hasKml = capa.kml_url;
        const hasJson = capa.json_url;
        
        let actionsHtml = '';
        if (hasImage) {
            actionsHtml += `<a href="${capa.png_url}" target="_blank" class="layer-action-btn" onclick="event.stopPropagation()">
                <i class="fas fa-image"></i> Ver
            </a>`;
        }
        if (hasKml) {
            actionsHtml += `<a href="${capa.kml_url}" target="_blank" class="layer-action-btn" onclick="event.stopPropagation()">
                <i class="fas fa-map-marked"></i> KML
            </a>`;
        }
        if (hasJson) {
            actionsHtml += `<a href="${capa.json_url}" target="_blank" class="layer-action-btn" onclick="event.stopPropagation()">
                <i class="fas fa-file-code"></i> JSON
            </a>`;
        }
        
        let detailsHtml = '';
        if (capa.superficie !== 'N/A') {
            detailsHtml += `Superficie: ${capa.superficie}`;
        }
        if (capa.porcentaje) {
            detailsHtml += ` | Afectación: ${capa.porcentaje}`;
        }
        if (capa.categoria) {
            detailsHtml += `<br>Categoría: ${capa.categoria}`;
        }
        if (capa.impacto) {
            detailsHtml += ` | Impacto: ${capa.impacto}`;
        }
        
        html += `
            <div class="layer-item" id="layer-${index}" onclick="toggleLayer(${index}, '${capa.nombre}', '${capa.png_url || ''}', '${capa.kml_url || ''}')">
                <div class="layer-header">
                    <div class="layer-title">${capa.nombre}</div>
                    <div class="layer-status ${statusClass}">${capa.estado}</div>
                </div>
                <div class="layer-details">
                    ${detailsHtml}
                </div>
                <div class="layer-actions">
                    ${actionsHtml}
                </div>
            </div>
        `;
    });
    
    html += '</div>';
    content.innerHTML = html;
}

function getStatusClass(estado) {
    switch (estado.toLowerCase()) {
        case 'solapado': return 'status-solapado';
        case 'descargada': return 'status-descargado';
        case 'generada': return 'status-generado';
        default: return 'status-descargado';
    }
}

function updateMapWithLayers(data) {
    // Limpiar capas existentes
    Object.values(currentLayers).forEach(layer => {
        map.removeLayer(layer);
    });
    currentLayers = {};
    
    // Centrar mapa en coordenadas si existen
    if (data.coordenadas) {
        const coords = [data.coordenadas.lat, data.coordenadas.lon];
        map.setView(coords, 15);
        
        // Añadir marcador de parcela
        const parcelMarker = L.marker(coords)
            .addTo(map)
            .bindPopup(`<b>Referencia: ${data.ref}</b><br>Coordenadas: ${data.coordenadas.lat.toFixed(6)}, ${data.coordenadas.lon.toFixed(6)}`);
        
        currentLayers.parcela = parcelMarker;
    }
    
    // Añadir capas disponibles
    data.analisis.capas_procesadas.forEach((capa, index) => {
        if (capa.png_url) {
            // Intentar añadir capa de imagen
            addImageLayer(index, capa);
        }
    });
}

function addImageLayer(index, capa) {
    // Para capas de imagen, creamos un overlay
    try {
        const imageUrl = capa.png_url;
        const bounds = calculateImageBounds(capa);
        
        if (bounds) {
            const imageOverlay = L.imageOverlay(imageUrl, bounds, {
                opacity: 0.7,
                className: `layer-overlay-${index}`
            });
            
            currentLayers[`image-${index}`] = imageOverlay;
            // No añadimos la capa automáticamente, solo cuando se hace clic
        }
    } catch (error) {
        console.error('Error añadiendo capa de imagen:', error);
    }
}

function calculateImageBounds(capa) {
    // Si tenemos coordenadas, creamos un bounds alrededor
    if (analysisData && analysisData.coordenadas) {
        const coords = analysisData.coordenadas;
        const lat = coords.lat;
        const lon = coords.lon;
        
        // Buffer de aproximadamente 200m
        const latBuffer = 0.001;
        const lonBuffer = 0.001;
        
        return [
            [lat - latBuffer, lon - lonBuffer],
            [lat + latBuffer, lon + lonBuffer]
        ];
    }
    return null;
}

function toggleLayer(index, nombre, imageUrl, kmlUrl) {
    const layerElement = document.getElementById(`layer-${index}`);
    const isActive = layerElement.classList.contains('active');
    
    if (isActive) {
        // Desactivar capa
        layerElement.classList.remove('active');
        
        // Remover capa del mapa
        if (currentLayers[`image-${index}`]) {
            map.removeLayer(currentLayers[`image-${index}`]);
            delete currentLayers[`image-${index}];
        }
        
        // Ocultar control de opacidad
        document.getElementById('opacity-control').classList.remove('active');
        
    } else {
        // Activar capa
        layerElement.classList.add('active');
        
        // Añadir capa al mapa
        if (imageUrl && currentLayers[`image-${index}`]) {
            currentLayers[`image-${index}].addTo(map);
            
            // Mostrar control de opacidad
            const opacityControl = document.getElementById('opacity-control');
            opacityControl.classList.add('active');
            opacityControl.dataset.layerIndex = index;
        }
        
        // Ajustar vista a la capa
        if (analysisData && analysisData.coordenadas) {
            const coords = [analysisData.coordenadas.lat, analysisData.coordenadas.lon];
            map.setView(coords, 16);
        }
    }
}

function updateOpacity(value) {
    const opacityControl = document.getElementById('opacity-control');
    const layerIndex = opacityControl.dataset.layerIndex;
    
    if (layerIndex && currentLayers[`image-${layerIndex}`]) {
        currentLayers[`image-${layerIndex}].setOpacity(value / 100);
    }
}

function zoomIn() {
    map.zoomIn();
}

function zoomOut() {
    map.zoomOut();
}

function fitBounds() {
    if (analysisData && analysisData.coordenadas) {
        const coords = [analysisData.coordenadas.lat, analysisData.coordenadas.lon];
        map.setView(coords, 15);
    }
}

function toggleFullscreen() {
    const mapContainer = document.querySelector('.map-container');
    
    if (!document.fullscreenElement) {
        mapContainer.requestFullscreen().catch(err => {
            console.error('Error al entrar en pantalla completa:', err);
        });
    } else {
        document.exitFullscreen();
    }
}

function showNoAnalysis() {
    const content = document.getElementById('viewer-content');
    content.innerHTML = `
        <div class="no-analysis">
            <i class="fas fa-map-marked-alt"></i>
            <h3>Sin análisis seleccionado</h3>
            <p>Selecciona una referencia catastral para visualizar los resultados del análisis</p>
        </div>
    `;
    
    // Limpiar mapa
    Object.values(currentLayers).forEach(layer => {
        map.removeLayer(layer);
    });
    currentLayers = {};
}

function showError(message) {
    const content = document.getElementById('viewer-content');
    content.innerHTML = `
        <div class="no-analysis">
            <i class="fas fa-exclamation-triangle"></i>
            <h3>Error</h3>
            <p>${message}</p>
        </div>
    `;
}

// Funciones globales para acceso desde HTML
window.loadReferenceData = loadReferenceData;
window.toggleLayer = toggleLayer;
window.updateOpacity = updateOpacity;
window.zoomIn = zoomIn;
window.zoomOut = zoomOut;
window.fitBounds = fitBounds;
window.toggleFullscreen = toggleFullscreen;
