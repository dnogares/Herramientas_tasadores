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
                data.references.map(ref => '<option value="' + ref + '">' + ref + '</option>').join('');
        } else {
            // Si no hay referencias, mostrar mensaje
            const select = document.getElementById('reference-select');
            select.innerHTML = '<option value="">No hay referencias disponibles</option>';
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
    
    // Validar que existan los datos de análisis - permitir datos mínimos
    if (!data.analisis) {
        showError('No se encontraron datos de análisis');
        return;
    }
    
    // Resumen del análisis - usar valores por defecto si no existen
    const resumen = data.analisis.resumen || {};
    const coordenadas = data.coordenadas;
    
    let html = '<div class="analysis-summary">';
    html += '<div class="summary-title"><i class="fas fa-chart-pie"></i> Resumen del Análisis</div>';
    html += '<div class="summary-stats">';
    html += '<div class="summary-stat"><span class="summary-label">Referencia</span><span class="summary-value">' + (data.ref || 'N/A') + '</span></div>';
    html += '<div class="summary-stat"><span class="summary-label">Capas procesadas</span><span class="summary-value">' + (resumen.total_capas || 0) + '</span></div>';
    html += '<div class="summary-stat"><span class="summary-label">Con afectación</span><span class="summary-value">' + (resumen.capas_afectan || 0) + '</span></div>';
    html += '<div class="summary-stat"><span class="summary-label">Superficie afectada</span><span class="summary-value">' + (resumen.superficie_total_afectada || 'N/A') + '</span></div>';
    html += '<div class="summary-stat"><span class="summary-label">Archivos generados</span><span class="summary-value">' + (resumen.archivos_generados || 0) + '</span></div>';
    html += '</div>';
    
    if (coordenadas) {
        html += '<div class="coordinates-info">';
        html += '<h4><i class="fas fa-map-marker-alt"></i> Coordenadas</h4>';
        html += '<div class="coord-item"><span class="coord-label">Longitud:</span><span class="coord-value">' + coordenadas.lon.toFixed(6) + '°</span></div>';
        html += '<div class="coord-item"><span class="coord-label">Latitud:</span><span class="coord-value">' + coordenadas.lat.toFixed(6) + '°</span></div>';
        html += '<div class="coord-item"><span class="coord-label">SRS:</span><span class="coord-value">' + (coordenadas.srs || 'EPSG:4326') + '</span></div>';
        html += '</div>';
    }
    
    html += '</div>';
    html += '<div class="layers-list">';
    html += '<h3><i class="fas fa-layer-group"></i> Capas Generadas</h3>';
    
    // Lista de capas - manejar diferentes estructuras
    let capasProcesadas = [];
    
    if (data.analisis.capas_procesadas && Array.isArray(data.analisis.capas_procesadas)) {
        capasProcesadas = data.analisis.capas_procesadas;
    } else if (data.analisis.wms_layers) {
        // Convertir WMS layers a capas procesadas
        Object.entries(data.analisis.wms_layers).forEach(([key, url]) => {
            capasProcesadas.push({
                nombre: key,
                estado: 'Generada',
                png_url: url,
                tipo: 'WMS'
            });
        });
    }
    
    // Añadir ortofotos si existen
    if (data.ortophotos && Array.isArray(data.ortophotos)) {
        data.ortophotos.forEach((ortofoto, index) => {
            capasProcesadas.push({
                nombre: ortofoto.title,
                estado: 'Generada',
                png_url: ortofoto.url,
                tipo: 'Ortofoto',
                buffer: ortofoto.buffer
            });
        });
    }
    
    if (capasProcesadas.length === 0) {
        html += '<div class="text-center py-lg"><i class="fas fa-info-circle text-muted"></i><p class="text-muted">No se encontraron capas procesadas</p></div>';
    } else {
        capasProcesadas.forEach((capa, index) => {
            const statusClass = getStatusClass(capa.estado);
            const hasImage = capa.png_url;
            const hasKml = capa.kml_url;
            const hasJson = capa.json_url;
            
            let actionsHtml = '';
            if (hasImage) {
                actionsHtml += `<button class="btn btn-sm btn-primary" onclick="toggleLayer(${index})">
                    <i class="fas fa-eye"></i> Ver
                </button>`;
            }
            
            html += `
                <div class="layer-item">
                    <div class="layer-header">
                        <div class="layer-info">
                            <h4 class="layer-name">${capa.nombre}</h4>
                            <span class="layer-status ${statusClass}">${capa.estado}</span>
                        </div>
                        <div class="layer-actions">
                            ${actionsHtml}
                        </div>
                    </div>
                    <div class="layer-details">
                        <span class="layer-type">${capa.tipo || 'Desconocido'}</span>
                        ${capa.superficie ? `<span class="layer-area">${capa.superficie}</span>` : ''}
                        ${capa.buffer ? `<span class="layer-buffer">Buffer: ${capa.buffer}m</span>` : ''}
                    </div>
                    ${hasImage ? `
                        <div class="layer-opacity-control">
                            <label class="opacity-label-small">Opacidad:</label>
                            <input type="range" class="opacity-slider-small" id="opacity-${index}" 
                                   min="0" max="100" value="80" 
                                   onchange="updateLayerOpacity(${index}, this.value)">
                            <span class="opacity-value-small">80%</span>
                        </div>
                    ` : ''}
                </div>
            `;
        });
    }
    
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
            .bindPopup('<b>Referencia: ' + data.ref + '</b><br>Coordenadas: ' + data.coordenadas.lat.toFixed(6) + ', ' + data.coordenadas.lon.toFixed(6));
        
        currentLayers.parcela = parcelMarker;
    }
    
    // Añadir capas disponibles
    if (data.analisis && data.analisis.capas_procesadas) {
        data.analisis.capas_procesadas.forEach((capa, index) => {
            if (capa.png_url) {
                // Intentar añadir capa de imagen
                addImageLayer(index, capa);
            }
        });
    }
    
    // Añadir ortofotos locales si existen
    if (data.ortophotos && data.ortophotos.length > 0) {
        addOrtophotosToMap(data.ortophotos);
    }
    
    // Mostrar control de opacidad
    showOpacityControl();
}

async function loadOrtophotos() {
    if (!currentReference) return;
    
    try {
        const response = await fetch('/api/ortophotos/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ referencia: currentReference })
        });
        
        const data = await response.json();
        
        if (data.status === 'success' && data.ortophotos) {
            console.log('[loadOrtophotos] Ortofotos cargadas:', data.ortophotos);
            addOrtophotosToMap(data.ortophotos);
        } else {
            console.warn('[loadOrtophotos] No se pudieron cargar ortofotos:', data);
        }
    } catch (error) {
        console.error('[loadOrtophotos] Error cargando ortofotos:', error);
    }
}

function addOrtophotosToMap(ortophotos) {
    if (!analysisData || !analysisData.coordenadas) {
        console.warn('[addOrtophotosToMap] No hay coordenadas disponibles');
        return;
    }
    
    const coords = analysisData.coordenadas;
    const buffer = 0.01; // ~1km de buffer
    
    ortophotos.forEach((ortofoto, index) => {
        if (ortofoto.url) {
            try {
                // Calcular bounds basados en el buffer del ortofoto
                const bufferDegrees = (ortofoto.buffer || 1000) / 111000; // Convertir metros a grados
                const bounds = [
                    [coords.lat - bufferDegrees, coords.lon - bufferDegrees],
                    [coords.lat + bufferDegrees, coords.lon + bufferDegrees]
                ];
                
                const imageOverlay = L.imageOverlay(ortofoto.url, bounds, {
                    opacity: 0.7,
                    className: 'ortophoto-layer-' + index,
                    error: function(e) {
                        console.error(`[addOrtophotosToMap] Error loading ortophoto ${ortofoto.url}:`, e);
                    }
                });
                
                currentLayers['ortophoto-' + index] = imageOverlay;
                console.log(`[addOrtophotosToMap] Ortofoto layer created: ${ortofoto.title}, bounds:`, bounds);
            } catch (error) {
                console.error(`[addOrtophotosToMap] Error creating ortophoto layer:`, error);
            }
        }
    });
}

function addImageLayer(index, capa) {
    // Para capas de imagen, creamos un overlay
    try {
        const imageUrl = capa.png_url;
        const bounds = calculateImageBounds(capa);
        
        console.log(`[addImageLayer] index=${index}, imageUrl=${imageUrl}, bounds=`, bounds);
        
        if (bounds && imageUrl) {
            const imageOverlay = L.imageOverlay(imageUrl, bounds, {
                opacity: 0.8,
                className: 'layer-overlay-' + index,
                error: function(e) {
                    console.error(`[addImageLayer] Error loading image ${imageUrl}:`, e);
                }
            });
            
            currentLayers['image-' + index] = imageOverlay;
            console.log(`[addImageLayer] Layer created for index ${index}`);
        } else {
            console.warn(`[addImageLayer] No bounds or imageUrl for index ${index}`);
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
        
        // Buffer dinámico según el tipo de capa
        let latBuffer = 0.001;  // ~100m
        let lonBuffer = 0.001;
        
        // Ajustar buffer según categoría o impacto
        if (capa.categoria === 'ambiental' || capa.impacto === 'Alto') {
            latBuffer = 0.002;  // ~200m
            lonBuffer = 0.002;
        } else if (capa.categoria === 'infraestructuras') {
            latBuffer = 0.0005; // ~50m
            lonBuffer = 0.0005;
        }
        
        console.log(`[calculateImageBounds] lat=${lat}, lon=${lon}, buffers=[${latBuffer}, ${lonBuffer}]`);
        
        return [
            [lat - latBuffer, lon - lonBuffer],
            [lat + latBuffer, lon + lonBuffer]
        ];
    }
    console.warn('[calculateImageBounds] No coordinates available');
    return null;
}

function updateLayerOpacity(index, value) {
    const layerKey = 'image-' + index;
    const ortophotoKey = 'ortophoto-' + index;
    
    console.log(`[updateLayerOpacity] index=${index}, value=${value}`);
    
    // Actualizar capa de imagen normal
    if (currentLayers[layerKey]) {
        currentLayers[layerKey].setOpacity(value / 100);
        console.log(`[updateLayerOpacity] Set opacity ${value/100} on layer ${layerKey}`);
    }
    
    // Actualizar ortofoto
    if (currentLayers[ortophotoKey]) {
        currentLayers[ortophotoKey].setOpacity(value / 100);
        console.log(`[updateLayerOpacity] Set opacity ${value/100} on ortophoto ${ortophotoKey}`);
    }
    
    // Actualizar el valor mostrado
    const valueSpan = document.querySelector(`#opacity-${index} + .opacity-value-small`);
    if (valueSpan) {
        valueSpan.textContent = value + '%';
    }
}

function toggleLayer(index) {
    const layerKey = 'image-' + index;
    const ortophotoKey = 'ortophoto-' + index;
    
    console.log(`[toggleLayer] index=${index}`);
    
    // Verificar si es una capa de imagen u ortofoto
    if (currentLayers[layerKey]) {
        // Capa de imagen normal
        if (map.hasLayer(currentLayers[layerKey])) {
            map.removeLayer(currentLayers[layerKey]);
            console.log(`[toggleLayer] Removed layer ${layerKey}`);
        } else {
            currentLayers[layerKey].addTo(map);
            console.log(`[toggleLayer] Added layer ${layerKey} to map`);
        }
    } else if (currentLayers[ortophotoKey]) {
        // Ortofoto
        if (map.hasLayer(currentLayers[ortophotoKey])) {
            map.removeLayer(currentLayers[ortophotoKey]);
            console.log(`[toggleLayer] Removed ortophoto ${ortophotoKey}`);
        } else {
            currentLayers[ortophotoKey].addTo(map);
            console.log(`[toggleLayer] Added ortophoto ${ortophotoKey} to map`);
        }
    } else {
        console.warn(`[toggleLayer] No layer found for index ${index}`);
    }
    
    // Mostrar control de opacidad
    showOpacityControl();
}

function updateOpacity(value) {
    const opacityControl = document.getElementById('opacity-control');
    const layerIndex = opacityControl.dataset.layerIndex;
    
    console.log(`[updateOpacity] value=${value}, layerIndex=${layerIndex}`);
    
    if (layerIndex && currentLayers['image-' + layerIndex]) {
        currentLayers['image-' + layerIndex].setOpacity(value / 100);
        console.log(`[updateOpacity] Set opacity ${value/100} on layer image-${layerIndex}`);
    } else {
        // Si no hay capa específica, aplicar a todas las capas de imagen
        Object.keys(currentLayers).forEach(key => {
            if (key.startsWith('image-') && currentLayers[key]) {
                currentLayers[key].setOpacity(value / 100);
                console.log(`[updateOpacity] Set opacity ${value/100} on layer ${key}`);
            }
        });
    }
}

// Mostrar siempre el control de opacidad
function showOpacityControl() {
    const opacityControl = document.getElementById('opacity-control');
    if (opacityControl) {
        opacityControl.classList.remove('hidden');
    }
}

// Inicializar: mostrar control de opacidad al cargar la página
document.addEventListener('DOMContentLoaded', function() {
    showOpacityControl();
});

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
    content.innerHTML = '<div class="no-analysis"><i class="fas fa-map-marked-alt"></i><h3>Sin análisis seleccionado</h3><p>Selecciona una referencia catastral para visualizar los resultados del análisis</p></div>';
    
    // Limpiar mapa
    Object.values(currentLayers).forEach(layer => {
        map.removeLayer(layer);
    });
    currentLayers = {};
}

function showError(message) {
    const content = document.getElementById('viewer-content');
    content.innerHTML = '<div class="no-analysis"><i class="fas fa-exclamation-triangle"></i><h3>Error</h3><p>' + message + '</p></div>';
}

// Funciones globales para acceso desde HTML
window.loadReferenceData = loadReferenceData;
window.toggleLayer = toggleLayer;
window.updateOpacity = updateOpacity;
window.updateLayerOpacity = updateLayerOpacity;
window.zoomIn = zoomIn;
window.zoomOut = zoomOut;
window.fitBounds = fitBounds;
window.toggleFullscreen = toggleFullscreen;
