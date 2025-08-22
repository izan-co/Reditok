"""
Orquestador Principal de la Aplicación
--------------------------------------
Este es el punto de entrada y el cerebro de la aplicación. Contiene el bucle principal
que se ejecuta de forma continua para producir y publicar vídeos de acuerdo con un horario.

Responsabilidades:
1.  Configurar el logging y la estructura de directorios.
2.  Cargar los modelos de IA (TTS y Whisper) en memoria.
3.  Ejecutar un bucle infinito que:
    a. Calcula la próxima ventana de publicación.
    b. Realiza tareas de mantenimiento (abastecimiento de vídeos de fondo).
    c. Orquesta el pipeline completo: buscar historia -> procesar texto ->
       generar audio -> ensamblar vídeo -> subir a YouTube.
    d. Gestiona la lógica de programación de publicaciones.
    e. Controla el tiempo de espera hasta el próximo ciclo de trabajo.
4.  Maneja la limpieza de memoria y sesiones antiguas.
"""

import gc
import torch
import logging
import time
import whisper
from datetime import datetime, timedelta
import pytz
from pathlib import Path
from dotenv import load_dotenv
import shutil
import os
import re

load_dotenv() # Carga las variables de entorno desde el archivo .env

# Importa todos los módulos que componen el pipeline.
from config import *
from reddit_scraper import RedditScraper
from text_processor import TextProcessor
from tts_generator import generate_audio, preload_coqui_models
from video_downloader import download_new_source_videos
from video_segmenter import process_new_videos_into_segments
from video_assembler import assemble_viral_video, get_random_video_segment, segment_manager
from youtube_uploader import upload_to_youtube

def setup_logging(session_path: Path) -> logging.Logger:
    """Configura el sistema de logging para guardar un log por sesión y mostrarlo en consola."""
    log_file = session_path / "session_log.txt"
    logger = logging.getLogger("ReditokApp")
    logger.setLevel(logging.INFO)
    if not logger.handlers: # Evita añadir manejadores duplicados si la función se llama de nuevo.
        # Manejador para guardar el log en un archivo.
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(module)s - %(message)s"))
        # Manejador para mostrar el log en la consola.
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logger.addHandler(file_handler)
        logger.addHandler(stream_handler)
    return logger

def clean_old_sessions():
    """Elimina las carpetas de sesiones más antiguas para evitar que el disco se llene."""
    logger = logging.getLogger("ReditokApp")
    sessions_path = Path(SESSIONS_FOLDER)
    if not sessions_path.exists(): return
    
    # Encuentra todas las carpetas de sesión válidas y las ordena de más nueva a más antigua.
    session_pattern = re.compile(r"^\d{8}_\d{6}$")
    valid_sessions = sorted(
        [d for d in sessions_path.iterdir() if d.is_dir() and session_pattern.match(d.name)],
        reverse=True
    )
    
    # Conserva las N más recientes y elimina el resto.
    to_delete = valid_sessions[MAX_SESSIONS_TO_KEEP:]
    if to_delete:
        logger.info(f"Limpiando {len(to_delete)} sesiones antiguas...")
        for session_dir in to_delete:
            try:
                shutil.rmtree(session_dir)
            except OSError as e:
                logger.error(f"Error al eliminar la sesión antigua {session_dir.name}: {e}")

def ensure_directories():
    """Asegura que todas las carpetas necesarias para la aplicación existan."""
    Path(ASSETS_FOLDER).mkdir(exist_ok=True)
    Path(SESSIONS_FOLDER).mkdir(exist_ok=True)
    Path(RAW_VIDEOS_FOLDER).mkdir(exist_ok=True)
    Path(SEGMENTS_FOLDER).mkdir(exist_ok=True)

def has_video_files(directory: Path, extensions=('.mp4', '.mov', '.mkv')) -> int:
    """Cuenta cuántos archivos de vídeo hay en un directorio."""
    if not directory.is_dir(): return 0
    return len([f for f in directory.iterdir() if f.suffix.lower() in extensions])

def maintenance_and_setup(logger: logging.Logger):
    """
    Ejecuta tareas de mantenimiento para asegurar que haya suficientes assets disponibles.
    Si faltan vídeos crudos, los descarga. Si hay vídeos crudos, los procesa en segmentos.
    """
    logger.info("--- Ciclo de Mantenimiento y Abastecimiento Iniciado ---")
    raw_videos_dir = Path(RAW_VIDEOS_FOLDER)
    
    # 1. Abastecimiento de vídeos crudos.
    videos_to_download = MAX_RAW_VIDEOS_IN_LIBRARY - has_video_files(raw_videos_dir)
    if videos_to_download > 0:
        logger.info(f"El almacén de vídeos crudos necesita {videos_to_download} vídeo(s) nuevo(s). Iniciando descarga...")
        download_new_source_videos(num_to_download=videos_to_download)
    
    # 2. Procesamiento de vídeos crudos a segmentos.
    if has_video_files(raw_videos_dir) > 0:
        logger.info("Procesando vídeos crudos existentes en segmentos...")
        process_new_videos_into_segments()

def get_segment_count() -> int:
    """Cuenta el número de segmentos de vídeo listos para usar."""
    segments_dir = Path(SEGMENTS_FOLDER)
    if not segments_dir.is_dir(): return 0
    return len([f for f in segments_dir.iterdir() if f.is_file() and f.suffix == '.mp4'])

def get_next_publish_time(schedule: list, timezone_str: str) -> datetime:
    """
    Calcula la próxima fecha y hora de publicación basándose en el horario
    y la hora actual en la zona horaria especificada.
    """
    tz = pytz.timezone(timezone_str)
    now_in_tz = datetime.now(tz)
    
    # Comprueba los horarios de hoy que aún no han pasado.
    for time_str in sorted(schedule):
        hour, minute = map(int, time_str.split(':'))
        next_publish_dt = now_in_tz.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if next_publish_dt > now_in_tz:
            return next_publish_dt
            
    # Si todos los horarios de hoy ya han pasado, devuelve el primer horario de mañana.
    tomorrow_in_tz = now_in_tz + timedelta(days=1)
    first_hour, first_minute = map(int, sorted(schedule)[0].split(':'))
    return tomorrow_in_tz.replace(hour=first_hour, minute=first_minute, second=0, microsecond=0)

def main_loop():
    """El bucle principal y orquestador de toda la aplicación."""
    # Crea una carpeta de sesión única para esta ejecución.
    session_folder = Path(SESSIONS_FOLDER) / datetime.now().strftime("%Y%m%d_%H%M%S")
    session_folder.mkdir(parents=True, exist_ok=True)
    logger = setup_logging(session_folder)

    logger.info("=" * 60)
    logger.info("===   SISTEMA DE PUBLICACIÓN AUTÓNOMA DE YOUTUBE INICIADO   ===")
    logger.info(f"===   Horario ({TIMEZONE}): {', '.join(PUBLISHING_SCHEDULE)}   ===")
    logger.info(f"===   Tolerancia de publicación: {PUBLISH_TOLERANCE_MINUTES} minutos   ===")
    logger.info("=" * 60)
    
    # Precarga los modelos de IA para un rendimiento más rápido en el bucle.
    preload_coqui_models()
    text_processor = TextProcessor()
    reddit_scraper = RedditScraper()
    whisper_model = whisper.load_model(WHISPER_MODEL)

    while True:
        try:
            # --- FASE DE PLANIFICACIÓN Y MANTENIMIENTO ---
            target_publish_time = get_next_publish_time(PUBLISHING_SCHEDULE, TIMEZONE)
            logger.info(f"\n--- Próximo objetivo de publicación: {target_publish_time.strftime('%Y-%m-%d %H:%M:%S %Z')} ---")
            
            if get_segment_count() < MIN_SEGMENTS_IN_LIBRARY:
                logger.warning(f"Inventario de segmentos bajo ({get_segment_count()}/{MIN_SEGMENTS_IN_LIBRARY}). Ejecutando mantenimiento...")
                maintenance_and_setup(logger)
            
            # --- FASE DE PRODUCCIÓN DE CONTENIDO ---
            logger.info("-> Buscando la mejor historia disponible...")
            stories = reddit_scraper.get_best_stories(num_stories=1)
            if not stories:
                logger.warning("No se encontraron historias válidas. Reintentando en 15 minutos.")
                time.sleep(900); continue
            
            story = stories[0]
            story_id, story_title = story['id'], story['title']
            story_folder = session_folder / f"story_{story_id}"
            story_folder.mkdir(exist_ok=True)
            
            logger.info(f">>> Produciendo vídeo para la historia: '{story_title[:60]}...'")
            content_pack = text_processor.process_story(story["story_text"])
            if not content_pack or not content_pack.get("descriptions"):
                logger.error(f"Fallo al procesar texto para {story_id}. Buscando nueva historia."); continue

            audio_path = story_folder / "audio.wav"
            if not generate_audio(content_pack["script"], str(audio_path), content_pack["narrator_gender"]):
                 logger.error(f"Fallo al generar audio para {story_id}. Buscando nueva historia."); continue

            background_segment = get_random_video_segment(story_id)
            output_video_path = story_folder / f"{story_id}_final.mp4"

            assemble_viral_video(background_segment, str(audio_path), str(output_video_path), whisper_model, content_pack["narrator_gender"])

            # --- FASE DE PUBLICACIÓN Y LIMPIEZA ---
            if output_video_path.exists() and output_video_path.stat().st_size > 1024:
                
                # Lógica para decidir si publicar ahora o programar.
                publish_time_for_api = target_publish_time
                current_time_in_tz = datetime.now(pytz.timezone(TIMEZONE))
                if current_time_in_tz >= target_publish_time:
                    time_passed = current_time_in_tz - target_publish_time
                    if time_passed.total_seconds() / 60 <= PUBLISH_TOLERANCE_MINUTES:
                        logger.warning("La producción ha tardado, pero está dentro del margen de tolerancia. Publicando ahora.")
                        publish_time_for_api = None # None significa publicar inmediatamente.
                    else:
                        logger.warning(f"La producción ha superado el margen de tolerancia. Se ha perdido el slot de las {target_publish_time.strftime('%H:%M')}.")
                        new_target_time = get_next_publish_time(PUBLISHING_SCHEDULE, TIMEZONE)
                        logger.info(f"Re-programando para el próximo slot: {new_target_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                        publish_time_for_api = new_target_time
                
                # Prepara los metadatos para la subida.
                yt_title = content_pack["descriptions"]["youtube_short_title"]
                yt_desc = content_pack["descriptions"]["youtube_short_desc"]
                yt_tags = ["reddit", "historias", "askreddit", "storytime", story["subreddit"]]
                
                video_id = upload_to_youtube(
                    video_path=output_video_path, title=yt_title, description=yt_desc,
                    tags=yt_tags, publish_at=publish_time_for_api
                )
                
                if video_id:
                    logger.info(f"✅ Vídeo para {story_id} subido a YouTube con éxito.")
                    segment_manager.consume_segment(story_id) # Elimina el segmento usado.
                    shutil.rmtree(story_folder) # Elimina la carpeta temporal de la historia.
                else:
                    logger.critical(f"El vídeo para {story_id} se creó pero falló al subir. Se reintentará en el próximo ciclo.")
            
            # --- FASE DE ESPERA ---
            logger.info("-> Iniciando ciclo de limpieza de memoria post-producción...")
            del story, stories, content_pack, background_segment
            gc.collect() # Fuerza la recolección de basura.

            now_in_tz = datetime.now(pytz.timezone(TIMEZONE))
            next_slot_after_job = get_next_publish_time(PUBLISHING_SCHEDULE, TIMEZONE)
            time_to_next_slot = next_slot_after_job - now_in_tz
            
            # Duerme hasta 1 hora antes del próximo slot de publicación.
            sleep_duration = max(60, time_to_next_slot.total_seconds() - 3600)
            logger.info(f"Producción en pausa. Próximo ciclo de trabajo comenzará en {sleep_duration/3600:.2f} horas.")
            time.sleep(sleep_duration)

        except Exception as e:
            logger.critical(f"Error inesperado en el bucle principal: {e}", exc_info=True)
            logger.info("Esperando 10 minutos antes de reintentar el ciclo...")
            time.sleep(600)

if __name__ == "__main__":
    ensure_directories()
    clean_old_sessions()
    main_loop()