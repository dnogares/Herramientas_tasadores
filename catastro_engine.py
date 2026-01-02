import os
import time
import requests
import xml.etree.ElementTree as ET
from pathlib import Path

# Intentar importar dependencias geoespaciales para la lógica de dibujo
try:
    import geopandas as gpd
    from shapely.geometry import Point
    GEOPANDAS_AVAILABLE = True
except ImportError:
    GEOPANDAS_AVAILABLE = False

try:
    from PIL import Image, ImageDraw
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False

class CatastroDownloader:
    """
    Motor de descarga de Catastro optimizado para integración en FastAPI.
    No contiene referencias fijas; todo se recibe por parámetro desde el frontend.
    """
    def __init__(self, output_dir="outputs"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.base_catastro = "https://ovc.catastro.meh.es"
        self.wms_url = "https://ovc.catastro.meh.es/Cartografia/WMS/ServidorWMS.aspx"

    def _obtener_epsg_por_provincia(self, ref):
        """Detecta el Huso UTM según los dos primeros dígitos de la RC."""
        prov = ref[:2]
        # Canarias: Las Palmas (35) y Santa Cruz de Tenerife (38) -> Huso 28
        if prov in ['35', '38']:
            return 'EPSG:25828'
        # Resto de España (Simplificado a Huso 30, el estándar para la mayoría)
        return 'EPSG:25830'

    def _safe_get(self, url, params=None, timeout=30):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            return r
        except Exception as e:
            return None

    def obtener_coordenadas(self, ref):
        """Consulta al servicio JSON de catastro para obtener lat/lon."""
        url = f"{self.base_catastro}/OVCServWeb/OVCWcfCallejero/COVCCallejero.svc/json/Geo_RCToWGS84/{ref}"
        res = self._safe_get(url)
        if res:
            data = res.json()
            if 'geo' in data:
                return {
                    'lon': float(data['geo']['xcen']),
                    'lat': float(data['geo']['ycen']),
                    'srs': 'EPSG:4326'
                }
        return None

    def descargar_todo(self, referencia_input):
        """
        Método principal llamado por el backend de FastAPI.
        """
        ref = "".join(referencia_input.split()).upper()
        ref_dir = self.output_dir / ref
        ref_dir.mkdir(parents=True, exist_ok=True)
        
        epsg = self._obtener_epsg_por_provincia(ref)
        log = {
            "referencia": ref,
            "epsg_utilizado": epsg,
            "archivos": {},
            "status": "procesando"
        }

        # 1. Descarga de GML de Parcela (Formato INSPIRE)
        url_gml = f"{self.base_catastro}/INSPIRE/wfsCP.aspx"
        p_gml = {
            'service': 'wfs',
            'version': '2.0.0',
            'request': 'GetFeature',
            'STOREDQUERY_ID': 'GetParcel',
            'refcat': ref,
            'srsname': epsg
        }
        
        res_gml = self._safe_get(url_gml, params=p_gml)
        if res_gml and len(res_gml.content) > 500:
            gml_path = ref_dir / f"{ref}_parcela.gml"
            gml_path.write_bytes(res_gml.content)
            log["archivos"]["gml"] = str(gml_path)

        # 2. Obtener Coordenadas WGS84 para el visor del Frontend
        coords = self.obtener_coordenadas(ref)
        if coords:
            log["coordenadas"] = coords
            
            # 3. Descarga de Imagen Catastral (WMS)
            # Definimos un BBOX pequeño alrededor del punto
            buffer = 0.0015 
            bbox = f"{coords['lon']-buffer},{coords['lat']-buffer},{coords['lon']+buffer},{coords['lat']+buffer}"
            
            p_wms = {
                'SERVICE': 'WMS', 'VERSION': '1.1.1', 'REQUEST': 'GetMap',
                'LAYERS': 'Catastro', 'SRS': 'EPSG:4326', 'BBOX': bbox,
                'WIDTH': '1200', 'HEIGHT': '1200', 'FORMAT': 'image/png', 'TRANSPARENT': 'TRUE'
            }
            
            res_wms = self._safe_get(self.wms_url, params=p_wms)
            if res_wms and len(res_wms.content) > 1000:
                img_path = ref_dir / f"{ref}_plano.png"
                img_path.write_bytes(res_wms.content)
                log["archivos"]["plano_png"] = str(img_path)
                log["status"] = "success"
        else:
            log["status"] = "partial_error"
            log["message"] = "No se pudieron obtener coordenadas espaciales"

        return log

# NOTA: Se ha eliminado el bloque if __name__ == "__main__" para evitar 
# ejecuciones accidentales durante la importación en FastAPI.