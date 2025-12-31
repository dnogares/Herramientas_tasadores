import os
import os
from dotenv import load_dotenv

# Carga el archivo .env si existe (para desarrollo local)
load_dotenv()

# Variables de configuración
DEBUG = os.getenv("DEBUG", "False") == "True"
PORT = int(os.getenv("PORT", 8080))
# Ejemplo de API Key futura
CATASTRO_API_TOKEN = os.getenv("CATASTRO_TOKEN", "default_secret")
import json
import shutil
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Body
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

# Importación de tus módulos locales
from urban_analysis import AnalizadorUrbanistico
from vector_analyzer import VectorAnalyzer

app = FastAPI(title="Catastro SaaS Pro API")

# 1. CONFIGURACIÓN DE RUTAS (Adaptadas para Docker/Easypanel)
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "outputs"
CAPAS_DIR = BASE_DIR / "capas"
STATIC_DIR = BASE_DIR / "static"

# Crear directorios si no existen
OUTPUT_DIR.mkdir(exist_ok=True)
CAPAS_DIR.mkdir(exist_ok=True)

# 2. MONTAR ARCHIVOS ESTÁTICOS
# Importante: Esto permite que Easypanel sirva el HTML, CSS, JS y las imágenes generadas
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/outputs", StaticFiles(directory=str(OUTPUT_DIR)), name="outputs")

# Instanciar motores de análisis
urban_engine = AnalizadorUrbanistico(output_base_dir=str(OUTPUT_DIR))
vector_engine = VectorAnalyzer(output_dir=str(OUTPUT_DIR), capas_dir=str(CAPAS_DIR))

# --- ENDPOINTS PRINCIPALES ---

@app.get("/")
async def read_index():
    """Ruta raíz que sirve el dashboard principal"""
    return FileResponse(STATIC_DIR / "index.html")

@app.post("/api/catastro/query")
async def query_catastro(data: dict = Body(...)):
    """
    PUNTO 1 y 2: Obtiene KML y datos básicos.
    """
    ref = data.get("referencia")
    if not ref:
        raise HTTPException(status_code=400, detail="Falta referencia")
    
    # 1. Obtener Geometría (Módulo Urban Analysis)
    catastro_data = urban_engine.obtener_datos_catastrales(ref)
    
    if catastro_data["status"] == "error":
        return JSONResponse(status_code=500, content=catastro_data)

    # 2. Ejecutar Análisis Vectorial y Generar Mapas (Módulo Vector Analyzer)
    # El vector_engine crea los .png automáticamente en la carpeta de la referencia
    analisis_gis = vector_engine.ejecutar_analisis_completo(ref, catastro_data["kml"])

    return {
        "status": "success",
        "ref": ref,
        "kml_url": f"/outputs/{ref}/{ref}.kml",
        "analisis": analisis_gis
    }

@app.post("/api/report/generate")
async def generate_final_report(
    ref: str = Form(...),
    empresa: str = Form(...),
    tecnico: str = Form(...),
    colegiado: str = Form(...),
    notas: str = Form(""),
    incluir_archivos: str = Form(...),
    logo: UploadFile = File(None)
):
    """
    PUNTO 5: Une todo en el PDF profesional.
    """
    try:
        from fpdf import FPDF
        
        mapas_seleccionados = json.loads(incluir_archivos)
        
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        # Manejo de Logo
        if logo:
            logo_path = OUTPUT_DIR / f"temp_logo_{ref}_{logo.filename}"
            with open(logo_path, "wb") as buffer:
                shutil.copyfileobj(logo.file, buffer)
            pdf.image(str(logo_path), 10, 8, 33)
            pdf.ln(20)

        # Encabezado
        pdf.set_font("Arial", 'B', 16)
        pdf.cell(0, 10, "INFORME TÉCNICO DE AFECCIONES URBANÍSTICAS", 0, 1, 'C')
        pdf.set_font("Arial", '', 11)
        pdf.cell(0, 10, f"Referencia Catastral: {ref}", 0, 1, 'C')
        pdf.ln(10)

        # Tabla de Datos
        pdf.set_fill_color(230, 230, 230)
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, "  IDENTIFICACIÓN DEL TÉCNICO", 0, 1, 'L', True)
        pdf.set_font("Arial", '', 11)
        pdf.cell(0, 8, f"Empresa: {empresa}", 0, 1)
        pdf.cell(0, 8, f"Técnico: {tecnico}", 0, 1)
        pdf.cell(0, 8, f"Colegiado: {colegiado}", 0, 1)
        pdf.ln(5)

        # Cuerpo de Notas
        if notas:
            pdf.set_font("Arial", 'B', 12)
            pdf.cell(0, 10, "  NOTAS Y OBSERVACIONES", 0, 1, 'L', True)
            pdf.set_font("Arial", '', 10)
            pdf.multi_cell(0, 6, notas)
            pdf.ln(5)

        # Inserción de Mapas (Uno por página)
        for img_url in mapas_seleccionados:
            # Convertir URL (/outputs/...) a ruta local de archivo
            # El img_url viene como "/outputs/REF123/REF123_capa.png"
            relative_path = img_url.replace("/outputs/", "")
            full_img_path = OUTPUT_DIR / relative_path

            if full_img_path.exists():
                pdf.add_page()
                pdf.set_font("Arial", 'B', 14)
                pdf.cell(0, 10, f"PLANO: {full_img_path.stem.replace(ref+'_', '')}", 0, 1, 'C')
                # Ajustar imagen al ancho del PDF (A4 tiene ~210mm)
                pdf.image(str(full_img_path), x=10, y=30, w=190)

        # Guardar PDF final
        report_filename = f"Informe_Final_{ref}.pdf"
        report_path = OUTPUT_DIR / ref / report_filename
        pdf.output(str(report_path))

        return {
            "status": "success",
            "pdf_url": f"/outputs/{ref}/{report_filename}"
        }

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

if __name__ == "__main__":
    import uvicorn
    # En producción (Easypanel), el puerto debe ser 8000
    uvicorn.run(app, host="0.0.0.0", port=8000)
