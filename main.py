import matplotlib
matplotlib.use('Agg')  # Backend sin GUI para Docker
import matplotlib.pyplot as plt
plt.ioff()  # Desactivar modo interactivo
import os
import sys
import logging
from dotenv import load_dotenv

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logger.info("=== INICIANDO APLICACIÓN ===")

# Carga el archivo .env si existe (para desarrollo local)
load_dotenv()

# Variables de configuración
DEBUG = os.getenv("DEBUG", "False") == "True"
PORT = int(os.getenv("PORT", 8081))
CATASTRO_API_TOKEN = os.getenv("CATASTRO_TOKEN", "default_secret")

logger.info(f"DEBUG: {DEBUG}, PORT: {PORT}")

import json
import shutil
import zipfile
import time
from io import BytesIO
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Body
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from urllib.parse import urlparse, unquote
from typing import List

logger.info("Importaciones básicas completadas")

# Importación de tus módulos locales
from urban_analysis import AnalizadorUrbanistico
from vector_analyzer import VectorAnalyzer
from catastro_engine import CatastroDownloader
from catastro_complete_downloader import CatastroCompleteDownloader
from local_layers_manager import LocalLayersManager

app = FastAPI(title="Catastro-tool")

# 1. CONFIGURACIÓN DE RUTAS (Adaptadas para Docker/Easypanel)
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "outputs"

# Configuración de CAPAS_DIR según entorno
if os.getenv("DOCKER_ENV"):
    # En Docker/producción: usar volumen montado
    CAPAS_DIR = Path("/app/capas")
else:
    # En desarrollo local: intentar H:/data, si no existe usar carpeta local 'capas'
    h_data = Path("H:/data")
    if h_data.exists():
        CAPAS_DIR = h_data
    else:
        CAPAS_DIR = BASE_DIR / "capas"
        CAPAS_DIR.mkdir(exist_ok=True)

STATIC_DIR = BASE_DIR / "static"

# Crear directorios si no existen
OUTPUT_DIR.mkdir(exist_ok=True)
# CAPAS_DIR es un volumen externo, no crear localmente

# Montar archivos estáticos
# Importante: Esto permite que Easypanel sirva el HTML, CSS, JS y las imágenes generadas
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/outputs", StaticFiles(directory=str(OUTPUT_DIR)), name="outputs")

# Instanciar motores de análisis
urban_engine = AnalizadorUrbanistico(output_base_dir=str(OUTPUT_DIR))
vector_engine = VectorAnalyzer(output_dir=str(OUTPUT_DIR), capas_dir=str(CAPAS_DIR))
catastro_engine = CatastroDownloader(str(OUTPUT_DIR))
catastro_complete = CatastroCompleteDownloader(str(OUTPUT_DIR))
local_layers = LocalLayersManager(str(CAPAS_DIR))

# --- ENDPOINTS PRINCIPALES ---

@app.get("/")
async def read_index():
    """Ruta raíz que sirve el dashboard principal"""
    return FileResponse(STATIC_DIR / "index_hybrid.html")

@app.post("/api/catastro/query")
async def query_catastro(data: dict = Body(...)):
    """Endpoint principal de consulta catastral con análisis completo"""
    ref = data.get("referencia")
    if not ref:
        raise HTTPException(status_code=400, detail="Falta referencia")

    try:
        # 1. Usar el nuevo catastro_engine actualizado
        catastro_data = catastro_engine.descargar_todo_completo(ref)
        
        if catastro_data.get("status") != "success":
            return JSONResponse(
                status_code=400, 
                content={"status": "error", "message": f"No se pudieron obtener datos catastrales: {catastro_data.get('status', 'error')}"}
            )
        
        # 2. Extraer datos de la nueva estructura
        data_info = catastro_data.get("data", {})
        coords = data_info.get("coordenadas")
        carpetas = data_info.get("carpetas", {})
        
        # 3. Generar ortofotos locales
        ortophotos = []
        if coords and isinstance(coords, dict):
            try:
                ortophotos = local_layers.generar_ortofotos_multi_escala(ref, coords)
            except Exception as e:
                logger.warning(f"No se pudieron generar ortofotos locales: {e}")

        # 4. Procesar archivos descargados por el nuevo catastro_engine
        wms_layers = {}
        capas_procesadas = []
        
        # Buscar archivos PNG en la carpeta de imágenes
        if 'imagenes' in carpetas:
            imagenes_path = Path(carpetas['imagenes'])
            if imagenes_path.exists():
                for archivo in imagenes_path.glob("*.png"):
                    nombre_capa = archivo.stem.replace(f"{ref}_", "")
                    if nombre_capa == 'COMPOSICION':
                        nombre_capa = 'composicion'
                        
                    nombre_display = nombre_capa.replace("_", " ").title()
                    
                    # Mapear nombres de capa a nombres descriptivos
                    nombres_map = {
                        'catastro': 'Catastro',
                        'ortofoto': 'Ortofoto PNOA', 
                        'callejero': 'Callejero',
                        'hidrografia': 'Hidrografía',
                        'composicion': 'Composición Completa'
                    }
                    
                    nombre_display = nombres_map.get(nombre_capa, nombre_display)
                    url = f"/outputs/{ref}/imagenes/{archivo.name}"
                    
                    wms_layers[nombre_capa] = url
                    capas_procesadas.append({
                        "nombre": nombre_display,
                        "estado": "Descargada",
                        "superficie": "N/A",
                        "png_url": url,
                        "tipo": "WMS"
                    })
        
        # 5. Retornar todo integrado
        return {
            "status": "success",
            "ref": ref,
            "coordenadas": coords,
            "analisis": {
                "resumen": {
                    "total_capas": len(capas_procesadas),
                    "capas_afectan": 0,
                    "superficie_total_afectada": "0.00 m²",
                    "archivos_generados": len(capas_procesadas)
                },
                "capas_procesadas": capas_procesadas,
                "wms_layers": wms_layers
            },
            "ortophotos": ortophotos,
            "carpeta": f"/outputs/{ref}"
        }
        
    except Exception as e:
        logger.exception(f"Error en consulta catastral para {ref}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)}
        )

@app.get("/api/references/list")
async def list_references():
    """Lista referencias disponibles"""
    try:
        refs = [p.name for p in OUTPUT_DIR.iterdir() if p.is_dir()]
        refs = sorted(refs)
        
        return {
            "status": "success",
            "references": refs
        }
    except Exception:
        return {
            "status": "success",
            "references": []
        }

00

async def get_layers_info():
    """Retorna información de capas locales disponibles"""
    try:
        info = local_layers.get_capas_info()
        return {"status": "success", "layers": info}
    except Exception as e:
        logger.exception(f"Error obteniendo info de capas")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.post("/api/catastro/complete/download")
async def download_complete_catastro(data: dict = Body(...)):
    """Descarga completa de Catastro con organización por tipos"""
    ref = data.get("referencia")
    if not ref:
        raise HTTPException(status_code=400, detail="Falta referencia")
    
    try:
        # Descargar todo y organizar por tipos
        exito, zip_path = catastro_complete.descargar_todo_completo(ref)
        
        if not exito:
            return JSONResponse(status_code=500, content={"status": "error", "message": "Descarga parcial o fallida"})
        
        if zip_path and zip_path.exists():
            # Devolver el ZIP para descarga
            return FileResponse(
                path=zip_path,
                filename=zip_path.name,
                media_type="application/zip"
            )
        else:
            return JSONResponse(status_code=500, content={"status": "error", "message": "No se pudo crear el ZIP"})
            
    except Exception as e:
        logger.exception(f"Error en download_complete_catastro para {ref}")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.post("/api/catastro/batch/complete")
async def batch_complete_catastro(data: dict = Body(...)):
    """Procesamiento por lotes con organización por tipos"""
    referencias = data.get("referencias", [])
    if not referencias:
        raise HTTPException(status_code=400, detail="Faltan referencias")
    
    try:
        # Procesar lote
        resultados = catastro_complete.procesar_lote(referencias)
        
        # Crear ZIP con todos los resultados
        mem = BytesIO()
        with zipfile.ZipFile(mem, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            # Añadir resumen
            resumen = {
                "total_referencias": len(referencias),
                "resultados": {ref: exito for ref, (exito, _) in resultados.items()},
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            zf.writestr("resumen_lote.json", json.dumps(resumen, ensure_ascii=False, indent=2))
            
            # Añadir todos los ZIPs individuales
            for ref, (exito, zip_path) in resultados.items():
                if exito and zip_path and zip_path.exists():
                    zf.write(zip_path, f"individuales/{zip_path.name}")
        
        mem.seek(0)
        headers = {"Content-Disposition": "attachment; filename=lote_completo.zip"}
        return StreamingResponse(mem, media_type="application/zip", headers=headers)
        
    except Exception as e:
        logger.exception(f"Error en batch_complete_catastro")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.post("/api/urban/analysis")
async def urban_analysis(data: dict = Body(...)):
    """Análisis urbanístico completo de una referencia"""
    ref = data.get("referencia")
    if not ref:
        raise HTTPException(status_code=400, detail="Falta referencia")
    
    # Intentar cargar datos reales de afecciones si existen
    json_path = OUTPUT_DIR / ref / f"{ref}_afecciones_info.json"
    afectaciones_reales = []
    
    if json_path.exists():
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                info = json.load(f)
                for capa in info.get("capas", []):
                    if capa.get("afectado"):
                        impacto = "Alto" if capa.get("area_afectada_m2", 0) > 100 else "Medio"
                        afectaciones_reales.append({
                            "tipo": capa.get("titulo", capa.get("nombre")),
                            "impacto": impacto,
                            "descripcion": f"La parcela intersecta con {capa.get('titulo')} ({capa.get('area_afectada_m2')} m²)"
                        })
        except Exception as e:
            logger.error(f"Error cargando afecciones reales para {ref}: {e}")

    # Si no hay afecciones reales, usar un mensaje informativo si el análisis GIS ya se hizo
    if not afectaciones_reales:
        if json_path.exists():
            afectaciones_reales = [{"tipo": "Sin afecciones", "impacto": "Bajo", "descripcion": "No se han detectado colisiones con las capas locales analizadas."}]
        else:
            afectaciones_reales = [{"tipo": "Análisis pendiente", "impacto": "N/A", "descripcion": "Realice primero el 'Análisis Individual' para cruzar con capas locales."}]

    payload = {
        "status": "success",
        "ref": ref,
        # Estos valores siguen siendo estimativos o de configuración general
        "zoning": "Suelo Urbano",
        "buildability": "Sujeto a PGOU",
        "occupation": "Pendiente de informe",
        "max_height": "Sujeto a ordenanza",
        "setback": "Consultar normativa",
        "regulations": "Plan General Municipal",
        "observations": "Análisis automatizado basado en capas GIS disponibles.",
        # Formato nuevo (tasador_hybrid.js)
        "analisis": {
            "calificacion": "Suelo Urbano / Rústico (según PGOU)",
            "edificabilidad": "Ver normativa local",
            "ocupacion": "Máxima según zona",
            "alturas": "Consultar ordenanza",
            "uso": "Principal según Catastro",
            "normativa": "PGOU Vigente",
            "afectaciones": afectaciones_reales,
        },
        "kml_url": f"/outputs/{ref}/{ref}.kml",
    }
    return payload

@app.post("/api/batch/download")
async def download_batch_results(results: str = Form(...)):
    """Genera ZIP con resultados del lote (multipart/form-data)."""
    try:
        parsed = json.loads(results)
    except Exception:
        parsed = []

    refs = []
    for r in parsed:
        ref = r.get("ref") if isinstance(r, dict) else None
        if ref:
            refs.append(ref)

    mem = BytesIO()
    with zipfile.ZipFile(mem, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("results.json", json.dumps(parsed, ensure_ascii=False, indent=2))
        for ref in refs:
            ref_dir = OUTPUT_DIR / ref
            if not ref_dir.exists():
                continue
            for p in ref_dir.rglob("*"):
                if p.is_file():
                    arcname = str(Path(ref) / p.relative_to(ref_dir))
                    zf.write(p, arcname=arcname)

    mem.seek(0)
    headers = {"Content-Disposition": "attachment; filename=resultados_lote.zip"}
    return StreamingResponse(mem, media_type="application/zip", headers=headers)

@app.post("/api/kml/intersection")
async def kml_intersection(kml_files: List[UploadFile] = File(...)):
    """Analiza intersecciones entre múltiples KMLs (multipart/form-data)."""
    try:
        import geopandas as gpd
        from shapely.ops import unary_union
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

    gdfs = []
    names = []
    errors = []
    
    for f in kml_files:
        content = await f.read()
try:                    # Usar XML parser para KML (no requiere driver GDAL)
                    from xml.etree import ElementTree as ET
                    tree = ET.parse(BytesIO(content))
                    # Buscar todas las coordenadas en el KML
                    ns = {'kml': 'http://www.opengis.net/kml/2.2'}
                    coords_text = []
                    for coord_elem in tree.findall('.//kml:coordinates', ns):
                        if coord_elem.text:
                            coords_text.append(coord_elem.text.strip())
                    
                    if not coords_text:
                        raise ValueError("No se encontraron coordenadas en el KML")
                    
                    # Crear geometrías desde las coordenadas
                    from shapely.geometry import Polygon, MultiPolygon
                    polygons = []
                    for coords_str in coords_text:
                        points = []
                        for coord in coords_str.split():
                            parts = coord.split(',')
                            if len(parts) >= 2:
                                lon, lat = float(parts[0]), float(parts[1])
                                points.append((lon, lat))
                        if len(points) >= 3:
                            polygons.append(Polygon(points))
                    
                    if not polygons:
                        raise ValueError("No se pudieron crear polígonos desde el KML")
                    
                    # Crear GeoDataFrame desde las geometrías
                    gdf = gpd.GeoDataFrame({'geometry': polygons}, crs="EPSG:4326")
            if gdf.crs is None:
                gdf = gdf.set_crs("EPSG:4326")
            gdf = gdf.to_crs("EPSG:25830")             # Unificar geometría si es multi-geometría
                            geom = unary_union(gdf.geometry)
                        gdfs.append(geom)
                        names.append(Path(f.filename).stem)
                            except Exception as e:
                                            errors.append(f"{f.filename}: {str(e)}")
                            continue
            
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
                        "layer1": names[i],
                        "layer2": names[j],
                        "percentage": round(pct, 2),
                        "area_m2": round(area, 2),
                    })
                except Exception as e:
                    errors.append(f"Error cruce {names[i]}-{names[j]}: {str(e)}")

    return {
        "status": "success", 
        "intersections": intersections, 
        "total_files": len(names),
        "errors": errors
    }

@app.post("/api/ortophotos/generate")
async def generate_ortophotos(payload: dict = Body(...)):
    """
    Genera set completo de ortofotos + capas (4 niveles Zoom)
    Devuelve URLs para visualización en frontend con opacidad.
    """
    ref = payload.get("referencia")
    if not ref:
        return JSONResponse(status_code=400, content={"status": "error", "message": "Falta referencia"})

    try:
        data = urban_engine.obtener_datos_catastrales(ref)
        if data.get("status") == "error":
            return JSONResponse(status_code=500, content=data)

        coords = data.get("coordenadas")
        if not coords:
            return JSONResponse(status_code=500, content={"status": "error", "message": "No hay coordenadas"})

        # Usar la nueva lógica multi-escala del descargador completo
        resultados = catastro_complete.descargar_set_capas_completo(ref, coords, OUTPUT_DIR / ref)
        
        # Formatear respuesta para el frontend
        ortophotos = []
        for res in resultados:
            # Construir URL relativa
            base_url = f"/outputs/{ref}/images"
            item = {
                "title": f"Zoom {res['nivel']}",
                "description": "Ortofoto + Catastro",
                "zoom": res['nivel'],
                "layers": {
                    "base": f"{base_url}/{Path(res['ortofoto']).name}" if res['ortofoto'] else None,
                    "overlay": f"{base_url}/{Path(res['catastro']).name}" if res['catastro'] else None,
                    "silhouette": f"{base_url}/{Path(res['silueta']).name}" if res.get('silueta') else None,
                    "labels": f"{base_url}/{Path(res.get('callejero', '')).name}" if res.get('callejero') else None
                },
                # Compatibilidad con visor antiguo (muestra solo ortofoto si falla visor nuevo)
                "url": f"{base_url}/{Path(res['ortofoto']).name}" if res['ortofoto'] else ""
            }
            ortophotos.append(item)

        return {"status": "success", "ortophotos": ortophotos}

    except Exception as e:
        logger.error(f"Error generando ortofotos: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.post("/api/report/generate")
@app.post("/api/report/custom")
async def generate_final_report(
    ref: str = Form(...),
    empresa: str = Form(...),
    tecnico: str = Form(...),
    colegiado: str = Form(...),
    notas: str = Form(""),
    incluir_archivos: str = Form(None),
    selected_sections: str = Form(None),
    logo: UploadFile = File(None)
):
    """
    PUNTO 5: Une todo en el PDF profesional. Soporta tanto /generate como /custom.
    """
    # Usar cualquiera de los dos campos que contenga la selección
    seleccion = selected_sections or incluir_archivos or "[]"
    try:
        from fpdf import FPDF

        (OUTPUT_DIR / ref).mkdir(parents=True, exist_ok=True)

        def _safe_pdf_text(s: str) -> str:
            if s is None:
                return ""
            if not isinstance(s, str):
                s = str(s)
            return s.encode("latin-1", errors="replace").decode("latin-1")

        try:
            mapas_seleccionados = json.loads(seleccion) if seleccion else []
        except Exception:
            mapas_seleccionados = []
        if not isinstance(mapas_seleccionados, list):
            mapas_seleccionados = []

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        # Manejo de Logo
        if logo:
            logo_path = OUTPUT_DIR / f"temp_logo_{ref}_{logo.filename}"
            with open(logo_path, "wb") as buffer:
                content = await logo.read()
                buffer.write(content)
            try:
                pdf.image(str(logo_path), 10, 8, 33)
            except Exception:
                pass
            pdf.ln(20)

        # Encabezado
        pdf.set_font("Helvetica", 'B', 16)
        pdf.cell(0, 10, _safe_pdf_text("INFORME TÉCNICO DE AFECCIONES URBANÍSTICAS"), 0, 1, 'C')
        pdf.set_font("Helvetica", '', 11)
        pdf.cell(0, 10, _safe_pdf_text(f"Referencia Catastral: {ref}"), 0, 1, 'C')
        pdf.ln(10)

        # Tabla de Datos
        pdf.set_fill_color(230, 230, 230)
        pdf.set_font("Helvetica", 'B', 12)
        pdf.cell(0, 10, _safe_pdf_text("  IDENTIFICACIÓN DEL TÉCNICO"), 0, 1, 'L', True)
        pdf.set_font("Helvetica", '', 11)
        pdf.cell(0, 8, _safe_pdf_text(f"Empresa: {empresa}"), 0, 1)
        pdf.cell(0, 8, _safe_pdf_text(f"Técnico: {tecnico}"), 0, 1)
        pdf.cell(0, 8, _safe_pdf_text(f"Colegiado: {colegiado}"), 0, 1)
        pdf.ln(5)

        # Cuerpo de Notas
        if notas:
            pdf.set_font("Helvetica", 'B', 12)
            pdf.cell(0, 10, _safe_pdf_text("  NOTAS Y OBSERVACIONES"), 0, 1, 'L', True)
            pdf.set_font("Helvetica", '', 10)
            pdf.multi_cell(0, 6, _safe_pdf_text(notas))
            pdf.ln(5)

        # Inserción de Mapas (Uno por página)
        for img_url in mapas_seleccionados:
            if not img_url or not isinstance(img_url, str):
                continue
            try:
                parsed = urlparse(img_url)
                normalized_path = unquote(parsed.path or "")
            except Exception:
                normalized_path = img_url
            if normalized_path.startswith("/outputs/"):
                normalized_path = normalized_path.replace("/outputs/", "", 1)
            normalized_path = normalized_path.lstrip("/\\")
            full_img_path = (OUTPUT_DIR / normalized_path).resolve()

            try:
                full_img_path.relative_to(OUTPUT_DIR.resolve())
            except Exception:
                continue

            if full_img_path.exists():
                pdf.add_page()
                pdf.set_font("Helvetica", 'B', 14)
                pdf.cell(0, 10, _safe_pdf_text(f"PLANO: {full_img_path.stem.replace(ref+'_', '')}"), 0, 1, 'C')
                try:
                    pdf.image(str(full_img_path), x=10, y=30, w=190)
                except Exception:
                    pass

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

@app.get("/api/health/kml")
async def check_kml_support():
    """Verifica si el servidor tiene soporte para drivers KML"""
    try:
        import fiona
        drivers = fiona.supported_drivers
        kml_support = "KML" in drivers or "LIBKML" in drivers
        return {
            "status": "success",
            "kml_support": kml_support,
            "drivers": list(drivers.keys()),
            "message": "KML support available" if kml_support else "KML support not available - install KML driver"
        }
    except ImportError:
        return {"status": "error", "message": "Fiona no instalado"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    # Usar puerto configurado
    host = "0.0.0.0" if os.getenv("DOCKER_ENV") else "127.0.0.1"
    uvicorn.run(app, host=host, port=PORT)
                    
