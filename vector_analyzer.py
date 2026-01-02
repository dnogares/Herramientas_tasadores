import os
import json
import logging
import geopandas as gpd
import matplotlib.pyplot as plt
from shapely.geometry import shape
import fiona
from pathlib import Path
import pyproj

# Configurar logging
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

class VectorAnalyzer:
    def __init__(self, output_dir="outputs", capas_dir="capas"):
        self.output_dir = Path(output_dir)
        self.capas_dir = Path(capas_dir)
        self.config_titulos = self._cargar_config_titulos()

    def _iter_capa_files(self):
        if not self.capas_dir.exists():
            return []

        capa_files = []

        # Buscar recursivamente dentro de subcarpetas (H:/data/*)
        for p in self.capas_dir.rglob('*'):
            if not p.is_file():
                continue

            suffix = p.suffix.lower()
            if suffix in {'.gpkg', '.geojson'}:
                capa_files.append(p)
            elif suffix == '.shp':
                # Evitar sidecars (.dbf/.shx/etc.). Solo procesamos el .shp.
                capa_files.append(p)

        return capa_files

    def _cargar_config_titulos(self):
        # Configuración de nombres amigables para el informe
        return {
            "vias_pecuarias": "Vías Pecuarias y Servidumbres",
            "inundabilidad": "Riesgo de Inundación (PRTR)",
            "urbanismo": "Calificación Urbanística Vigente",
            "proteccion_ambiental": "Espacios Naturales Protegidos"
        }

    def ejecutar_analisis_completo(self, referencia, kml_path):
        """
        Ejecuta la intersección espacial y genera los mapas PNG y JSON de afecciones.
        """
        results = []
        carpeta_ref = self.output_dir / referencia
        carpeta_ref.mkdir(parents=True, exist_ok=True)

        # 1. Cargar la parcela (KML o GeoJSON)
        try:
            parcela_gdf = gpd.read_file(kml_path)
            if parcela_gdf.crs is None:
                parcela_gdf = parcela_gdf.set_crs("EPSG:4326")
            # Asegurar sistema de coordenadas proyectado (ej: EPSG:25830 para España)
            if parcela_gdf.crs != "EPSG:25830":
                parcela_gdf = parcela_gdf.to_crs("EPSG:25830")
        except Exception as e:
            return {"error": f"Error leyendo archivo de parcela: {e}"}

        afecciones_info = {"referencia": referencia, "capas": []}

        # 2. Analizar cada capa disponible en la carpeta /capas (recursivo)
        for ruta_capa in self._iter_capa_files():
            nombre_capa = ruta_capa.stem
            
            # Procesar intersección
            info_interseccion = self._analizar_capa_especifica(parcela_gdf, ruta_capa, nombre_capa)
            
            # Generar Mapa (PNG)
            img_path = self._generar_captura_mapa(parcela_gdf, info_interseccion['gdf_capa'], referencia, nombre_capa)
            
            # Preparar info para JSON
            capa_info = {
                "nombre": nombre_capa,
                "titulo": self.config_titulos.get(nombre_capa, nombre_capa),
                "afectado": info_interseccion['afectado'],
                "area_afectada_m2": info_interseccion['area_m2'],
                "mapa_url": img_path,
                "fuente": str(ruta_capa.name)
            }
            afecciones_info["capas"].append(capa_info)
            
            results.append({
                "capa": nombre_capa,
                "titulo": self.config_titulos.get(nombre_capa, nombre_capa),
                "afectado": info_interseccion['afectado'],
                "area_afectada": info_interseccion['area_m2'],
                "mapa_url": img_path
            })

        # Guardar JSON de afecciones
        json_path = carpeta_ref / f"{referencia}_afecciones_info.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(afecciones_info, f, indent=2, ensure_ascii=False)

        return results

    def _analizar_capa_especifica(self, parcela_gdf, ruta_capa, nombre):
        """Realiza el clipping espacial."""
        # Leer por bbox para evitar cargar capas gigantes completas.
        # Importante: bbox debe estar en el CRS de la capa.
        layer_crs = None
        try:
            with fiona.open(ruta_capa) as src:
                layer_crs = src.crs_wkt or src.crs
        except Exception:
            layer_crs = None

        bbox = None
        if layer_crs:
            try:
                transformer = pyproj.Transformer.from_crs(parcela_gdf.crs, layer_crs, always_xy=True)
                minx, miny, maxx, maxy = parcela_gdf.total_bounds
                x1, y1 = transformer.transform(minx, miny)
                x2, y2 = transformer.transform(maxx, maxy)
                bbox = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
            except Exception:
                bbox = None

        try:
            if bbox is not None:
                capa_gdf = gpd.read_file(ruta_capa, bbox=bbox)
            else:
                capa_gdf = gpd.read_file(ruta_capa)
        except TypeError:
            capa_gdf = gpd.read_file(ruta_capa)

        # Ajustar CRS
        if capa_gdf.crs is None:
            # Si no sabemos el CRS de la capa, asumimos el mismo que la parcela
            capa_gdf = capa_gdf.set_crs(parcela_gdf.crs)
        if capa_gdf.crs != parcela_gdf.crs:
            capa_gdf = capa_gdf.to_crs(parcela_gdf.crs)
        
        # Intersección
        interseccion = gpd.overlay(parcela_gdf, capa_gdf, how='intersection')
        
        area_afectada = 0
        if not interseccion.empty:
            area_afectada = interseccion.area.sum()

        return {
            "gdf_capa": capa_gdf,
            "afectado": not interseccion.empty,
            "area_m2": round(area_afectada, 2)
        }

    def _generar_captura_mapa(self, parcela_gdf, capa_gdf, referencia, nombre_capa):
        """
        Crea un archivo PNG/JPG con el diseño del mapa para el informe.
        """
        fig, ax = plt.subplots(figsize=(10, 8))
        
        # 1. Dibujar la capa de fondo (ej: inundabilidad) en color suave
        capa_gdf.plot(ax=ax, color='blue', alpha=0.3, edgecolor='blue', linewidth=0.5)
        
        # 2. Dibujar la parcela con un borde rojo grueso
        parcela_gdf.plot(ax=ax, facecolor="none", edgecolor="red", linewidth=2.5, label="Parcela Analizada")
        
        # 3. Zoom a la parcela con un margen (buffer)
        bounds = parcela_gdf.total_bounds
        margin = 200 # metros
        ax.set_xlim([bounds[0] - margin, bounds[2] + margin])
        ax.set_ylim([bounds[1] - margin, bounds[3] + margin])

        # Estética
        titulo = self.config_titulos.get(nombre_capa, nombre_capa).upper()
        plt.title(f"{titulo}\nRef: {referencia}", fontsize=14, fontweight='bold')
        ax.set_axis_off()
        
        # Guardar imagen
        output_name = f"{referencia}_{nombre_capa}.png"
        save_path = self.output_dir / referencia / output_name
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        plt.close()
        
        # Retornar ruta relativa para el frontend
        return f"/outputs/{referencia}/{output_name}"

# Función de compatibilidad para main.py
def procesar_parcelas(referencia, kml_path):
    analyzer = VectorAnalyzer()
    return analyzer.ejecutar_analisis_completo(referencia, kml_path)