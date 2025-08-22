"""
Módulo Descargador de Vídeos (YouTube)
--------------------------------------
Este módulo se encarga de abastecer la biblioteca de vídeos de fondo.
Descarga vídeos largos de una lista curada de canales de YouTube, que luego
serán procesados por el segmentador. Implementa una estrategia de "caza por niveles"
para priorizar vídeos más largos y maneja errores comunes de descarga.
"""

import random
import time
import yt_dlp
from pathlib import Path
import logging
from dotenv import load_dotenv
from config import (
    RAW_VIDEOS_FOLDER, PROCESSED_VIDEOS_LOG, CURATED_CHANNEL_IDS, HUNTING_TIERS,
    ENABLE_VIDEO_TRIMMING, TRIM_START_SECONDS, TRIM_END_SECONDS, YOUTUBE_COOKIES_FILE,
    CHANNEL_SCAN_LIMIT
)

logger = logging.getLogger(__name__)

def _load_processed_videos() -> set:
    """Carga los IDs de los vídeos de YouTube que ya han sido descargados y procesados."""
    log_path = Path(PROCESSED_VIDEOS_LOG)
    return set(log_path.read_text().splitlines()) if log_path.exists() else set()


def download_new_source_videos(num_to_download: int) -> list[str]:
    """
    Descarga una cantidad específica de nuevos vídeos de YouTube.

    Utiliza una estrategia de "caza por niveles": primero busca vídeos muy largos,
    y si no cumple el objetivo, relaja los requisitos de duración y vuelve a buscar.

    :param num_to_download: El número de vídeos que se intentará descargar.
    :return: Una lista con las rutas de los vídeos descargados con éxito.
    """
    load_dotenv(Path(__file__).parent / '.env')
    raw_videos_path = Path(RAW_VIDEOS_FOLDER)
    raw_videos_path.mkdir(exist_ok=True)
    processed_ids = _load_processed_videos()
    
    downloaded_paths = []
    # Mezcla los canales para variar el origen de los vídeos en cada ejecución.
    shuffled_channels = random.sample(CURATED_CHANNEL_IDS, len(CURATED_CHANNEL_IDS))

    # Itera a través de los niveles de caza definidos en config.py
    for tier in HUNTING_TIERS:
        tier_name = tier["tier_name"]
        min_download_duration = tier["min_duration_seconds"]
        
        # Si el recorte está activado, la duración mínima debe ser mayor para asegurar que quede material útil.
        if ENABLE_VIDEO_TRIMMING:
            min_download_duration += (TRIM_START_SECONDS + TRIM_END_SECONDS)

        if len(downloaded_paths) >= num_to_download:
            break

        logger.info(f"--- Iniciando caza - Nivel: '{tier_name}' (Duración mínima descarga: {min_download_duration / 60:.1f} min) ---")

        tier_candidates = []
        for channel_id in shuffled_channels:
            channel_url = f"https://www.youtube.com/channel/{channel_id}/videos"
            logger.info(f"  > Escaneando canal: '{channel_url}'")
            
            try:
                # Usa 'extract_flat' para obtener la lista de vídeos de un canal muy rápidamente sin descargar nada.
                with yt_dlp.YoutubeDL({'extract_flat': True, 'quiet': True, 'ignoreerrors': True, 'playlistend': CHANNEL_SCAN_LIMIT}) as ydl:
                    channel_info = ydl.extract_info(channel_url, download=False)
                
                if not channel_info or not channel_info.get('entries'):
                    logger.warning(f"  < No se encontró información o vídeos para el canal '{channel_id}'.")
                    continue
                
                videos = channel_info['entries']

                # Filtra los vídeos para encontrar candidatos válidos para este nivel.
                valid_videos = [
                    v for v in videos if v and
                    v.get('duration', 0) > min_download_duration and
                    v.get('id') not in processed_ids
                ]
                
                if valid_videos:
                    logger.info(f"  > Canal '{channel_id}' aporta {len(valid_videos)} candidato(s) a la reserva del nivel.")
                    tier_candidates.extend(valid_videos)

            except Exception as e:
                logger.error(f"  < Error inesperado procesando el canal '{channel_id}': {e}")
                continue

        if not tier_candidates:
            logger.warning(f"--- No se encontraron candidatos en ningún canal para el nivel '{tier_name}'. Pasando al siguiente. ---")
            continue

        logger.info(f"--- Búsqueda en nivel '{tier_name}' finalizada. {len(tier_candidates)} candidatos totales encontrados. ---")
        random.shuffle(tier_candidates) # Mezcla todos los candidatos para maximizar la variedad.

        # Intenta descargar los candidatos uno por uno hasta alcanzar el objetivo.
        for video_to_try in tier_candidates:
            if len(downloaded_paths) >= num_to_download:
                break

            video_id = video_to_try['id']
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            local_video_path = raw_videos_path / f"{video_id}.mp4"

            logger.info(f"    -> Intentando con: '{video_to_try.get('title', video_id)}' ({video_to_try.get('duration', 0)/60:.1f} min)")
            
            ydl_opts = {
                # Pide el mejor formato de vídeo con codec AVC (h264) que es muy compatible.
                'format': 'bestvideo[vcodec^=avc][ext=mp4]/bestvideo[vcodec^=avc]/bestvideo[acodec=none]',
                'outtmpl': str(local_video_path),
                'quiet': True,
                'merge_output_format': 'mp4',
                'retries': 30, # Aumenta los reintentos para redes inestables.
                'fragment_retries': 30,
                'socket_timeout': 120,
                'ignoreerrors': True,
            }
            
            # Si existe un archivo de cookies, lo usa para autenticarse y evitar throttling (errores 429).
            cookies_path = Path(YOUTUBE_COOKIES_FILE)
            if cookies_path.exists():
                ydl_opts['cookiefile'] = str(cookies_path)

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([video_url])

                # Verifica que el archivo se haya descargado correctamente y no esté vacío.
                if local_video_path.exists() and local_video_path.stat().st_size > 1024:
                    logger.info(f"    -> ✅ Descarga exitosa: '{local_video_path}'")
                    downloaded_paths.append(str(local_video_path))
                    processed_ids.add(video_id) 
                else:
                    logger.warning(f"    -> ❌ Fallo la descarga de '{video_id}'.")
                    if local_video_path.exists(): local_video_path.unlink()

            except Exception as e:
                # Manejo específico para el error de "rate limiting".
                if "rate-limited" in str(e).lower() or "too many requests" in str(e).lower():
                    logger.warning(f"    -> ❌ Rate limiting detectado. Pausando 15 minutos...")
                    time.sleep(900)
                else:
                    logger.warning(f"    -> ❌ Error inesperado al descargar '{video_id}': {e}.")
            
            # Pausa aleatoria entre descargas para simular un comportamiento más humano.
            time.sleep(random.uniform(60, 120))
    
    logger.info(f"Caza finalizada. Se descargaron {len(downloaded_paths)}/{num_to_download} vídeos solicitados.")
    return downloaded_paths