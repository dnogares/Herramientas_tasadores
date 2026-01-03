#!/usr/bin/env python3
"""
local_layers_manager.py - Gestor de capas locales para ortofotos
================================================================

Gestiona las capas vectoriales locales en H:\data para generar 
ortofotos personalizadas en lugar de depender de servicios externos.

Autor: Sistema Catastro-tool
Fecha: 2025
"""

import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import logging

# Dependencias geoespaciales
try:
    import geopandas as gpd
    from shapely.geometry import Point, box
    import matplotlib.pyplot as plt
    import matplotlib.patches as patches
    from matplotlib.colors import ListedColormap
    GEOPANDAS_AVAILABLE = True
except ImportError:
    GEOPANDAS_AVAILABLE = False

logger = logging.getLogger(__name__)

class LocalLayersManager:
    """Gestor de capas locales para generación de ortofotos"""
    
    def __init__(self, capas_dir: str = "H:/data"):
        self.capas_dir = Path(capas_dir)
        self.capas_disponibles = self._escanear_capas()
        
    def _escanear_capas(self) -> Dict[str, Dict]:
        """Escanea las carpetas y detecta capas disponibles"""
        capas = {}
        
        # Configuración de capas conocidas
        config_capas = {
            'dph': {
                'nombre': 'Dominio Público Hidráulico',
                'tipo': 'hidráulico',
                'color': '#0066CC',
                'estilo': 'línea',
                'grosor': 2
            },
            'espacios_protegidos': {
                'nombre': 'Espacios Naturales Protegidos',
                'tipo': 'ambiental',
                'color': '#228B22',
                'estilo': 'polígono',
                'transparencia': 0.3
            },
            'zonas_inundables': {
                'nombre': 'Zonas de Riesgo de Inundación',
                'tipo': 'riesgos',
                'color': '#FF6B35',
                'estilo': 'polígono',
                'transparencia': 0.4
            },
            'montes_publicos': {
                'nombre': 'Montes Públicos',
                'tipo': 'forestal',
                'color': '#228B22',
                'estilo': 'polígono',
                'transparencia': 0.2
            },
            'capas_ambientales': {
                'nombre': 'Capas Ambientales',
                'tipo': 'ambiental',
                'color': '#32CD32',
                'estilo': 'polígono',
                'transparencia': 0.25
            }
        }
        
        for carpeta in self.capas_dir.iterdir():
            if carpeta.is_dir() and carpeta.name in config_capas:
                # Buscar archivos shapefile
                shp_files = list(carpeta.glob("*.shp"))
                if shp_files:
                    capas[carpeta.name] = {
                        **config_capas[carpeta.name],
                        'ruta_shp': shp_files[0],
                        'archivos': {
                            'shp': shp_files[0],
                            'dbf': list(carpeta.glob("*.dbf"))[0] if list(carpeta.glob("*.dbf")) else None,
                            'shx': list(carpeta.glob("*.shx"))[0] if list(carpeta.glob("*.shx")) else None,
                            'prj': list(carpeta.glob("*.prj"))[0] if list(carpeta.glob("*.prj")) else None
                        }
                    }
                    logger.info(f"Capa encontrada: {carpeta.name} -> {shp_files[0]}")
        
        return capas
    
    def cargar_capa(self, nombre_capa: str) -> Optional[gpd.GeoDataFrame]:
        """Carga una capa específica como GeoDataFrame"""
        if not GEOPANDAS_AVAILABLE:
            logger.error("GeoPandas no disponible")
            return None
            
        if nombre_capa not in self.capas_disponibles:
            logger.error(f"Capa {nombre_capa} no encontrada")
            return None
        
        try:
            ruta_shp = self.capas_disponibles[nombre_capa]['ruta_shp']
            gdf = gpd.read_file(ruta_shp)
            
            # Asegurar CRS WGS84
            if gdf.crs is None:
                gdf.set_crs('EPSG:4326', inplace=True)
            else:
                gdf = gdf.to_crs('EPSG:4326')
            
            logger.info(f"Capa {nombre_capa} cargada: {len(gdf)} elementos")
            return gdf
            
        except Exception as e:
            logger.error(f"Error cargando capa {nombre_capa}: {e}")
            return None
    
    def intersectar_con_bbox(self, gdf: gpd.GeoDataFrame, bbox: Tuple[float, float, float, float]) -> gpd.GeoDataFrame:
        """Filtra elementos que intersectan con un bbox"""
        if gdf.empty:
            return gdf
            
        # Crear polígono del bbox
        bbox_polygon = box(bbox[0], bbox[1], bbox[2], bbox[3])
        bbox_gdf = gpd.GeoDataFrame([1], geometry=[bbox_polygon], crs='EPSG:4326')
        
        # Intersectar
        resultado = gpd.overlay(gdf, bbox_gdf, how='intersection')
        return resultado
    
    def generar_ortofoto_local(self, referencia: str, coords: Dict, buffer_metros: int = 5000) -> Optional[str]:
        """Genera ortofoto usando capas locales"""
        if not GEOPANDAS_AVAILABLE:
            logger.error("GeoPandas no disponible para ortofoto local")
            return None
        
        try:
            # Calcular bbox con límites de tamaño
            lon, lat = coords['lon'], coords['lat']
            
            # Limitar buffer para evitar imágenes demasiado grandes
            max_buffer = 10000  # Máximo 10km
            if buffer_metros > max_buffer:
                buffer_metros = max_buffer
                logger.warning(f"Buffer reducido a {max_buffer}m para evitar imágenes demasiado grandes")
            
            buffer_lon = buffer_metros / 85000
            buffer_lat = buffer_metros / 111000
            bbox = (lon - buffer_lon, lat - buffer_lat, lon + buffer_lon, lat + buffer_lat)
            
            # Configurar figura con tamaño controlado
            fig, ax = plt.subplots(figsize=(8, 8), dpi=100)  # Tamaño pequeño y controlado
            ax.set_aspect('equal')
            
            # Fondo base
            ax.set_facecolor('#f0f8ff')
            
            # Dibujar capas disponibles
            capas_dibujadas = 0
            for nombre_capa, config in self.capas_disponibles.items():
                gdf = self.cargar_capa(nombre_capa)
                if gdf is not None and not gdf.empty:
                    # Filtrar por bbox
                    gdf_filtrado = self.intersectar_con_bbox(gdf, bbox)
                    
                    if not gdf_filtrado.empty:
                        # Aplicar estilo según configuración
                        if config['estilo'] == 'polígono':
                            alpha = config.get('transparencia', 0.3)
                            gdf_filtrado.plot(ax=ax, color=config['color'], alpha=alpha, edgecolor='black', linewidth=0.5)
                        elif config['estilo'] == 'línea':
                            gdf_filtrado.plot(ax=ax, color=config['color'], linewidth=config.get('grosor', 2))
                        
                        capas_dibujadas += 1
                        logger.info(f"Dibujada capa {nombre_capa}: {len(gdf_filtrado)} elementos")
                    else:
                        logger.info(f"Capa {nombre_capa}: sin elementos en el área")
            
            # Si no hay capas dibujadas, crear una imagen de referencia
            if capas_dibujadas == 0:
                ax.text(0.5, 0.5, f'Área de estudio\nReferencia: {referencia}\nBuffer: {buffer_metros}m\n\n(Sin capas locales en esta zona)', 
                       ha='center', va='center', fontsize=12, color='gray', 
                       bbox=dict(boxstyle="round,pad=0.3", facecolor='white', alpha=0.8))
            
            # Añadir punto de referencia
            ax.plot(lon, lat, 'r*', markersize=20, label=f'Referencia: {referencia}')
            
            # Configurar ejes y límites
            ax.set_xlim(bbox[0], bbox[2])
            ax.set_ylim(bbox[1], bbox[3])
            ax.set_xlabel('Longitud')
            ax.set_ylabel('Latitud')
            ax.set_title(f'Ortofoto Local - {referencia}\nBuffer: {buffer_metros}m')
            ax.legend()
            ax.grid(True, alpha=0.3)
            
            # Guardar imagen con tamaño controlado
            output_dir = Path("outputs") / referencia / "ortophotos"
            output_dir.mkdir(parents=True, exist_ok=True)
            
            filename = output_dir / f"ortofoto_local_{buffer_metros}m.png"
            plt.savefig(filename, dpi=80, bbox_inches='tight', facecolor='white', pad_inches=0.1)
            plt.close()
            
            logger.info(f"Ortofoto local generada: {filename}")
            return str(filename)
            
        except Exception as e:
            logger.error(f"Error generando ortofoto local: {e}")
            return None
    
    def generar_ortofotos_multi_escala(self, referencia: str, coords: Dict) -> List[Dict]:
        """Genera ortofotos a múltiples escalas usando capas locales"""
        escalas = [
            {"title": "Vista Regional", "desc": "Provincia y alrededores", "buffer": 50000},
            {"title": "Vista Local", "desc": "Municipio y zona cercana", "buffer": 5000},
            {"title": "Vista Detallada", "desc": "Parcela y alrededores", "buffer": 1000},
        ]
        
        ortophotos = []
        
        for escala in escalas:
            filename = self.generar_ortofoto_local(referencia, coords, escala['buffer'])
            if filename:
                ortophotos.append({
                    "title": escala["title"],
                    "description": escala["desc"],
                    "url": f"/outputs/{referencia}/ortophotos/{Path(filename).name}",
                    "buffer": escala["buffer"]
                })
        
        return ortophotos
    
    def get_capas_info(self) -> Dict:
        """Retorna información de capas disponibles"""
        return {
            "total_capas": len(self.capas_disponibles),
            "capas": {
                nombre: {
                    "nombre": config["nombre"],
                    "tipo": config["tipo"],
                    "archivos_disponibles": list(config["archivos"].keys())
                }
                for nombre, config in self.capas_disponibles.items()
            }
        }
