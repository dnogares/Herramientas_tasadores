# Usamos una imagen de Python ligera pero compatible con GIS
FROM python:3.10-slim

# Instalar dependencias del sistema necesarias para GeoPandas y Matplotlib
RUN apt-get update && apt-get install -y \
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
COPY . .

# Crear carpetas necesarias y dar permisos
RUN mkdir -p outputs capas
RUN chmod -R 777 outputs capas

# Exponer el puerto que usa FastAPI
EXPOSE 8000

# Comando para arrancar la app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]