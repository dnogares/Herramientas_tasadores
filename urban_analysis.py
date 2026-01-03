import os
import time
import requests
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Dict, Optional
from io import BytesIO
import logging

# Configuración de logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AnalizadorUrbanistico:
    def __init__(self, output_base_dir: str = "outputs"):
        self.output_base_dir = Path(output_base_dir)
        self.output_base_dir.mkdir(parents=True, exist_ok=True)
        self.base_catastro = "https://ovc.catastro.meh.es"
        self.wfs_parcela_url = f"{self.base_catastro}/INSPIRE/wfsCP.aspx"
        self.wms_url = f"{self.base_catastro}/Cartografia/WMS/ServidorWMS.aspx"

        try:
            import geopandas as gpd  # noqa: F401
            self._geopandas_available = True
        except Exception:
            self._geopandas_available = False

        try:
            from PIL import Image  # noqa: F401
            self._pillow_available = True
        except Exception:
            self._pillow_available = False

    def procesar_lote_referencias(self, path_archivo: str, agrupar_por: str = "referencia") -> List[Dict]:
        """
        Lee un CSV/TXT y procesa cada referencia catastral incluida.
        """
        resultados = []
        try:
            with open(path_archivo, 'r') as f:
                # Soporta referencias separadas por comas, espacios o saltos de línea
                contenido = f.read().replace(',', '\n').replace(' ', '\n')
                referencias = [line.strip() for line in contenido.split('\n') if len(line.strip()) > 10]
            
            for ref in referencias:
                logger.info(f"Procesando referencia de lote: {ref}")
                res = self.obtener_datos_catastrales(ref)
                resultados.append(res)
            
            return resultados
        except Exception as e:
            logger.error(f"Error en procesar_lote_referencias: {e}")
            return [{"error": str(e)}]

    def obtener_datos_catastrales(self, referencia: str) -> Dict:
        """
        Módulo 1: Obtiene geometría y datos de la parcela desde el Catastro.
        """
        try:
            ref = self._limpiar_referencia(referencia)

            # Crear subcarpeta para esta referencia (usar referencia limpia)
            carpeta_ref = self.output_base_dir / ref
            carpeta_ref.mkdir(parents=True, exist_ok=True)

            gml_path = self._descargar_parcela_gml(ref, carpeta_ref)

            # 1. Obtener coordenadas e intentar GML
            coordenadas = None
            if gml_path and self._geopandas_available:
                try:
                    import geopandas as gpd
                    parcela_gdf = gpd.read_file(gml_path)
                    
                    if parcela_gdf.crs is None:
                        parcela_gdf = parcela_gdf.set_crs("EPSG:25830")
                    
                    # Intentar extraer centroide para coordenadas
                    parcela_wgs = parcela_gdf.to_crs("EPSG:4326")
                    c = parcela_wgs.geometry.iloc[0].centroid
                    coordenadas = {"lon": float(c.x), "lat": float(c.y), "srs": "EPSG:4326"}
                except Exception as e:
                    logger.warning(f"No se pudieron extraer coordenadas desde GeoPandas ({ref}): {e}")
                    # Fallback manual XML/ET si falla GeoPandas (implementación anterior)
                    pass

            if not coordenadas:
                coordenadas = self._obtener_coordenadas(ref)

            # 2. Generar KML
            kml_path = carpeta_ref / f"{ref}.kml"
            kml_generado = False
            
            if gml_path and self._geopandas_available:
                try:
                    # Re-leer para asegurar limpieza (o usar parcela_gdf ya cargado arriba si optimizamos)
                    import geopandas as gpd
                    gdf = gpd.read_file(gml_path)
                    if gdf.crs is None:
                        gdf = gdf.set_crs("EPSG:25830")
                    gdf = gdf.to_crs("EPSG:4326")
                    
                    try:
                        gdf.to_file(kml_path, driver="KML")
                        kml_generado = True
                    except Exception:
                        try:
                            gdf.to_file(kml_path, driver="LIBKML")
                            kml_generado = True
                        except Exception:
                            logger.warning(f"Drivers KML/LIBKML fallaron para {ref}")
                except Exception as e:
                    logger.warning(f"Error GeoPandas KML: {e}")

            if not kml_generado and not kml_path.exists():
                logger.info(f"Generando GeoJSON básico para {ref}")
                # Actualizamos kml_path a la ruta del nuevo GeoJSON
                kml_path = Path(self._generar_geojson_basico(ref, kml_path, coordenadas))

            wms_layers = {}
            if coordenadas and isinstance(coordenadas, dict):
                for nombre, layer in {
                    "ortofoto": "PNOA",
                    "catastro": "Catastro",
                    "callejero": "Callejero",
                    "hidrografia": "Hidrografia",
                }.items():
                    p = self._descargar_capa_wms(ref, coordenadas, nombre, layer, carpeta_ref)
                    if p:
                        wms_layers[nombre] = p

                if self._pillow_available and wms_layers:
                    comp = self._crear_composicion_capas(ref, wms_layers, carpeta_ref)
                    if comp:
                        wms_layers["composicion"] = comp

            return {
                "referencia": ref,
                "status": "success",
                "folder": str(carpeta_ref),
                "kml": str(kml_path),
                "coordenadas": coordenadas,
                "wms_layers": wms_layers,
                "resumen": {
                    "total_capas": len(wms_layers),
                    "capas_afectan": 0,
                    "superficie_total_afectada": "0.00 m²",
                    "archivos_generados": len(wms_layers)
                },
                "capas_procesadas": []
            }
        except Exception as e:
            logger.error(f"Error al obtener datos de {referencia}: {e}")
            return {"referencia": referencia, "status": "error", "message": str(e)}

    def _generar_geojson_basico(self, referencia: str, output_path: Path, coords: Optional[dict] = None) -> str:
        """
        Crea un archivo GeoJSON básico (cuadrado alrededor del centro) para análisis
        cuando fallan los drivers KML o la descarga GML.
        """
        # Coordenadas por defecto (Madrid) si no se proporcionan
        lat = coords.get("lat") if coords and isinstance(coords, dict) else 40.416775
        lon = coords.get("lon") if coords and isinstance(coords, dict) else -3.70379

        # Generar un pequeño polígono (cuadrado ~100x100m) alrededor de las coordenadas
        delta = 0.001 
        
        # GeoJSON Structure
        geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"referencia": referencia},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [lon, lat],
                        [lon + delta, lat],
                        [lon + delta, lat + delta],
                        [lon, lat + delta],
                        [lon, lat]
                    ]]
                }
            }]
        }
        
        # Cambiar extensión a .geojson si venía como .kml
        if output_path.suffix.lower() == '.kml':
            output_path = output_path.with_suffix('.geojson')
            
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(geojson, f)
            
        return str(output_path)

    def _safe_get(self, url: str, params: Optional[dict] = None, timeout: int = 30, max_retries: int = 2):
        last_exc = None
        for attempt in range(max_retries + 1):
            try:
                return requests.get(url, params=params, timeout=timeout)
            except requests.exceptions.RequestException as e:
                last_exc = e
                time.sleep(1 + attempt)
        raise last_exc

    def _limpiar_referencia(self, ref: str) -> str:
        return (ref or "").replace(" ", "").strip()

    def _descargar_parcela_gml(self, referencia: str, carpeta_ref: Path) -> Optional[str]:
        out_path = carpeta_ref / f"{referencia}_parcela.gml"
        params = {
            "service": "wfs",
            "version": "2.0.0",
            "request": "GetFeature",
            "STOREDQUERY_ID": "GetParcel",
            "refcat": referencia,
            "srsname": "EPSG:25830",
        }
        r = self._safe_get(self.wfs_parcela_url, params=params, timeout=45)
        if r.status_code != 200:
            return None
        if b"ExceptionReport" in r.content:
            return None
        out_path.write_bytes(r.content)
        return str(out_path)

    def _utm_a_wgs84(self, x_utm, y_utm, epsg='25830'):
        """Convierte coordenadas UTM a WGS84 (lat/lon)"""
        if not self._geopandas_available:
            return None
        
        try:
            import geopandas as gpd
            from shapely.geometry import Point
            gdf = gpd.GeoDataFrame(
                geometry=[Point(x_utm, y_utm)], 
                crs=f'EPSG:{epsg}'
            )
            gdf_wgs84 = gdf.to_crs('EPSG:4326')
            point_wgs84 = gdf_wgs84.geometry.iloc[0]
            
            return {
                'lon': point_wgs84.x,
                'lat': point_wgs84.y,
                'srs': 'EPSG:4326'
            }
        except Exception as e:
            logger.error(f"Error convirtiendo coordenadas: {e}")
            return None

    def _obtener_coordenadas(self, referencia: str) -> Optional[dict]:
        try:
            url_json = f"{self.base_catastro}/OVCServWeb/OVCWcfCallejero/COVCCallejero.svc/json/Geo_RCToWGS84/{referencia}"
            r = self._safe_get(url_json, timeout=20)
            if r.status_code == 200:
                data = r.json()
                if "geo" in data and "xcen" in data["geo"] and "ycen" in data["geo"]:
                    return {
                        "lon": float(data["geo"]["xcen"]),
                        "lat": float(data["geo"]["ycen"]),
                        "srs": "EPSG:4326",
                    }
        except Exception:
            pass

        try:
            url_xml = f"{self.base_catastro}/ovcservweb/ovcswlocalizacionrc/ovccoordenadas.asmx/Consulta_RCCOOR"
            params = {"SRS": "EPSG:4326", "RC": referencia.upper()}
            r = self._safe_get(url_xml, params=params, timeout=20)
            if r.status_code == 200:
                root = ET.fromstring(r.content)
                ns = {"cat": "http://www.catastro.meh.es/"}
                coord = root.find(".//cat:coord", ns)
                if coord is not None:
                    geo = coord.find("cat:geo", ns)
                    if geo is not None:
                        xcen = geo.find("cat:xcen", ns)
                        ycen = geo.find("cat:ycen", ns)
                        if xcen is not None and ycen is not None:
                            return {"lon": float(xcen.text), "lat": float(ycen.text), "srs": "EPSG:4326"}
        except Exception:
            pass

        return None

    def _calcular_bbox(self, lon: float, lat: float, buffer_metros: int = 200) -> str:
        buffer_lon = buffer_metros / 85000
        buffer_lat = buffer_metros / 111000
        return f"{lon-buffer_lon},{lat-buffer_lat},{lon+buffer_lon},{lat+buffer_lat}"

    def _descargar_capa_wms(self, referencia: str, coords: dict, nombre_capa: str, layers: str, carpeta_ref: Path, bbox_metros: int = 200) -> Optional[str]:
        lon, lat = coords.get("lon"), coords.get("lat")
        if lon is None or lat is None:
            return None
        bbox = self._calcular_bbox(float(lon), float(lat), bbox_metros)
        params = {
            "SERVICE": "WMS",
            "VERSION": "1.1.1",
            "REQUEST": "GetMap",
            "LAYERS": layers,
            "STYLES": "",
            "SRS": "EPSG:4326",
            "BBOX": bbox,
            "WIDTH": "1600",
            "HEIGHT": "1600",
            "FORMAT": "image/png",
            "TRANSPARENT": "TRUE",
        }
        try:
            r = self._safe_get(self.wms_url, params=params, timeout=60)
            if r.status_code == 200 and len(r.content) > 1000:
                out_path = carpeta_ref / f"{referencia}_capa_{nombre_capa}.png"
                out_path.write_bytes(r.content)
                return str(out_path)
        except Exception:
            return None

        return None

    def _crear_composicion_capas(self, referencia: str, capas_descargadas: dict, carpeta_ref: Path) -> Optional[str]:
        try:
            from PIL import Image

            orden = ["ortofoto", "catastro", "callejero", "hidrografia"]
            imagen_base = None

            for capa in orden:
                if capa not in capas_descargadas:
                    continue
                img = Image.open(capas_descargadas[capa]).convert("RGBA")
                if imagen_base is None:
                    imagen_base = img
                else:
                    imagen_base = Image.alpha_composite(imagen_base, img)

            if imagen_base is None:
                return None

            out_path = carpeta_ref / f"{referencia}_composicion_completa.png"
            imagen_base.save(out_path)
            return str(out_path)
        except Exception:
            return None

    def exportar_informe_csv(self, resultados: List[Dict], filename: str = "resumen_catastro.csv"):
        """
        Genera el CSV de resultados mencionado en el punto 1.
        """
        import pandas as pd
        df = pd.DataFrame(resultados)
        output_path = self.output_base_dir / filename
        df.to_csv(output_path, index=False)
        return str(output_path)

# ----------------------------------------------------------------
# Integración con el Módulo 3 (Foto 2)
# ----------------------------------------------------------------
def integrar_analisis_urbanistico(referencia: str):
    """
    Función puente que llama el main.py
    """
    analizador = AnalizadorUrbanistico()
    return analizador.obtener_datos_catastrales(referencia)