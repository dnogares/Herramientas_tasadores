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

# Configuración de logging para ver errores en la consola de la API
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Dependencias opcionales
try:
    import geopandas as gpd
    from shapely.geometry import shape, mapping
    GEOPANDAS_AVAILABLE = True
except ImportError:
    GEOPANDAS_AVAILABLE = False
    logger.warning("⚠️ GeoPandas no detectado. No se generarán archivos KML.")

try:
    from PIL import Image
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    logger.warning("⚠️ Pillow no detectado. No se generará la imagen de COMPOSICIÓN.")

class CatastroDownloader:
    def __init__(self, output_base_dir: str):
        self.output_base_dir = Path(output_base_dir)
        self.output_base_dir.mkdir(parents=True, exist_ok=True)
        self.base_url_inspire = "https://ovc.catastro.meh.es/INSPIRE/wfsCP.aspx"
        self.wms_url = "https://ovc.catastro.meh.es/Cartografia/WMS/ServidorWMS.aspx"
        
    def limpiar_referencia(self, ref: str) -> str:
        return ref.replace(' ', '').strip().upper()

    def _crear_estructura_carpetas(self, ref: str) -> Dict[str, Path]:
        """Organiza los resultados en subcarpetas por función"""
        ref_path = self.output_base_dir / ref
        dirs = {
            'raiz': ref_path,
            'imagenes': ref_path / "imagenes",
            'geometrias': ref_path / "geometrias",
            'datos': ref_path / "datos",
            'informes': ref_path / "informes"
        }
        for d in dirs.values():
            d.mkdir(parents=True, exist_ok=True)
        return dirs

    # ==========================================
    # SISTEMA DE COORDENADAS (TRIPLE FALLBACK)
    # ==========================================
    def obtener_coordenadas(self, ref: str) -> Optional[Dict]:
        """Nivel 1: Servicio JSON / Nivel 2: Servicio XML"""
        # Intento 1: JSON (Más rápido)
        try:
            url = f"https://ovc.catastro.meh.es/OVCServWeb/OVCWcfCallejero/COVCCallejero.svc/json/Geo_RCToWGS84/{ref}"
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()
                if 'geo' in data:
                    return {'lon': float(data['geo']['xcen']), 'lat': float(data['geo']['ycen']), 'src': 'JSON'}
        except: pass

        # Intento 2: XML Oficial (Más estable)
        try:
            url_xml = "https://ovc.catastro.meh.es/ovcservweb/ovcswlocalizacionrc/ovccoordenadas.asmx/Consulta_RCCOOR"
            params = {"SRS": "EPSG:4326", "RC": ref}
            r = requests.get(url_xml, params=params, timeout=10)
            if r.status_code == 200:
                root = ET.fromstring(r.content)
                ns = {"cat": "http://www.catastro.meh.es/"}
                coord = root.find(".//cat:coord", ns)
                if coord is not None:
                    geo = coord.find("cat:geo", ns)
                    return {
                        'lon': float(geo.find("cat:xcen", ns).text),
                        'lat': float(geo.find("cat:ycen", ns).text),
                        'src': 'XML'
                    }
        except: pass
        return None

    def extraer_coordenadas_de_gml(self, gml_content: bytes) -> Optional[Dict]:
        """Nivel 3: Rescate desde el archivo GML (Si los servicios fallan)"""
        try:
            root = ET.fromstring(gml_content)
            ns = {'gml': 'http://www.opengis.net/gml/3.2'}
            pos_list = root.find('.//gml:posList', ns)
            if pos_list is not None:
                coords = pos_list.text.split()
                # El GML suele venir en Lat, Lon (EPSG:4326) o X, Y (UTM)
                # Tomamos el primer par de puntos como referencia de centro
                return {'lat': float(coords[0]), 'lon': float(coords[1]), 'src': 'GML_EXTRACT'}
        except Exception as e:
            logger.error(f"Error extrayendo de GML: {e}")
        return None

    # ==========================================
    # DESCARGAS DE DATOS
    # ==========================================
    def descargar_geometrias(self, ref: str, dirs: Dict) -> Optional[bytes]:
        """Descarga GML y genera KML si es posible"""
        params = {
            'service': 'wfs', 'version': '2.0.0', 'request': 'GetFeature',
            'STOREDQUERY_ID': 'GetParcel', 'refcat': ref, 'srsname': 'EPSG:4326'
        }
        try:
            r = requests.get(self.base_url_inspire, params=params, timeout=25)
            if r.status_code == 200 and b'Exception' not in r.content:
                gml_path = dirs['geometrias'] / f"{ref}_parcela.gml"
                gml_path.write_bytes(r.content)
                
                # Conversión a KML
                if GEOPANDAS_AVAILABLE:
                    try:
                        gdf = gpd.read_file(BytesIO(r.content))
                        gdf.to_file(dirs['geometrias'] / f"{ref}_parcela.kml", driver='KML')
                    except: pass
                return r.content
        except Exception as e:
            logger.error(f"Error en descarga GML: {e}")
        return None

    def descargar_imagenes_wms(self, ref: str, coords: Dict, dirs: Dict):
        """Descarga Ortofotos y Mapas Catastrales"""
        lon, lat = coords['lon'], coords['lat']
        buffer = 0.0018  # Zoom aproximado
        bbox = f"{lon-buffer},{lat-buffer},{lon+buffer},{lat+buffer}"
        
        capas = {'ortofoto': 'PNOA', 'catastro': 'Catastro'}
        img_paths = {}

        for nombre, layer in capas.items():
            params = {
                'SERVICE': 'WMS', 'VERSION': '1.1.1', 'REQUEST': 'GetMap',
                'LAYERS': layer, 'SRS': 'EPSG:4326', 'BBOX': bbox,
                'WIDTH': '1200', 'HEIGHT': '1200', 'FORMAT': 'image/png', 'TRANSPARENT': 'TRUE'
            }
            try:
                r = requests.get(self.wms_url, params=params, timeout=20)
                if r.status_code == 200:
                    path = dirs['imagenes'] / f"{ref}_{nombre}.png"
                    path.write_bytes(r.content)
                    img_paths[nombre] = path
            except: pass

        # Crear composición (Mix de foto + líneas de catastro)
        if PILLOW_AVAILABLE and 'ortofoto' in img_paths and 'catastro' in img_paths:
            try:
                img1 = Image.open(img_paths['ortofoto']).convert("RGBA")
                img2 = Image.open(img_paths['catastro']).convert("RGBA")
                composicion = Image.alpha_composite(img1, img2)
                composicion.save(dirs['imagenes'] / f"{ref}_COMPOSICION.png")
            except: pass

    # ==========================================
    # MÉTODO PRINCIPAL (EL QUE LLAMA MAIN.PY)
    # ==========================================
    def descargar_todo_completo(self, referencia: str) -> Dict:
        ref = self.limpiar_referencia(referencia)
        dirs = self._crear_estructura_carpetas(ref)
        
        logger.info(f"🚀 Iniciando proceso completo para: {ref}")

        # 1. Intentar Geometría (es lo más importante)
        gml_content = self.descargar_geometrias(ref, dirs)

        # 2. Intentar Coordenadas (Servicios oficiales)
        coords = self.obtener_coordenadas(ref)

        # 3. SI FALLA EL PASO 2: Rescate desde GML
        if not coords and gml_content:
            logger.info("⚠️ Servicios de coordenadas fallaron. Usando rescate GML...")
            coords = self.extraer_coordenadas_de_gml(gml_content)

        if not coords:
            return {"status": "error_coords", "referencia": ref}

        # 4. Descargar Imágenes con las coordenadas obtenidas
        self.descargar_imagenes_wms(ref, coords, dirs)

        # 5. Guardar metadatos JSON
        info = {
            "referencia": ref,
            "coordenadas": coords,
            "fecha": datetime.now().isoformat(),
            "carpetas": {k: str(v.relative_to(self.output_base_dir)) for k, v in dirs.items()}
        }
        with open(dirs['datos'] / "info.json", 'w', encoding='utf-8') as f:
            json.dump(info, f, indent=4)

        return {
            "status": "success",
            "referencia": ref,
            "data": info
        }