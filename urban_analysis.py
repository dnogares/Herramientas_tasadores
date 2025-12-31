import os
import requests
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Dict, Optional
import logging

# Configuración de logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AnalizadorUrbanistico:
    def __init__(self, output_base_dir: str = "outputs"):
        self.output_base_dir = Path(output_base_dir)
        self.output_base_dir.mkdir(parents=True, exist_ok=True)
        # URL del Servicio WFS de la Sede Electrónica del Catastro (España)
        self.ovc_url = "https://ovc.catastro.meh.es/ovcservweb/OVCSWLocalizacionRC/OVCCallejero.asmx"

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
        # Crear subcarpeta para esta referencia
        carpeta_ref = self.output_base_dir / referencia
        carpeta_ref.mkdir(parents=True, exist_ok=True)

        try:
            # 1. Consulta a OVC para obtener coordenadas/datos básicos
            params = {
                'RefCat': referencia
            }
            # Simulamos la descarga de un GML (en una implementación real usaríamos el WFS del Catastro)
            # Para este ejemplo, generamos el path donde se guardará el KML convertido
            kml_path = carpeta_ref / f"{referencia}.kml"
            
            # 2. Lógica de conversión (Módulo 1: GML a KML)
            self._generar_kml_basico(referencia, kml_path)

            return {
                "referencia": referencia,
                "status": "success",
                "folder": str(carpeta_ref),
                "kml": str(kml_path)
            }
        except Exception as e:
            logger.error(f"Error al obtener datos de {referencia}: {e}")
            return {"referencia": referencia, "status": "error", "message": str(e)}

    def _generar_kml_basico(self, referencia: str, output_path: Path):
        """
        Crea un archivo KML con la estructura necesaria para Leaflet.
        """
        kml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>{referencia}</name>
    <Placemark>
      <name>Parcela {referencia}</name>
      <description>Referencia Catastral: {referencia}</description>
      <Style>
        <LineStyle><color>ff0000ff</color><width>2</width></LineStyle>
        <PolyStyle><fill>0</fill></PolyStyle>
      </Style>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              -3.70379,40.416775 
              -3.70379,40.417775 
              -3.70279,40.417775 
              -3.70279,40.416775 
              -3.70379,40.416775
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
  </Document>
</kml>"""
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(kml_content)

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