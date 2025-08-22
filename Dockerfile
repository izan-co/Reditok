# Usa una imagen oficial de Python 3.11 en su versión 'slim' (más ligera) como base.
FROM python:3.11-slim

# Establece el directorio de trabajo dentro del contenedor.
WORKDIR /app

# Variable de entorno para aceptar los términos de servicio de Coqui TTS automáticamente.
ENV COQUI_TOS_AGREED=1

# --- Instalación de dependencias del sistema operativo ---
# Actualiza la lista de paquetes e instala herramientas esenciales que Python no provee:
# - ffmpeg: Fundamental para cualquier operación de vídeo (usado por moviepy y yt-dlp).
# - imagemagick: Requerido por moviepy para crear clips de texto (TextClip).
# - build-essential, rustc, etc.: Dependencias de compilación para algunas librerías de Python.
# - libsndfile1-dev: Necesaria para el procesamiento de audio.
RUN apt-get update && \
    apt-get install -y ffmpeg imagemagick dos2unix build-essential rustc pkg-config libsndfile1-dev && \
    apt-get clean && rm -rf /var/lib/apt/lists/* && \
    # Desactiva una política de seguridad de ImageMagick que a veces causa problemas en Docker.
    echo "" > /etc/ImageMagick-7/policy.xml

# Copia solo el archivo de requisitos primero. Esto aprovecha el sistema de caché de Docker.
# Si requirements.txt no cambia, Docker no volverá a ejecutar los siguientes pasos de 'pip install'.
COPY requirements.txt .

# Instala PyTorch y Torchaudio primero, especificando una versión para CPU para mantener la imagen ligera.
# El modelo TTS y Whisper pueden funcionar en CPU.
RUN pip install torch==2.3.1 torchaudio==2.3.1 --index-url https://download.pytorch.org/whl/cpu

# Instala todas las dependencias de Python listadas en requirements.txt.
RUN pip install --no-cache-dir -r requirements.txt

# El resto de los archivos del proyecto se copiarán a través del docker-compose.yml
# usando un volumen, lo que permite el desarrollo en vivo sin reconstruir la imagen.