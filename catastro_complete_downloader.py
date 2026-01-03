#!/usr/bin/env python3
"""
catastro_complete_downloader.py - Integración completa con organización por tipos
================================================================================

Basado en catastro_downloader6.py con:
- Descarga completa de todos los documentos Catastro
- Organización automática por tipo de archivo
- Soporte para lotes con clasificación inteligente
- Generación de ZIP comprimido por referencia

Autor: Sistema integrado Catastro-tool
Fecha: 2025
"""

import os
import time
import json
import requests
import zipfile
from pathlib import Path
from io import BytesIO
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple
import logging

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Dependencias opcionales
try:
    import geopandas as gpd
    from shapely.geometry import mapping, Point
    GEOPANDAS_AVAILABLE = True
except Exception:
    GEOPANDAS_AVAILABLE = False

try:
    from PIL import Image, ImageDraw, ImageFont
    PILLOW_AVAILABLE = True
except Exception:
    PILLOW_AVAILABLE = False


def safe_get(url, params=None, headers=None, timeout=30, max_retries=2, method='get', json_body=None):
    """Wrapper con reintentos para requests"""
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            if method.lower() == 'get':
                r = requests.get(url, params=params, headers=headers, timeout=timeout)
            else:
                r = requests.post(url, params=params, headers=headers, json=json_body, timeout=timeout)
            return r
        except requests.exceptions.RequestException as e:
            last_exc = e
            time.sleep(1 + attempt)
    raise last_exc


class CatastroCompleteDownloader:
    def __init__(self, output_dir="outputs"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Capas WMS del Catastro
        self.capas_wms = {
            'catastro': 'Catastro',
            'ortofoto': 'PNOA',
            'callejero': 'Callejero',
            'hidrografia': 'Hidrografia',
        }

        # Servicios WFS para afectaciones
        self.servicios_wfs = {
            'espacios_naturales': {
                'url': 'https://www.miteco.gob.es/wfs/espacios_protegidos',
                'layer': 'espacios_protegidos',
                'descripcion': 'Espacios Naturales Protegidos',
                'categoria': 'ambiental',
                'impacto_valor': 'MEDIO-ALTO'
            },
            'zonas_inundables': {
                'url': 'https://www.miteco.gob.es/wfs/snczi',
                'layer': 'zonas_inundables',
                'descripcion': 'Zonas de Riesgo de Inundación SNCZI',
                'categoria': 'riesgos',
                'impacto_valor': 'ALTO'
            },
            'dph': {
                'url': 'https://www.miteco.gob.es/wfs/ide_hidrografia',
                'layer': 'dph',
                'descripcion': 'Dominio Público Hidráulico',
                'categoria': 'ambiental',
                'impacto_valor': 'MEDIO'
            },
            'carreteras': {
                'url': 'https://www.ine.es/wfs/transporte',
                'layer': 'carreteras',
                'descripcion': 'Red de Carreteras',
                'categoria': 'infraestructuras',
                'impacto_valor': 'BAJO'
            }
        }

        self.base_catastro = "https://ovc.catastro.meh.es"

    def limpiar_referencia(self, ref: str) -> str:
        return ref.replace(' ', '').strip()

    def extraer_coordenadas_desde_gml(self, gml_path):
        """Extrae coordenadas del GML de parcela descargado"""
        try:
            tree = ET.parse(gml_path)
            root = tree.getroot()
            
            # Namespaces correctos para GML 3.2
            ns = {
                'gml': 'http://www.opengis.net/gml/3.2',
                'cp': 'http://inspire.ec.europa.eu/schemas/cp/4.0'
            }
            
            # MÉTODO 1: Punto de referencia
            ref_point = root.find('.//cp:referencePoint/gml:Point/gml:pos', ns)
            if ref_point is not None and ref_point.text:
                coords = ref_point.text.strip().split()
                if len(coords) >= 2:
                    x_utm = float(coords[0])
                    y_utm = float(coords[1])
                    return {
                        'x_utm': x_utm,
                        'y_utm': y_utm,
                        'epsg': '25830',
                        'source': 'referencePoint'
                    }
            
            # MÉTODO 2: Calcular centroide del polígono
            poslist = root.find('.//gml:posList', ns)
            if poslist is not None and poslist.text:
                coords = [float(x) for x in poslist.text.strip().split()]
                x_coords = coords[0::2]
                y_coords = coords[1::2]
                
                if x_coords and y_coords:
                    centroid_x = sum(x_coords) / len(x_coords)
                    centroid_y = sum(y_coords) / len(y_coords)
                    return {
                        'x_utm': centroid_x,
                        'y_utm': centroid_y,
                        'epsg': '25830',
                        'source': 'centroid'
                    }
            
            return None
            
        except Exception as e:
            logger.error(f"    ⚠️ Error extrayendo coordenadas del GML: {e}")
            return None

    def utm_a_wgs84(self, x_utm, y_utm, epsg='25830'):
        """Convierte coordenadas UTM a WGS84 (lat/lon)"""
        if not GEOPANDAS_AVAILABLE:
            return None
        
        try:
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
            logger.error(f"    ⚠️ Error convirtiendo coordenadas: {e}")
            return None

    def obtener_coordenadas(self, referencia: str, gml_parcela_path=None):
        """Obtiene coordenadas con estrategia de fallback"""
        ref = self.limpiar_referencia(referencia)
        
        # MÉTODO 1: Desde GML de parcela
        if gml_parcela_path and os.path.exists(gml_parcela_path):
            coords_utm = self.extraer_coordenadas_desde_gml(gml_parcela_path)
            if coords_utm:
                coords_wgs84 = self.utm_a_wgs84(coords_utm['x_utm'], coords_utm['y_utm'])
                if coords_wgs84:
                    return coords_wgs84
        
        # MÉTODO 2: Servicio JSON rápido
        try:
            url_json = f"{self.base_catastro}/OVCServWeb/OVCWcfCallejero/COVCCallejero.svc/json/Geo_RCToWGS84/{ref}"
            r = safe_get(url_json, timeout=20)
            if r.status_code == 200:
                data = r.json()
                if 'geo' in data and 'xcen' in data['geo'] and 'ycen' in data['geo']:
                    lon = float(data['geo']['xcen'])
                    lat = float(data['geo']['ycen'])
                    return {'lon': lon, 'lat': lat, 'srs': 'EPSG:4326'}
        except Exception as e:
            logger.warning(f"  ⚠️ Error método JSON: {e}")

        # MÉTODO 3: Servicio XML
        try:
            url_xml = f"{self.base_catastro}/ovcservweb/ovcswlocalizacionrc/ovccoordenadas.asmx/Consulta_RCCOOR"
            params = {'SRS': 'EPSG:4326', 'RC': ref.upper()}
            r = safe_get(url_xml, params=params, timeout=20)
            if r.status_code == 200:
                root = ET.fromstring(r.content)
                ns = {'cat': 'http://www.catastro.meh.es/'}
                coord = root.find('.//cat:coord', ns)
                if coord is not None:
                    geo = coord.find('cat:geo', ns)
                    if geo is not None:
                        xcen = geo.find('cat:xcen', ns)
                        ycen = geo.find('cat:ycen', ns)
                        if xcen is not None and ycen is not None:
                            lon = float(xcen.text)
                            lat = float(ycen.text)
                            return {'lon': lon, 'lat': lat, 'srs': 'EPSG:4326'}
        except Exception as e:
            logger.warning(f"  ⚠️ Error método XML: {e}")

        return None

    def calcular_bbox(self, lon, lat, buffer_metros=200):
        """Calcula BBOX para WMS"""
        buffer_lon = buffer_metros / 85000
        buffer_lat = buffer_metros / 111000
        return f"{lon-buffer_lon},{lat-buffer_lat},{lon+buffer_lon},{lat+buffer_lat}"

    def descargar_consulta_descriptiva(self, referencia: str, output_dir: Path):
        """Descarga consulta descriptiva y guarda en carpeta JSON"""
        ref = self.limpiar_referencia(referencia)
        json_dir = output_dir / "json"
        json_dir.mkdir(exist_ok=True)
        
        try:
            url_json = f"{self.base_catastro}/OVCServWeb/OVCWcfCallejero/COVCCallejero.svc/json/Geo_RCToWGS84/{ref}"
            r = safe_get(url_json, timeout=20)
            if r.status_code == 200:
                data = r.json()
                out_json = json_dir / f"{ref}_consulta_descriptiva.json"
                with open(out_json, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                
                # También guardar HTML en carpeta html
                html_dir = output_dir / "html"
                html_dir.mkdir(exist_ok=True)
                html = self.generar_html_descriptivo(data, ref)
                out_html = html_dir / f"{ref}_consulta_descriptiva.html"
                with open(out_html, 'w', encoding='utf-8') as f:
                    f.write(html)
                
                return data
        except Exception as e:
            logger.error(f"  ⚠️ Error consulta descriptiva: {e}")
        return None

    def generar_html_descriptivo(self, data, ref):
        """Genera HTML descriptivo básico"""
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Consulta {ref}</title>
<style>body {{ font-family: sans-serif; margin: 20px; }} .seccion {{ margin-bottom: 20px; padding: 10px; border: 1px solid #ccc; }}</style>
</head><body><h1>Consulta {ref}</h1>
"""
        if data and 'ldt' in data:
            html += f"<div class='seccion'><h3>Dirección</h3><p>{data['ldt']}</p></div>"
        html += "</body></html>"
        return html

    def calcular_bbox_escala(self, lon_centro, lat_centro, nivel):
        """
        Calcula BBOX para 4 niveles de zoom.
        Nivel 1: España (aprox 1000km)
        Nivel 2: Región (aprox 50km)
        Nivel 3: Local/Municipio (aprox 2km)
        Nivel 4: Parcela (aprox 200m)
        """
        # Metros de 'radio' aproximado para cada nivel
        radios = {
            1: 600000,  # España entera
            2: 25000,   # Comarca/Región
            3: 1000,    # Municipio/Barrio
            4: 150      # Parcela (detalle)
        }
        
        radio = radios.get(nivel, 150)
        
        # Conversión aproximada a grados (en latitudes medias de España)
        # 1 grado lat ~ 111km
        # 1 grado lon ~ 85km
        delta_lat = radio / 111000.0
        delta_lon = radio / 85000.0
        
        return f"{lon_centro - delta_lon},{lat_centro - delta_lat},{lon_centro + delta_lon},{lat_centro + delta_lat}"

    def descargar_set_capas_completo(self, referencia, coords, output_dir: Path):
        """
        Descarga el set completo de 4 ortofotos + capas superpuestas
        Todas comparten el mismo BBOX para poder superponerse perfectamente.
        """
        ref = self.limpiar_referencia(referencia)
        images_dir = output_dir / "images"
        images_dir.mkdir(exist_ok=True, parents=True)
        
        lon, lat = coords['lon'], coords['lat']
        
        # 4 Niveles de Zoom
        niveles = [
            (1, "Nacional"),
            (2, "Regional"),
            (3, "Local"),
            (4, "Parcela")
        ]
        
        resumen_descargas = []

        for nivel, nombre_nivel in niveles:
            bbox = self.calcular_bbox_escala(lon, lat, nivel)
            suffix = f"zoom{nivel}_{nombre_nivel}"
            
            # 1. Ortofoto Base (PNOA) - Opaca
            path_orto = self._descargar_wms_generico(
                bbox, "PNOA", images_dir / f"{ref}_Ortofoto_{suffix}.png"
            )
            
            # 2. Capa Catastro - Transparente (para superponer)
            path_cat = self._descargar_wms_generico(
                bbox, "Catastro", images_dir / f"{ref}_Catastro_{suffix}.png", transparent=True
            )
            
            # 3. Capa Callejero - Transparente
            path_call = self._descargar_wms_generico(
                bbox, "Callejero", images_dir / f"{ref}_Callejero_{suffix}.png", transparent=True
            )
            
            resumen_descargas.append({
                "nivel": nombre_nivel,
                "ortofoto": str(path_orto) if path_orto else None,
                "catastro": str(path_cat) if path_cat else None
            })
            
            logger.info(f"    📷 Generado Zoom {nivel}: {nombre_nivel}")

        return resumen_descargas

    def _descargar_wms_generico(self, bbox, layers, output_path: Path, transparent=False):
        """Helper para descargas WMS estandarizadas"""
        wms_url = f"{self.base_catastro}/Cartografia/WMS/ServidorWMS.aspx"
        params = {
            'SERVICE': 'WMS', 'VERSION': '1.1.1', 'REQUEST': 'GetMap',
            'LAYERS': layers, 'STYLES': '', 'SRS': 'EPSG:4326', 
            'BBOX': bbox,
            'WIDTH': '1600', 'HEIGHT': '1600', # Tamaño fijo para todas
            'FORMAT': 'image/png', 
            'TRANSPARENT': 'TRUE' if transparent else 'FALSE'
        }
        
        # Si es PNOA (Ortofoto), a veces requiere BGCOLOR o no ser transparente para verse bien de fondo
        if layers == "PNOA":
            params['TRANSPARENT'] = 'FALSE'
            
        try:
            r = safe_get(wms_url, params=params, timeout=60)
            if r.status_code == 200 and len(r.content) > 1000:
                with open(output_path, 'wb') as f:
                    f.write(r.content)
                return output_path
        except Exception:
            pass
        return None

    def descargar_capas_multiples(self, referencia, coords, output_dir: Path):
        """
        Versión mejorada: Llama al generador multi-escala.
        Mantiene compatibilidad con el nombre anterior.
        """
        logger.info("  🗺️ Generando Ortofotos Multi-Escala y Capas...")
        resultados = self.descargar_set_capas_completo(referencia, coords, output_dir)
        return len(resultados) > 0

    def crear_composicion_capas(self, referencia, capas_descargadas, coords, output_dir: Path):
        # Deprecado en favor de descargar_set_capas_completo que baja las capas separadas
        # para permitir control de opacidad en el cliente.
        pass

    def analizar_afectaciones(self, referencia, archivo_gml_parcela, output_dir: Path):
        """Analiza afectaciones y guarda en carpeta json"""
        if not GEOPANDAS_AVAILABLE:
            logger.warning("  ⚠️ GeoPandas no disponible - análisis omitido")
            return None
        
        ref = self.limpiar_referencia(referencia)
        json_dir = output_dir / "json"
        json_dir.mkdir(exist_ok=True)
        html_dir = output_dir / "html"
        html_dir.mkdir(exist_ok=True)
        
        logger.info("  🔍 Analizando afectaciones...")
        
        try:
            parcela_gdf = gpd.read_file(archivo_gml_parcela)
            if parcela_gdf.empty:
                return None

            if parcela_gdf.crs is None:
                parcela_gdf.set_crs('EPSG:25830', inplace=True)
            parcela_gdf = parcela_gdf.to_crs('EPSG:4326')
            geom_parcela = parcela_gdf.geometry.iloc[0]
            bounds = geom_parcela.bounds

            parcela_utm = parcela_gdf.to_crs('EPSG:25830')
            area_m2 = parcela_utm.geometry.area.iloc[0]
            centroide_wgs = geom_parcela.centroid
            centroide_utm = parcela_utm.geometry.centroid.iloc[0]

            afectaciones = {
                'referencia': ref,
                'area_parcela_m2': round(float(area_m2), 2),
                'coordenadas': {
                    'latitud': round(float(centroide_wgs.y), 6),
                    'longitud': round(float(centroide_wgs.x), 6),
                    'utm_x': round(float(centroide_utm.x), 2),
                    'utm_y': round(float(centroide_utm.y), 2),
                    'huso_utm': 30
                },
                'afectaciones_detectadas': []
            }

            # Consultar cada servicio WFS
            for nombre_servicio, config in self.servicios_wfs.items():
                logger.info(f"    🔎 {config['descripcion']}...")
                try:
                    params = {
                        'service': 'WFS', 'version': '2.0.0', 'request': 'GetFeature',
                        'typeName': config['layer'],
                        'bbox': f"{bounds[0]},{bounds[1]},{bounds[2]},{bounds[3]},EPSG:4326",
                        'srsName': 'EPSG:4326', 'outputFormat': 'GML3'
                    }
                    r = safe_get(config['url'], params=params, timeout=60)
                    if r.status_code == 200 and len(r.content) > 500 and b'ExceptionReport' not in r.content:
                        features_gdf = gpd.read_file(BytesIO(r.content))
                        if not features_gdf.empty:
                            features_gdf = features_gdf.to_crs(parcela_gdf.crs)
                            inter = gpd.overlay(parcela_gdf, features_gdf, how='intersection')
                            if not inter.empty and inter.geometry.area.sum() > 0:
                                area_afect = inter.to_crs('EPSG:25830').geometry.area.sum()
                                porcentaje = (area_afect / afectaciones['area_parcela_m2']) * 100
                                afec = {
                                    'tipo': nombre_servicio,
                                    'descripcion': config['descripcion'],
                                    'detectado': True,
                                    'area_afectada_m2': round(float(area_afect), 2),
                                    'porcentaje_parcela': round(float(porcentaje), 2),
                                    'numero_elementos': len(inter)
                                }
                                for col in ['nombre', 'name', 'NOMBRE', 'NAME']:
                                    if col in inter.columns:
                                        afec['nombres'] = inter[col].dropna().tolist()
                                        break
                                afectaciones['afectaciones_detectadas'].append(afec)
                                logger.info(f"      ✅ AFECTACIÓN: {afec['porcentaje_parcela']:.1f}%")
                            else:
                                logger.info("      ✓ Sin afectación")
                        else:
                            logger.info("      ✓ Sin elementos")
                    else:
                        logger.warning(f"      ⚠️ Status {r.status_code}")
                except Exception as e:
                    logger.error(f"      ❌ Error: {e}")
                time.sleep(0.8)

            with open(json_dir / f"{ref}_analisis_afectaciones.json", 'w', encoding='utf-8') as f:
                json.dump(afectaciones, f, indent=2, ensure_ascii=False)
            
            self.generar_informe_afectaciones(afectaciones, html_dir)
            logger.info("  ✅ Análisis completado")
            return afectaciones
        except Exception as e:
            logger.error(f"  ❌ Error análisis: {e}")
            return None

    def generar_informe_afectaciones(self, afectaciones, html_dir: Path):
        """Genera informe HTML de afectaciones"""
        ref = afectaciones.get('referencia', 'N/A')
        html = f"<html><body><h1>Análisis Afectaciones - {ref}</h1>"
        html += f"<p>Superficie: {afectaciones.get('area_parcela_m2')} m²</p>"
        if afectaciones.get('afectaciones_detectadas'):
            for af in afectaciones['afectaciones_detectadas']:
                html += f"<div><h3>{af['descripcion']}</h3><p>{af['area_afectada_m2']} m² — {af['porcentaje_parcela']}%</p></div>"
        else:
            html += "<p>✅ Sin afectaciones detectadas</p>"
        html += "</body></html>"
        with open(html_dir / f"{ref}_informe_afectaciones.html", 'w', encoding='utf-8') as f:
            f.write(html)

    def descargar_pdf_sigpac(self, referencia: str, output_dir: Path):
        """Descarga PDF SIGPAC y guarda en carpeta pdf"""
        ref = self.limpiar_referencia(referencia)
        pdf_dir = output_dir / "pdf"
        pdf_dir.mkdir(exist_ok=True)
        
        if not GEOPANDAS_AVAILABLE:
            logger.warning("    ⚠️ Requiere GeoPandas")
            return False

        coords = self.obtener_coordenadas(ref)
        if not coords:
            logger.warning("    ⚠️ No se pueden descargar capas sin coordenadas")
            return False

        try:
            from shapely.geometry import Point
            gdf = gpd.GeoDataFrame(geometry=[Point(coords['lon'], coords['lat'])], crs='EPSG:4326')
            gdf_utm = gdf.to_crs('EPSG:25830')
            utm_x, utm_y = int(gdf_utm.geometry.x[0]), int(gdf_utm.geometry.y[0])

            print_url = 'https://sigpac.mapa.gob.es/sigpublico/visor/imprimir'
            spec = {
                'layout': 'A4 horizontal',
                'outputFormat': 'pdf',
                'attributes': {'title': f"SIGPAC - RC: {ref}"},
                'layers': [{
                    'type': 'WMS',
                    'baseURL': 'https://wms.mapa.gob.es/wms-inspire/sigpac',
                    'layers': ['SIGPAC']
                }],
                'center': [utm_x, utm_y],
                'scale': 5000,
                'srs': 'EPSG:25830'
            }

            r = safe_get(print_url, method='post', json_body={'spec': spec}, timeout=90)
            if r.status_code == 200 and r.headers.get('Content-Type', '').lower().startswith('application/pdf'):
                filename = pdf_dir / f"{ref}_informe_sigpac.pdf"
                with open(filename, 'wb') as f:
                    f.write(r.content)
                logger.info("    ✅ PDF SIGPAC guardado")
                return True
            else:
                logger.warning(f"    ⚠️ Error SIGPAC (Status: {r.status_code})")
                return False
        except Exception as e:
            logger.error(f"    ❌ Error SIGPAC: {e}")
            return False

    def descargar_todo_completo(self, referencia: str) -> Tuple[bool, Path]:
        """Descarga todo y organiza por tipo de archivo"""
        logger.info(f"\n{'='*70}\n🚀 Procesando: {referencia}\n{'='*70}")
        ref = self.limpiar_referencia(referencia)
        
        # Crear estructura de carpetas por tipo
        ref_dir = self.output_dir / ref
        ref_dir.mkdir(parents=True, exist_ok=True)
        
        # Carpetas por tipo
        carpetas = {
            'json': ref_dir / "json",
            'html': ref_dir / "html", 
            'gml': ref_dir / "gml",
            'kml': ref_dir / "kml",
            'images': ref_dir / "images",
            'pdf': ref_dir / "pdf"
        }
        
        for carpeta in carpetas.values():
            carpeta.mkdir(exist_ok=True)

        resultados = {}
        
        # 1. Consulta descriptiva
        logger.info("\n📋 CONSULTA DESCRIPTIVA")
        resultados['consulta_descriptiva'] = self.descargar_consulta_descriptiva(ref, ref_dir) is not None
        
        # 2. Parcela GML (CRÍTICO)
        logger.info("\n🗺️ GEOMETRÍA PARCELA")
        archivo_parcela_gml = self.descargar_parcela_gml(ref, ref_dir)
        resultados['parcela_gml'] = archivo_parcela_gml is not None
        
        # 3. Coordenadas
        coords = self.obtener_coordenadas(ref, archivo_parcela_gml)
        if not coords:
            logger.warning("    ⚠️ No se pudieron obtener coordenadas")
            coords = None
        
        # 4. Capas WMS
        if coords:
            logger.info("\n🖼️ CAPAS WMS Y ORTOFOTOS")
            resultados['capas_wms'] = self.descargar_capas_multiples(ref, coords, ref_dir)
        
        # 5. Edificio GML
        logger.info("\n🏢 GEOMETRÍA EDIFICIO")
        resultados['edificio_gml'] = self.descargar_edificio_gml(ref, ref_dir) is not None

        # 6. Ficha catastral
        logger.info("\n📄 FICHA CATASTRAL")
        resultados['ficha_catastral'] = self.descargar_ficha_catastral(ref, ref_dir) is not None

        # 7. Análisis de afectaciones
        if archivo_parcela_gml and GEOPANDAS_AVAILABLE:
            logger.info("\n🔍 ANÁLISIS DE AFECTACIONES")
            resultados['analisis_afectaciones'] = self.analizar_afectaciones(
                ref, archivo_parcela_gml, ref_dir
            ) is not None
        else:
            resultados['analisis_afectaciones'] = False

        # 8. PDF SIGPAC
        if GEOPANDAS_AVAILABLE:
            logger.info("\n📄 PDF SIGPAC")
            resultados['pdf_sigpac'] = self.descargar_pdf_sigpac(ref, ref_dir)
        else:
            resultados['pdf_sigpac'] = False

        # 9. Crear ZIP comprimido
        logger.info("\n📦 CREANDO ZIP COMPRIMIDO")
        zip_path = self.crear_zip_comprimido(ref, ref_dir)
        resultados['zip_creado'] = zip_path is not None
        
        logger.info(f"\n{'='*70}")
        logger.info(f"✅ COMPLETADO: {ref}")
        logger.info(f"{'='*70}")
        logger.info("\n📊 RESUMEN:")
        for k, v in resultados.items():
            emoji = '✅' if v else '❌'
            logger.info(f"  {emoji} {k}: {v}")
        print()
        
        time.sleep(0.5)
        exitosos = sum(1 for v in resultados.values() if v)
        total = len(resultados)
        return exitosos == total, zip_path

    def crear_zip_comprimido(self, referencia: str, ref_dir: Path) -> Optional[Path]:
        """Crea ZIP comprimido con todos los archivos organizados"""
        try:
            zip_path = self.output_dir / f"{referencia}_completo.zip"
            
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # Añadir todos los archivos manteniendo la estructura
                for file_path in ref_dir.rglob('*'):
                    if file_path.is_file():
                        # Ruta relativa desde la carpeta de referencia
                        arcname = file_path.relative_to(ref_dir.parent)
                        zipf.write(file_path, arcname)
            
            logger.info(f"  ✅ ZIP creado: {zip_path}")
            return zip_path
        except Exception as e:
            logger.error(f"  ❌ Error creando ZIP: {e}")
            return None

    def procesar_lote(self, referencias: List[str]) -> Dict[str, Tuple[bool, Path]]:
        """Procesa lote de referencias"""
        resultados = {}
        
        for ref in referencias:
            exito, zip_path = self.descargar_todo_completo(ref)
            resultados[ref] = (exito, zip_path)
            time.sleep(1)  # Pausa entre referencias
        
        return resultados
