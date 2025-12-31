import os
import json
import geopandas as gpd
import matplotlib.pyplot as plt
from shapely.geometry import shape
import fiona
from pathlib import Path

class VectorAnalyzer:
    def __init__(self, output_dir="outputs", capas_dir="capas"):
        self.output_dir = Path(output_dir)
        self.capas_dir = Path(capas_dir)
        self.config_titulos = self._cargar_config_titulos()

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
        Ejecuta la intersección espacial y genera los mapas JPG.
        """
        results = []
        carpeta_ref = self.output_dir / referencia
        carpeta_ref.mkdir(parents=True, exist_ok=True)

        # 1. Cargar la parcela (KML)
        try:
            parcela_gdf = gpd.read_file(kml_path)
            # Asegurar sistema de coordenadas proyectado (ej: EPSG:25830 para España)
            if parcela_gdf.crs != "EPSG:25830":
                parcela_gdf = parcela_gdf.to_crs("EPSG:25830")
        except Exception as e:
            return {"error": f"Error leyendo KML: {e}"}

        # 2. Analizar cada capa disponible en la carpeta /capas
        for capa_file in os.listdir(self.capas_dir):
            if capa_file.endswith(('.gpkg', '.geojson', '.shp')):
                nombre_capa = Path(capa_file).stem
                ruta_capa = self.capas_dir / capa_file
                
                # Procesar intersección
                info_interseccion = self._analizar_capa_especifica(parcela_gdf, ruta_capa, nombre_capa)
                
                # Generar Mapa (Punto 3 y 4)
                img_path = self._generar_captura_mapa(parcela_gdf, info_interseccion['gdf_capa'], referencia, nombre_capa)
                
                results.append({
                    "capa": nombre_capa,
                    "titulo": self.config_titulos.get(nombre_capa, nombre_capa),
                    "afectado": info_interseccion['afectado'],
                    "area_afectada": info_interseccion['area_m2'],
                    "mapa_url": img_path
                })

        return results

    def _analizar_capa_especifica(self, parcela_gdf, ruta_capa, nombre):
        """Realiza el clipping espacial."""
        capa_gdf = gpd.read_file(ruta_capa)
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