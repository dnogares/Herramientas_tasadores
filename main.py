import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.ioff()
import os
import sys
import logging
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logger.info("=== INICIANDO APLICACIÓN ===")

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
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from urllib.parse import urlparse, unquote
from typing import List

logger.info("Importaciones básicas completadas")

# Importación de módulos locales
from urban_analysis import AnalizadorUrbanistico
from vector_analyzer import VectorAnalyzer
from catastro_engine import CatastroDownloader
from catastro_complete_downloader import CatastroCompleteDownloader
from local_layers_manager import LocalLayersManager

logger.info("Módulos locales cargados correctamente")

app = FastAPI(title="Catastro-tool")

# CORS CONFIGURATION
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CONFIGURACIÓN DE RUTAS
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "outputs"

# Configuración de CAPAS_DIR según entorno
if os.getenv("DOCKER_ENV"):
    CAPAS_DIR = Path("/app/capas")
    OUTPUT_DIR = Path("/app/outputs")
else:
    h_data = Path("H:/data")
    if h_data.exists():
        CAPAS_DIR = h_data
    else:
        CAPAS_DIR = BASE_DIR / "capas"
        CAPAS_DIR.mkdir(exist_ok=True)

STATIC_DIR = BASE_DIR / "static"

# Crear directorios
OUTPUT_DIR.mkdir(exist_ok=True)

# Montar archivos estáticos
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/outputs", StaticFiles(directory=str(OUTPUT_DIR)), name="outputs")

# Instanciar motores
urban_engine = AnalizadorUrbanistico(output_base_dir=str(OUTPUT_DIR))
vector_engine = VectorAnalyzer(output_dir=str(OUTPUT_DIR), capas_dir=str(CAPAS_DIR))
catastro_engine = CatastroDownloader(str(OUTPUT_DIR))
catastro_complete = CatastroCompleteDownloader(str(OUTPUT_DIR))
local_layers = LocalLayersManager(str(CAPAS_DIR))

# ENDPOINTS

@app.get("/")
async def read_index():
    return FileResponse(STATIC_DIR / "index_hybrid.html")

@app.post("/api/catastro/query")
async def query_catastro(data: dict = Body(...)):
    ref = data.get("referencia")
    if not ref:
        raise HTTPException(status_code=400, detail="Falta referencia")

    try:
        catastro_data = urban_engine.obtener_datos_catastrales(ref)
        
        if catastro_data.get("status") != "success":
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": f"Error obteniendo datos: {catastro_data.get('status')}"}
            )
        
        coords = catastro_data.get("coordenadas")
        wms_layers = catastro_data.get("wms_layers", {})
        
        ortophotos = []
        if coords and isinstance(coords, dict):
            try:
                ortophotos = local_layers.generar_ortofotos_multi_escala(ref, coords)
            except Exception as e:
                logger.warning(f"No se pudieron generar ortofotos locales: {e}")

        capas_procesadas = []
        for nombre_capa, path in wms_layers.items():
            if path and Path(path).exists():
                url_relativa = str(Path(path).relative_to(OUTPUT_DIR))
                capas_procesadas.append({
                    "nombre": nombre_capa.replace("_", " ").title(),
                    "estado": "Descargada",
                    "superficie": "N/A",
                    "png_url": f"/outputs/{url_relativa}",
                    "tipo": "WMS"
                })
        
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
                "wms_layers": {k: f"/outputs/{Path(v).relative_to(OUTPUT_DIR)}" for k, v in wms_layers.items() if v and Path(v).exists()}
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

@app.get("/api/layers/info")
async def get_layers_info():
    try:
        info = local_layers.get_capas_info()
        return {"status": "success", "layers": info}
    except Exception as e:
        logger.exception(f"Error obteniendo info de capas")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.post("/api/ortophotos/generate")
async def generate_ortophotos(payload: dict = Body(...)):
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

        ortophotos = local_layers.generar_ortofotos_multi_escala(ref, coords)
        
        return {"status": "success", "ortophotos": ortophotos}

    except Exception as e:
        logger.error(f"Error generando ortofotos: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

if __name__ == "__main__":
    import uvicorn
    host = "0.0.0.0" if os.getenv("DOCKER_ENV") else "127.0.0.1"
    logger.info(f"Iniciando servidor en {host}:{PORT}")
    uvicorn.run(app, host=host, port=PORT)
