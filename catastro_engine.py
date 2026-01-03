import os
import time
import json
import requests
import xml.etree.ElementTree as ET
from pathlib import Path
from io import BytesIO
from datetime import datetime
from typing import Dict, Optional, List
import logging

# Configuración de logging
logger = logging.getLogger(__name__)

# Dependencias opcionales con manejo de errores
try:
    import geopandas as gpd
    from shapely.geometry import Point, mapping
    GEOPANDAS_AVAILABLE = True
except ImportError:
    GEOPANDAS_AVAILABLE = False
    logger.warning("GeoPandas no instalado. Algunas funciones espaciales fallarán.")

try:
    from PIL import Image, ImageDraw, ImageFont
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    logger.warning("Pillow no instalado. No se crearán composiciones de imagen.")

class CatastroDownloader:
    def __init__(self, output_base_dir: str):
        self.output_base_dir = Path(output_base_dir)
        self.base_url_ovc = "https://ovc.catastro.minhafp.gob.es/ovc/Proxy.ashx"
        self.base_url_inspire = "https://ovc.catastro.meh.es/INSPIRE/wfsCP.aspx"
        
        # Configuración de capas WMS
        self.capas_wms = {
            'catastro': 'Catastro',
            'ortofoto': 'PNOA',
            'callejero': 'Callejero',
            'hidrografia': 'Hidrografia'
        }

    def _crear_estructura_carpetas(self, ref: str) -> Dict[str, Path]:
        """Crea la estructura de subcarpetas para una referencia"""
        ref_path = self.output_base_dir / ref
        dirs = {
            'raiz': ref_path,
            'imagenes': ref_path / "imagenes",
            'geometrias': ref_path / "geometrias",
            'informes': ref_path / "informes",
            'datos': ref_path / "datos"
        }
        for d in dirs.values():
            d.mkdir(parents=True, exist_ok=True)
        return dirs

    def limpiar_referencia(self, ref: str) -> str:
        return ref.replace(' ', '').strip().upper()

    # --- OBTENCIÓN DE COORDENADAS ---
    def obtener_coordenadas(self, ref: str) -> Optional[Dict]:
        """Obtiene coordenadas WGS84 mediante el servicio oficial"""
        url = f"https://ovc.catastro.meh.es/OVCServWeb/OVCWcfCallejero/COVCCallejero.svc/json/Geo_RCToWGS84/{ref}"
        try:
            r = requests.get(url, timeout=20)
            if r.status_code == 200:
                data = r.json()
                if 'geo' in data:
                    return {'lon': float(data['geo']['xcen']), 'lat': float(data['geo']['ycen'])}
        except Exception as e:
            logger.error(f"Error obteniendo coordenadas: {e}")
        return None

    # --- DESCARGAS DE GEOMETRÍA ---
    def descargar_geometrias(self, ref: str, dirs: Dict):
        """Descarga GML de parcela y edificio"""
        params_base = {'service': 'wfs', 'version': '2.0.0', 'request': 'GetFeature', 'refcat': ref, 'srsname': 'EPSG:25830'}
        
        # 1. Parcela
        try:
            p = {**params_base, 'STOREDQUERY_ID': 'GetParcel'}
            r = requests.get(self.base_url_inspire, params=p, timeout=30)
            if r.status_code == 200 and b'Exception' not in r.content:
                gml_path = dirs['geometrias'] / f"{ref}_parcela.gml"
                gml_path.write_bytes(r.content)
                # Convertir a KML si es posible
                if GEOPANDAS_AVAILABLE:
                    try:
                        gdf = gpd.read_file(BytesIO(r.content))
                        gdf.to_crs('EPSG:4326').to_file(dirs['geometrias'] / f"{ref}_parcela.kml", driver='KML')
                    except: pass
                return gml_path
        except Exception as e:
            logger.error(f"Error geometría parcela: {e}")
        return None

    # --- DESCARGAS DE IMÁGENES (WMS) ---
    def descargar_mapas(self, ref: str, coords: Dict, dirs: Dict, gml_path: Path = None):
        """Descarga capas WMS y crea la composición"""
        lon, lat = coords['lon'], coords['lat']
        buffer = 0.002 # Aprox 200m
        bbox = f"{lon-buffer},{lat-buffer},{lon+buffer},{lat+buffer}"
        
        wms_url = "https://ovc.catastro.meh.es/Cartografia/WMS/ServidorWMS.aspx"
        fotos_descargadas = {}

        for nombre, layer in self.capas_wms.items():
            params = {
                'SERVICE': 'WMS', 'VERSION': '1.1.1', 'REQUEST': 'GetMap',
                'LAYERS': layer, 'SRS': 'EPSG:4326', 'BBOX': bbox,
                'WIDTH': '1200', 'HEIGHT': '1200', 'FORMAT': 'image/png', 'TRANSPARENT': 'TRUE'
            }
            try:
                r = requests.get(wms_url, params=params, timeout=30)
                if r.status_code == 200 and len(r.content) > 1000:
                    img_path = dirs['imagenes'] / f"{ref}_{nombre}.png"
                    img_path.write_bytes(r.content)
                    fotos_descargadas[nombre] = img_path
            except: continue

        # Crear composición si Pillow está disponible
        if PILLOW_AVAILABLE and 'ortofoto' in fotos_descargadas:
            self._crear_composicion(ref, fotos_descargadas, dirs['imagenes'])

    def _crear_composicion(self, ref: str, fotos: Dict, out_dir: Path):
        try:
            base = Image.open(fotos['ortofoto']).convert('RGBA')
            if 'catastro' in fotos:
                overlay = Image.open(fotos['catastro']).convert('RGBA')
                base = Image.alpha_composite(base, overlay)
            
            # Guardar resultado final
            base.save(out_dir / f"{ref}_COMPOSICION.png")
        except Exception as e:
            logger.error(f"Error en composición: {e}")

    # --- FLUJO PRINCIPAL ---
    def descargar_todo_completo(self, referencia: str) -> Dict:
        """Este es el método que llamará main.py para hacerlo TODO"""
        ref = self.limpiar_referencia(referencia)
        dirs = self._crear_estructura_carpetas(ref)
        
        resultado = {
            "referencia": ref,
            "status": "iniciado",
            "archivos": [],
            "carpetas": {k: str(v.relative_to(self.output_base_dir)) for k, v in dirs.items()}
        }

        # 1. Coordenadas
        coords = self.obtener_coordenadas(ref)
        if not coords:
            resultado["status"] = "error_coords"
            return resultado

        # 2. Geometrías (GML/KML)
        gml_parcela = self.descargar_geometrias(ref, dirs)
        
        # 3. Mapas e Imágenes
        self.descargar_mapas(ref, coords, dirs, gml_parcela)

        # 4. Datos JSON de consulta
        info_path = dirs['datos'] / f"{ref}_info.json"
        with open(info_path, 'w') as f:
            json.dump({"ref": ref, "coords": coords, "fecha": datetime.now().isoformat()}, f)

        resultado["status"] = "success"
        resultado["coordenadas"] = coords
        return resultado