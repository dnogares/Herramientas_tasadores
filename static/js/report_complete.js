// Generador de informes personalizados
const ReportBuilder = {
    currentRef: null,
    selectedSections: [],
    referenceData: null,
    
    async init() {
        await this.loadReferences();
        this.setupEventListeners();
    },
    
    async loadReferences() {
        try {
            const response = await fetch('/api/references/list');
            const data = await response.json();
            
            if (data.status === 'success' && data.references.length > 0) {
                const selector = document.getElementById('ref-selector');
                selector.innerHTML = '<option value="">Selecciona una referencia...</option>' +
                    data.references.map(ref => `<option value="${ref}">${ref}</option>`).join('');
            }
        } catch (error) {
            console.error('Error cargando referencias:', error);
        }
    },
    
    setupEventListeners() {
        // Escuchar cambios en checkboxes
        document.querySelectorAll('.checkbox-item input[type="checkbox"]').forEach(checkbox => {
            checkbox.addEventListener('change', () => this.updatePreview());
        });
    },
    
    async loadReferenceData() {
        const selector = document.getElementById('ref-selector');
        const ref = selector.value;
        
        if (!ref) {
            this.hideReportBuilder();
            return;
        }
        
        this.currentRef = ref;
        
        try {
            const response = await fetch('/api/catastro/query', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ referencia: ref })
            });
            
            const data = await response.json();
            if (data.status === 'success') {
                this.referenceData = data;
                this.showReportBuilder();
                this.updateAvailableSections(data);
            }
        } catch (error) {
            console.error('Error cargando datos de referencia:', error);
        }
    },
    
    showReportBuilder() {
        document.getElementById('report-builder').style.display = 'grid';
        document.getElementById('form-section').style.display = 'block';
        document.getElementById('generate-section').style.display = 'block';
        document.getElementById('download-section').style.display = 'none';
    },
    
    hideReportBuilder() {
        document.getElementById('report-builder').style.display = 'none';
        document.getElementById('form-section').style.display = 'none';
        document.getElementById('generate-section').style.display = 'none';
        document.getElementById('download-section').style.display = 'none';
    },
    
    updateAvailableSections(data) {
        // Actualizar checkboxes basados en los datos disponibles
        const checkboxes = document.querySelectorAll('.checkbox-item input[type="checkbox"]');
        
        checkboxes.forEach(checkbox => {
            const value = checkbox.value;
            let available = true;
            
            // Verificar disponibilidad según el tipo
            if (value.startsWith('map-') || value.startsWith('layer-')) {
                available = data.analisis && data.analisis.capas_procesadas.length > 0;
            } else if (value.startsWith('doc-')) {
                available = true; // Documentos siempre disponibles
            }
            
            checkbox.disabled = !available;
            if (!available) {
                checkbox.parentElement.style.opacity = '0.5';
                checkbox.parentElement.style.cursor = 'not-allowed';
            }
        });
    },
    
    updatePreview() {
        const selected = this.getSelectedSections();
        const container = document.getElementById('preview-container');
        
        if (selected.length === 0) {
            container.innerHTML = `
                <div class="text-muted text-center py-5">
                    <i class="fas fa-file-pdf fa-3x mb-3"></i>
                    <p>Selecciona los elementos que quieres incluir</p>
                    <p>La vista previa se actualizará automáticamente</p>
                </div>
            `;
            return;
        }
        
        let previewHTML = '';
        
        selected.forEach(section => {
            const sectionInfo = this.getSectionInfo(section);
            previewHTML += `
                <div class="preview-item">
                    <div class="preview-icon">
                        <i class="${sectionInfo.icon}"></i>
                    </div>
                    <div class="preview-content">
                        <div class="preview-title">${sectionInfo.title}</div>
                        <div class="preview-desc">${sectionInfo.description}</div>
                    </div>
                </div>
            `;
        });
        
        container.innerHTML = previewHTML;
    },
    
    getSelectedSections() {
        const checkboxes = document.querySelectorAll('.checkbox-item input[type="checkbox"]:checked');
        return Array.from(checkboxes).map(cb => cb.value);
    },
    
    getSectionInfo(sectionId) {
        const sections = {
            'map-general': {
                icon: 'fas fa-map',
                title: 'Plano General',
                description: 'Vista general de la parcela y entorno inmediato'
            },
            'map-satellite': {
                icon: 'fas fa-satellite',
                title: 'Ortofotografía Satélite',
                description: 'Imágenes satelitales de alta resolución'
            },
            'map-topographic': {
                icon: 'fas fa-mountain',
                title: 'Plano Topográfico',
                description: 'Curvas de nivel y análisis de elevación'
            },
            'layer-urban': {
                icon: 'fas fa-city',
                title: 'Análisis Urbanístico',
                description: 'Zonificación y normativa aplicable'
            },
            'layer-environmental': {
                icon: 'fas fa-leaf',
                title: 'Afecciones Ambientales',
                description: 'Espacios protegidos y restricciones ambientales'
            },
            'layer-infrastructure': {
                icon: 'fas fa-road',
                title: 'Infraestructuras',
                description: 'Red viaria y servicios públicos cercanos'
            },
            'doc-catastro': {
                icon: 'fas fa-home',
                title: 'Datos Catastrales',
                description: 'Información oficial del catastro'
            },
            'doc-urban': {
                icon: 'fas fa-gavel',
                title: 'Normativa Urbanística',
                description: 'Reglamentos y ordenanzas aplicables'
            },
            'doc-technical': {
                icon: 'fas fa-clipboard',
                title: 'Ficha Técnica',
                description: 'Características técnicas detalladas'
            }
        };
        
        return sections[sectionId] || {
            icon: 'fas fa-file',
            title: 'Sección Desconocida',
            description: 'Descripción no disponible'
        };
    },
    
    async generateCustomReport() {
        const selected = this.getSelectedSections();
        
        if (selected.length === 0) {
            alert('Por favor, selecciona al menos un elemento para incluir en el informe');
            return;
        }
        
        // Validar formulario
        const empresa = document.getElementById('company-name').value.trim();
        const tecnico = document.getElementById('tech-name').value.trim();
        const colegiado = document.getElementById('tech-id').value.trim();
        
        if (!empresa || !tecnico || !colegiado) {
            alert('Por favor, completa todos los campos obligatorios del técnico');
            return;
        }
        
        this.showLoading();
        
        try {
            const formData = new FormData();
            formData.append('ref', this.currentRef);
            formData.append('empresa', empresa);
            formData.append('tecnico', tecnico);
            formData.append('colegiado', colegiado);
            formData.append('notas', document.getElementById('additional-notes').value || '');
            formData.append('selected_sections', JSON.stringify(selected));
            
            const logoInput = document.getElementById('logo-input');
            if (logoInput.files[0]) {
                formData.append('logo', logoInput.files[0]);
            }
            
            // Simular progreso
            await this.simulateProgress();
            
            const response = await fetch('/api/report/custom', {
                method: 'POST',
                body: formData
            });
            
            const data = await response.json();
            
            if (data.status === 'success') {
                this.hideLoading();
                this.showDownloadLink(data.pdf_url);
            } else {
                throw new Error(data.error || 'Error generando el informe');
            }
            
        } catch (error) {
            this.hideLoading();
            alert(`Error generando el informe: ${error.message}`);
        }
    },
    
    showLoading() {
        document.getElementById('loading-overlay').style.display = 'flex';
        document.getElementById('loading-text').textContent = 'Generando informe personalizado...';
        document.getElementById('loading-detail').textContent = 'Procesando contenido seleccionado...';
        document.getElementById('loading-progress-bar').style.width = '0%';
    },
    
    hideLoading() {
        document.getElementById('loading-overlay').style.display = 'none';
    },
    
    async simulateProgress() {
        const steps = [
            { progress: 20, text: 'Recopilando datos catastrales...', detail: 'Obteniendo información oficial' },
            { progress: 40, text: 'Generando planos...', detail: 'Creando mapas y visualizaciones' },
            { progress: 60, text: 'Analizando capas...', detail: 'Procesando intersecciones y afectaciones' },
            { progress: 80, text: 'Compilando documentación...', detail: 'Organizando documentos técnicos' },
            { progress: 95, text: 'Generando PDF...', detail: 'Creando documento final' }
        ];
        
        for (const step of steps) {
            document.getElementById('loading-progress-bar').style.width = step.progress + '%';
            document.getElementById('loading-text').textContent = step.text;
            document.getElementById('loading-detail').textContent = step.detail;
            await new Promise(resolve => setTimeout(resolve, 800));
        }
        
        document.getElementById('loading-progress-bar').style.width = '100%';
        document.getElementById('loading-text').textContent = 'Informe generado correctamente';
        document.getElementById('loading-detail').textContent = 'Preparando descarga...';
    },
    
    showDownloadLink(pdfUrl) {
        document.getElementById('generate-section').style.display = 'none';
        document.getElementById('download-section').style.display = 'block';
        
        const downloadLink = document.getElementById('download-link');
        downloadLink.href = pdfUrl;
        downloadLink.download = `informe_personalizado_${this.currentRef}.pdf`;
    }
};

// Funciones globales
function toggleSelection(element) {
    const checkbox = element.querySelector('input[type="checkbox"]');
    checkbox.checked = !checkbox.checked;
    
    if (checkbox.checked) {
        element.classList.add('selected');
    } else {
        element.classList.remove('selected');
    }
    
    ReportBuilder.updatePreview();
}

function loadReferenceData() {
    ReportBuilder.loadReferenceData();
}

function handleLogoUpload(input) {
    const file = input.files[0];
    if (file) {
        if (file.size > 2 * 1024 * 1024) {
            alert('El archivo no puede superar 2MB');
            input.value = '';
            return;
        }
        
        const reader = new FileReader();
        reader.onload = (e) => {
            const preview = document.getElementById('logo-preview');
            preview.innerHTML = `
                <img src="${e.target.result}" style="max-width: 200px; max-height: 100px; border-radius: 8px;">
                <p class="mt-2 mb-0"><strong>${file.name}</strong></p>
                <small>Click para cambiar</small>
            `;
            document.getElementById('logo-upload-area').classList.add('has-file');
        };
        reader.readAsDataURL(file);
    }
}

function generateCustomReport() {
    ReportBuilder.generateCustomReport();
}

// Inicializar al cargar la página
document.addEventListener('DOMContentLoaded', () => {
    ReportBuilder.init();
});
