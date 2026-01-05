# Usamos una imagen de Python ligera pero compatible con GIS
FROM python:3.10-slim

# Instalar dependencias del sistema necesarias para GeoPandas y Matplotlib
RUN apt-get update && apt-get install -y  \
    gdal-bin \
        libkml-dev \
    libgdal-dev \
    g++ \
    libproj-dev \
    && rm -rf /var/lib/apt/lists/*

# Configurar variables de entorno para GDAL
ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal

WORKDIR /app

# Copiar requerimientos e instalar
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar todo el proyecto
RUN echo "Build: 2025-01-14-v2" > /tmp/build.txt
# Cache bust: 2025-01-14
COPY . .

# Crear carpetas necesarias y dar permisos
RUN mkdir -p outputs
RUN chmod -R 777 outputs

# NOTA: La carpeta 'capas' se montará como volumen externo en producción

# Exponer el puerto que usa FastAPI
EXPOSE 8080

# Comando para arrancar la app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
