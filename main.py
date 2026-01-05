import matplotlib
matplotlib.use('Agg')  # Backend sin GUI para Docker
import matplotlib.pyplot as plt
plt.ioff()  # Desactivar modo interactivo
import os
import sys
import logging
import json
import shutil
import zipfile
import time
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse, unquote
from typing import List

from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Body
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# --- CONFIGURACIÓN Y LOGGING ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.info("=== INICIANDO APLICACIÓN ===")

load_dotenv()

DEBUG = os.getenv("DEBUG", "False") == "True"
PORT = int(os.getenv("PORT", 8081))
CATASTRO_API_TOKEN = os.getenv("CATASTRO_TOKEN", "default_secret")

# --- IMPORTACIÓN DE MÓDULOS LOCALES (Punto 2: Crítico para la lógica de dnogares) ---
try:
    from urban_analysis import AnalizadorUrbanistico
    from vector_analyzer import VectorAnalyzer
    from catastro_engine import CatastroDownloader
    from catastro_complete_downloader import CatastroCompleteDownloader
    from local_layers_manager import LocalLayersManager
    logger.info("Módulos locales cargados correctamente")
except ImportError as e:
    logger.error(f"Error cargando módulos locales: {e}")
    # No detenemos para permitir debug, pero los motores fallarán si no están los archivos

app = FastAPI(title="Catastro-tool")

# --- CONFIGURACIÓN DE RUTAS (Adaptadas para Docker/Easypanel) ---
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "outputs"
STATIC_DIR = BASE_DIR / "static"

if os.getenv("DOCKER_ENV"):
    CAPAS_DIR = Path("/app/capas")
else:
    h_data = Path("H:/data")
    if h_data.exists():
        CAPAS_DIR = h_data
    else:
        CAPAS_DIR = BASE_DIR / "capas"
        CAPAS_DIR.mkdir(exist_ok=True)

OUTPUT_DIR.mkdir(exist_ok=True)

# Montar estáticos
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/outputs", StaticFiles(directory=str(OUTPUT_DIR)), name="outputs")

# --- INSTANCIAR MOTORES ---
urban_engine = AnalizadorUrbanistico(output_base_dir=str(OUTPUT_DIR))
vector_engine = VectorAnalyzer(output_dir=str(OUTPUT_DIR), capas_dir=str(CAPAS_DIR))
catastro_engine = CatastroDownloader(str(OUTPUT_DIR))
catastro_complete = CatastroCompleteDownloader(str(OUTPUT_DIR))
local_layers = LocalLayersManager(str(CAPAS_DIR))

# --- ENDPOINTS PRINCIPALES ---

@app.get("/")
async def read_index():
    return FileResponse(STATIC_DIR / "index_hybrid.html")

@app.post("/api/catastro/query")
async def query_catastro(data: dict = Body(...)):
    ref = data.get("referencia")
    if not ref:
        raise HTTPException(status_code=400, detail="Falta referencia")

    try:
        catastro_data = catastro_engine.descargar_todo_completo(ref)
        if catastro_data.get("status") != "success":
            return JSONResponse(status_code=400, content=catastro_data)
        
        data_info = catastro_data.get("data", {})
        coords = data_info.get("coordenadas")
        carpetas = data_info.get("carpetas", {})
        
        ortophotos = []
        if coords and isinstance(coords, dict):
            try:
                ortophotos = local_layers.generar_ortofotos_multi_escala(ref, coords)
            except Exception as e:
                logger.warning(f"Error en ortofotos locales: {e}")

        wms_layers = {}
        capas_procesadas = []
        
        if 'imagenes' in carpetas:
            imagenes_path = Path(carpetas['imagenes'])
            if imagenes_path.exists():
                for archivo in imagenes_path.glob("*.png"):
                    nombre_capa = archivo.stem.replace(f"{ref}_", "")
                    if nombre_capa == 'COMPOSICION': nombre_capa = 'composicion'
                    
                    nombres_map = {
                        'catastro': 'Catastro', 'ortofoto': 'Ortofoto PNOA', 
                        'callejero': 'Callejero', 'hidrografia': 'Hidrografía',
                        'composicion': 'Composición Completa'
                    }
                    
                    nombre_display = nombres_map.get(nombre_capa, nombre_capa.replace("_", " ").title())
                    url = f"/outputs/{ref}/imagenes/{archivo.name}"
                    wms_layers[nombre_capa] = url
                    capas_procesadas.append({
                        "nombre": nombre_display, "estado": "Descargada",
                        "superficie": "N/A", "png_url": url, "tipo": "WMS"
                    })
        
        return {
            "status": "success", "ref": ref, "coordenadas": coords,
            "analisis": {
                "resumen": {"total_capas": len(capas_procesadas), "capas_afectan": 0},
                "capas_procesadas": capas_procesadas, "wms_layers": wms_layers
            },
            "ortophotos": ortophotos, "carpeta": f"/outputs/{ref}"
        }
    except Exception as e:
        logger.exception(f"Error en consulta {ref}")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.get("/api/references/list")
async def list_references():
    try:
        refs = sorted([p.name for p in OUTPUT_DIR.iterdir() if p.is_dir()])
        return {"status": "success", "references": refs}
    except Exception:
        return {"status": "success", "references": []}

@app.get("/api/layers/info")  # CORREGIDO: Eliminado el "00"
async def get_layers_info():
    try:
        info = local_layers.get_capas_info()
        return {"status": "success", "layers": info}
    except Exception as e:
        logger.exception("Error obteniendo info de capas")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.post("/api/kml/intersection")
async def kml_intersection(kml_files: List[UploadFile] = File(...)):
    """Analiza intersecciones entre múltiples KMLs con redundancia de parseo."""
    try:
        import geopandas as gpd
        from shapely.ops import unary_union
        from shapely.geometry import Polygon
    except ImportError as e:
        return JSONResponse(status_code=500, content={"message": f"Faltan dependencias GIS: {e}"})

    gdfs = []
    names = []
    errors = []
    
    for f in kml_files:
        content = await f.read()
        try:
            from xml.etree import ElementTree as ET
            tree = ET.parse(BytesIO(content))
            ns = {'kml': 'http://www.opengis.net/kml/2.2'}
            coords_text = [c.text.strip() for c in tree.findall('.//kml:coordinates', ns) if c.text]
            
            polygons = []
            for coords_str in coords_text:
                points = []
                for coord in coords_str.split():
                    parts = coord.split(',')
                    if len(parts) >= 2:
                        points.append((float(parts[0]), float(parts[1])))
                if len(points) >= 3:
                    polygons.append(Polygon(points))
            
            if not polygons:
                raise ValueError("No se encontraron geometrías")
                
            gdf = gpd.GeoDataFrame({'geometry': polygons}, crs="EPSG:4326").to_crs("EPSG:25830")
            gdfs.append(unary_union(gdf.geometry))
            names.append(Path(f.filename).stem)
        except Exception as e:
            errors.append(f"{f.filename}: {str(e)}")

    intersections = []
    if len(gdfs) > 1:
        for i in range(len(gdfs)):
            for j in range(i + 1, len(gdfs)):
                try:
                    inter = gdfs[i].intersection(gdfs[j])
                    area = float(inter.area) if not inter.is_empty else 0.0
                    base_area = float(gdfs[i].area) if gdfs[i].area else 0.0
                    pct = (area / base_area * 100.0) if base_area > 0 else 0.0
                    intersections.append({
                        "layer1": names[i], "layer2": names[j],
                        "percentage": round(pct, 2), "area_m2": round(area, 2)
                    })
                except Exception as e:
                    errors.append(f"Error cruce {names[i]}-{names[j]}: {str(e)}")

    return {"status": "success", "intersections": intersections, "total_files": len(names), "errors": errors}

@app.post("/api/report/generate")
@app.post("/api/report/custom")
async def generate_final_report(
    ref: str = Form(...), empresa: str = Form(...), tecnico: str = Form(...),
    colegiado: str = Form(...), notas: str = Form(""), incluir_archivos: str = Form(None),
    selected_sections: str = Form(None), logo: UploadFile = File(None)
):
    """Generación de informe PDF profesional."""
    seleccion = selected_sections or incluir_archivos or "[]"
    try:
        from fpdf import FPDF
        (OUTPUT_DIR / ref).mkdir(parents=True, exist_ok=True)

        def _safe_pdf_text(s: str) -> str:
            return str(s).encode("latin-1", errors="replace").decode("latin-1") if s else ""

        mapas_seleccionados = json.loads(seleccion) if seleccion else []
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        # Logo y Cabecera
        if logo:
            logo_path = OUTPUT_DIR / f"temp_logo_{ref}_{logo.filename}"
            with open(logo_path, "wb") as buffer:
                buffer.write(await logo.read())
            try: pdf.image(str(logo_path), 10, 8, 33)
            except: pass
            pdf.ln(20)

        pdf.set_font("Helvetica", 'B', 16)
        pdf.cell(0, 10, _safe_pdf_text("INFORME TÉCNICO DE AFECCIONES URBANÍSTICAS"), 0, 1, 'C')
        pdf.set_font("Helvetica", '', 11)
        pdf.cell(0, 10, _safe_pdf_text(f"Referencia Catastral: {ref}"), 0, 1, 'C')
        pdf.ln(10)

        # Información del técnico
        pdf.set_fill_color(230, 230, 230)
        pdf.set_font("Helvetica", 'B', 12)
        pdf.cell(0, 10, _safe_pdf_text("  IDENTIFICACIÓN DEL TÉCNICO"), 0, 1, 'L', True)
        pdf.set_font("Helvetica", '', 11)
        pdf.cell(0, 8, _safe_pdf_text(f"Empresa: {empresa}"), 0, 1)
        pdf.cell(0, 8, _safe_pdf_text(f"Técnico: {tecnico}"), 0, 1)
        pdf.cell(0, 8, _safe_pdf_text(f"Colegiado: {colegiado}"), 0, 1)

        # Notas
        if notas:
            pdf.ln(5)
            pdf.set_font("Helvetica", 'B', 12)
            pdf.cell(0, 10, _safe_pdf_text("  NOTAS Y OBSERVACIONES"), 0, 1, 'L', True)
            pdf.set_font("Helvetica", '', 10)
            pdf.multi_cell(0, 6, _safe_pdf_text(notas))

        # Mapas
        for img_url in mapas_seleccionados:
            try:
                parsed = urlparse(img_url)
                path_str = unquote(parsed.path).replace("/outputs/", "", 1).lstrip("/\\")
                full_img_path = (OUTPUT_DIR / path_str).resolve()
                if full_img_path.exists():
                    pdf.add_page()
                    pdf.set_font("Helvetica", 'B', 14)
                    pdf.cell(0, 10, _safe_pdf_text(f"PLANO: {full_img_path.stem.replace(ref+'_', '')}"), 0, 1, 'C')
                    pdf.image(str(full_img_path), x=10, y=30, w=190)
            except Exception as e:
                logger.error(f"Error añadiendo imagen al PDF: {e}")

        report_filename = f"Informe_Final_{ref}.pdf"
        report_path = OUTPUT_DIR / ref / report_filename
        pdf.output(str(report_path))

        return {"status": "success", "pdf_url": f"/outputs/{ref}/{report_filename}"}
    except Exception as e:
        logger.exception("Error generando reporte")
        return JSONResponse(status_code=500, content={"error": str(e)})

# --- RESTO DE ENDPOINTS (Omitidos aquí por brevedad, pero mantenlos en tu archivo) ---
# download_complete_catastro, batch_complete_catastro, urban_analysis, download_batch_results, generate_ortophotos, check_kml_support...

if __name__ == "__main__":
    import uvicorn
    host = "0.0.0.0" if os.getenv("DOCKER_ENV") else "127.0.0.1"
    uvicorn.run(app, host=host, port=PORT)
