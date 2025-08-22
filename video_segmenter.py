"""
Módulo Segmentador y Validador de Vídeo
---------------------------------------
Este módulo es responsable de tomar los vídeos largos y crudos descargados por
`video_downloader` y procesarlos para crear una biblioteca de segmentos de vídeo cortos,
de alta calidad y listos para usar como fondo en los vídeos finales.

Funcionalidades clave:
1. Recorte opcional del inicio y final de los vídeos.
2. División en segmentos de duración fija usando FFmpeg.
3. Validación de calidad de cada segmento (brillo y movimiento) usando OpenCV.
4. Limpieza de los archivos originales para ahorrar espacio.
"""

import subprocess
import re
from pathlib import Path
import logging
import math
from tqdm import tqdm
import shutil
import cv2
import numpy as np
from typing import Tuple

from config import (
    RAW_VIDEOS_FOLDER, SEGMENTS_FOLDER, SEGMENT_DURATION_SECONDS,
    PROCESSED_VIDEOS_LOG, FFMPEG_PATH, ENABLE_QUALITY_VALIDATION,
    VALIDATION_FRAME_SAMPLES, MIN_BRIGHTNESS, MAX_BRIGHTNESS, MIN_MOTION_SCORE,
    ENABLE_VIDEO_TRIMMING, TRIM_START_SECONDS, TRIM_END_SECONDS
)

logger = logging.getLogger(__name__)

def is_segment_high_quality(segment_path: Path) -> Tuple[bool, str]:
    """
    Analiza un segmento de vídeo para determinar si cumple con los estándares de calidad.

    Mide dos métricas clave en una muestra de fotogramas:
    - Brillo: Para descartar escenas demasiado oscuras o sobreexpuestas.
    - Movimiento: Para descartar escenas estáticas o con muy poca acción visual.

    :param segment_path: Ruta al archivo del segmento de vídeo.
    :return: Una tupla (es_valido, razon).
    """
    if not ENABLE_QUALITY_VALIDATION:
        return True, "Validación de calidad deshabilitada"

    try:
        cap = cv2.VideoCapture(str(segment_path))
        if not cap.isOpened():
            return False, "No se pudo abrir el archivo de video"

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames < VALIDATION_FRAME_SAMPLES:
            cap.release()
            return False, "Video demasiado corto para muestrear"

        # Selecciona N fotogramas distribuidos uniformemente a lo largo del clip.
        frame_indices = np.linspace(0, total_frames - 1, VALIDATION_FRAME_SAMPLES, dtype=int)
        
        avg_brightness = []
        motion_scores = []
        prev_frame = None

        for idx in frame_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if not ret:
                continue

            gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            # 1. Cálculo del brillo: media de los valores de píxeles en la imagen en escala de grises.
            avg_brightness.append(gray_frame.mean())

            # 2. Cálculo del movimiento: diferencia absoluta entre el fotograma actual y el anterior.
            if prev_frame is not None:
                diff = cv2.absdiff(prev_frame, gray_frame)
                _, thresholded = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
                motion_percent = (np.count_nonzero(thresholded) * 100) / thresholded.size
                motion_scores.append(motion_percent)
            
            prev_frame = gray_frame
        
        cap.release()

        if not avg_brightness:
            return False, "No se pudieron leer frames del video"

        # Compara las métricas promedio con los umbrales definidos en config.py
        final_brightness = np.mean(avg_brightness)
        if not (MIN_BRIGHTNESS <= final_brightness <= MAX_BRIGHTNESS):
            return False, f"Brillo fuera de rango ({final_brightness:.1f})"

        final_motion = np.mean(motion_scores) if motion_scores else 0
        if final_motion < MIN_MOTION_SCORE:
            return False, f"Movimiento insuficiente ({final_motion:.2f}%)"
            
        return True, "Calidad aceptable"

    except Exception as e:
        if 'cap' in locals() and cap.isOpened():
            cap.release()
        return False, f"Error durante la validación con OpenCV: {e}"

def get_video_duration(video_path: Path) -> float:
    """Obtiene la duración de un vídeo en segundos usando FFmpeg."""
    try:
        # Ejecuta FFmpeg solo para leer la cabecera del archivo, es muy rápido.
        result = subprocess.run([FFMPEG_PATH, '-i', str(video_path)], capture_output=True, text=True, check=False, encoding='utf-8')
        # Busca la línea "Duration:" en la salida de error de FFmpeg.
        if duration_match := re.search(r"Duration: (\d{2}:\d{2}:\d{2}\.\d{2})", result.stderr):
            h, m, s = map(float, duration_match.group(1).split(':'))
            return h * 3600 + m * 60 + s
        raise ValueError("No se pudo parsear la duración desde la salida de FFmpeg")
    except Exception as e:
        logger.error(f"Fallo al obtener la duración de {video_path}: {e}")
        raise

def process_new_videos_into_segments():
    """
    Función principal que orquesta el procesamiento de vídeos crudos en segmentos.
    """
    if not shutil.which(FFMPEG_PATH):
        logger.error(f"FFmpeg no encontrado en '{FFMPEG_PATH}'. Asegúrate de que está instalado y en el PATH.")
        return

    raw_videos_dir = Path(RAW_VIDEOS_FOLDER)
    segments_dir = Path(SEGMENTS_FOLDER)
    raw_videos_dir.mkdir(exist_ok=True)
    segments_dir.mkdir(exist_ok=True)

    processed_log_path = Path(PROCESSED_VIDEOS_LOG)
    processed_log = set(processed_log_path.read_text().splitlines()) if processed_log_path.exists() else set()

    # Encuentra vídeos nuevos que no estén en el log de procesados.
    videos = [f for f in raw_videos_dir.iterdir() if f.suffix.lower() in (".mp4", ".mov", ".mkv") and f.stem not in processed_log]
    if not videos:
        logger.info("No hay vídeos nuevos para procesar.")
        return

    for video_path in videos:
        video_id = video_path.stem
        logger.info(f"Procesando {video_path.name}")
        try:
            original_duration = get_video_duration(video_path)
            input_for_segmentation = video_path
            
            # Fase 1: Recorte (opcional)
            if ENABLE_VIDEO_TRIMMING and original_duration > TRIM_START_SECONDS + TRIM_END_SECONDS:
                logger.info(f"Pre-procesando: Recortando {TRIM_START_SECONDS}s del inicio y {TRIM_END_SECONDS}s del final.")
                trimmed_video_path = raw_videos_dir / f"{video_id}_trimmed.mp4"
                new_duration = original_duration - TRIM_START_SECONDS - TRIM_END_SECONDS
                # Comando FFmpeg para recortar sin re-codificar (muy rápido).
                trim_command = [
                    FFMPEG_PATH, '-ss', str(TRIM_START_SECONDS), '-i', str(video_path),
                    '-t', str(new_duration), '-c', 'copy', '-y', str(trimmed_video_path)
                ]
                result = subprocess.run(trim_command, capture_output=True, text=True, check=False)
                if result.returncode == 0 and trimmed_video_path.exists():
                    input_for_segmentation = trimmed_video_path
                else:
                    logger.error(f"Fallo al recortar {video_path.name}. Se usará el vídeo original. Error: {result.stderr}")
            
            # Fase 2: Segmentación
            duration = get_video_duration(input_for_segmentation)
            num_segments = math.floor(duration / SEGMENT_DURATION_SECONDS)
            if num_segments == 0:
                logger.warning(f"El vídeo {input_for_segmentation.name} es demasiado corto para extraer segmentos completos.")
                continue

            successful_segments = 0
            for i in tqdm(range(num_segments), desc=f"Segmentando {video_id}"):
                segment_path = segments_dir / f"{video_id}_seg{i+1}.mp4"
                if segment_path.exists(): continue
                
                # Comando FFmpeg para extraer un segmento sin re-codificar.
                command = [
                    FFMPEG_PATH, '-ss', str(i * SEGMENT_DURATION_SECONDS), '-i', str(input_for_segmentation),
                    '-t', str(SEGMENT_DURATION_SECONDS), '-c', 'copy', '-movflags', '+faststart', '-y', str(segment_path)
                ]
                subprocess.run(command, capture_output=True, text=True, check=False)
                
                if not segment_path.exists() or segment_path.stat().st_size < 1024:
                    logger.error(f"Fallo al crear el segmento {i+1}")
                    continue
                
                # Fase 3: Validación de Calidad
                is_valid, reason = is_segment_high_quality(segment_path)
                if not is_valid:
                    logger.warning(f"Segmento {i+1} descartado. Razón: {reason}")
                    segment_path.unlink() # Elimina el segmento de baja calidad.
                else:
                    logger.info(f"Segmento {i+1} creado y validado.")
                    successful_segments += 1
            
            logger.info(f"Procesado de {video_path.name} completo. {successful_segments}/{num_segments} segmentos válidos creados.")
            
            # Fase 4: Limpieza
            with open(processed_log_path, "a") as f: f.write(f"{video_id}\n")
            if video_path.exists(): video_path.unlink()
            if input_for_segmentation != video_path and input_for_segmentation.exists(): input_for_segmentation.unlink()
            logger.info(f"Archivos de vídeo crudo para {video_id} procesados y eliminados.")

        except Exception as e:
            logger.error(f"Error crítico procesando {video_path.name}: {e}", exc_info=True)
