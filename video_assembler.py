"""
Módulo Ensamblador de Vídeo
---------------------------
Este es el corazón creativo del proyecto. Se encarga de tomar todos los assets
preparados (segmento de vídeo, audio, guion) y combinarlos en un único vídeo
final de formato vertical (Short).

Funcionalidades principales:
1. Gestión de segmentos de vídeo para evitar su reutilización.
2. Transcripción del audio palabra por palabra con Whisper para obtener timestamps.
3. Creación de subtítulos dinámicos con efecto "karaoke".
4. Aplicación de un efecto de borde de color a los subtítulos.
5. Creación y superposición de una barra de progreso.
6. Ensamblaje y renderización del vídeo final con `moviepy`.
"""

import random
import logging
import shutil
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from functools import lru_cache

import whisper
import numpy as np
from scipy.special import expit
from moviepy.editor import (
    VideoFileClip, AudioFileClip, TextClip, CompositeVideoClip
)
from moviepy.video.VideoClip import VideoClip
from moviepy.config import change_settings
from moviepy.video.fx.all import crop, resize
from tqdm import tqdm

from config import (
    SEGMENTS_FOLDER, WHISPER_MODEL, IMAGEMAGICK_PATH,
    VIDEO_RESOLUTION, VIDEO_FPS, VIDEO_BITRATE, AUDIO_BITRATE, VIDEO_PRESET, ASPECT_RATIO,
    SUBTITLE_FONT, SUBTITLE_FONTSIZE, SUBTITLE_COLOR, SUBTITLE_STROKE_COLORS, SUBTITLE_STROKE_WIDTH,
    MIN_SEGMENT_SIZE_BYTES
)

logger = logging.getLogger(__name__)

@lru_cache(maxsize=1)
def setup_imagemagick():
    """Verifica la existencia de ImageMagick y configura moviepy para usarlo."""
    if not shutil.which(IMAGEMAGICK_PATH):
        logger.error(f"ImageMagick no encontrado en: '{IMAGEMAGICK_PATH}'. Es necesario para crear TextClips.")
        raise FileNotFoundError("ImageMagick es un requisito.")
    change_settings({"IMAGEMAGICK_BINARY": IMAGEMAGICK_PATH})
    logger.info(f"ImageMagick configurado para ser usado por moviepy.")

# Se ejecuta al importar el módulo para asegurar que ImageMagick esté listo.
setup_imagemagick()

class SegmentManager:
    """
    Gestiona la asignación y consumo de segmentos de vídeo de fondo.
    Asegura que un segmento se asigne a una única historia y se elimine después
    de ser usado, garantizando que el contenido sea siempre fresco. Es thread-safe.
    """
    def __init__(self):
        self._assigned = {}  # Diccionario para rastrear qué segmento se asignó a qué historia.
        self._lock = threading.Lock() # Para evitar race conditions si se usara en múltiples hilos.

    def get_segment(self, story_id: str) -> str:
        """Asigna un segmento de vídeo aleatorio y válido a un ID de historia."""
        with self._lock:
            # Si ya se asignó un segmento a esta historia, devuelve el mismo.
            if story_id in self._assigned: return self._assigned[story_id]
            segment = self._select_valid_segment()
            self._assigned[story_id] = segment
            logger.info(f"Segmento '{Path(segment).name}' asignado a historia '{story_id}'.")
            return segment

    def _select_valid_segment(self) -> str:
        """Selecciona un segmento de vídeo aleatorio de la carpeta de segmentos."""
        segments_path = Path(SEGMENTS_FOLDER)
        if not segments_path.exists(): raise FileNotFoundError(f"Carpeta de segmentos no existe: '{SEGMENTS_FOLDER}'")
        
        available_segments = [p for p in segments_path.glob("*.mp4") if p.stat().st_size >= MIN_SEGMENT_SIZE_BYTES]
        if not available_segments:
            raise ValueError("No hay segmentos de vídeo válidos disponibles en la biblioteca.")
        
        return str(random.choice(available_segments))

    def consume_segment(self, story_id: str):
        """Elimina el segmento de vídeo asociado a una historia una vez que el vídeo final se ha subido."""
        with self._lock:
            if story_id not in self._assigned: return
            segment_path_str = self._assigned.pop(story_id)
            segment_path = Path(segment_path_str)
            if segment_path.exists():
                logger.info(f"Consumiendo (eliminando) segmento: {segment_path.name}")
                try:
                    segment_path.unlink()
                except OSError as e:
                    logger.error(f"Error al eliminar segmento: {e}")

# Instancia global del gestor de segmentos.
segment_manager = SegmentManager()

def sigmoid_ease(t: float, duration: float, steepness: int = 10) -> float:
    """Función de suavizado sigmoide para una animación de progreso más natural."""
    x = steepness * (t / duration - 0.5)
    return expit(x)

def create_neon_progress_bar(duration: float, size: tuple) -> VideoClip:
    """Crea una barra de progreso animada con un degradado de color y animación suavizada."""
    width, height = size
    bar_height = max(10, int(height / 100)) # 1% de la altura del vídeo, mínimo 10px.
    
    color_start = np.array([255, 69, 0], dtype=np.uint8)  # Naranja
    color_end = np.array([73, 182, 194], dtype=np.uint8) # Cian

    # Pre-calcula el degradado de color para toda la barra.
    colors = np.array([np.linspace(start, end, width) for start, end in zip(color_start, color_end)]).T.astype(np.uint8)

    def make_frame_rgb(t):
        progress = sigmoid_ease(t, duration)
        current_length = int(progress * width)
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        bar_start_y = height - bar_height
        if current_length > 0:
            frame[bar_start_y:height, :current_length] = colors[:current_length][np.newaxis, :, :]
        return frame

    # La máscara define la transparencia, haciendo que solo la barra sea visible.
    def make_frame_mask(t):
        progress = sigmoid_ease(t, duration)
        mask = np.zeros((height, width), dtype=np.float32)
        bar_start_y = height - bar_height
        if int(progress * width) > 0:
            mask[bar_start_y:height, :int(progress * width)] = 1.0
        return mask

    bar_clip = VideoClip(make_frame_rgb, duration=duration)
    mask_clip = VideoClip(make_frame_mask, duration=duration, ismask=True)
    return bar_clip.set_mask(mask_clip)

@contextmanager
def managed_clip(clip_path: str, clip_type: str = 'video'):
    """Gestor de contexto para abrir y cerrar clips de moviepy, evitando fugas de memoria."""
    clip = None
    try:
        clip = VideoFileClip(clip_path) if clip_type == 'video' else AudioFileClip(clip_path)
        yield clip
    finally:
        if clip: clip.close()

def transcribe_audio(audio_path: str, whisper_model) -> list:
    """Transcribe un archivo de audio para obtener timestamps de cada palabra."""
    try:
        # `word_timestamps=True` es la clave para el efecto karaoke.
        result = whisper_model.transcribe(audio_path, word_timestamps=True, fp16=False)
        return [word for segment in result.get('segments', []) for word in segment.get('words', [])]
    except Exception as e:
        logger.error(f"Error transcribiendo {audio_path}: {e}")
        return []

def create_subtitle_clip(text: str, video_size: tuple, y_pos: int, border_color: str) -> CompositeVideoClip:
    """Crea un clip de subtítulo con un borde de color sólido y alto contraste."""
    text_width = int(video_size[0] * 0.9) # 90% del ancho del vídeo.
    
    # Clip de fondo (el borde). Es un texto más grueso del color del borde.
    border_clip = TextClip(
        txt=text, fontsize=SUBTITLE_FONTSIZE, font=SUBTITLE_FONT, color=border_color,
        stroke_color=border_color, stroke_width=SUBTITLE_STROKE_WIDTH,
        method='caption', align='center', size=(text_width, None)
    )
    # Clip de texto principal, que se superpone al borde.
    text_clip = TextClip(
        txt=text, fontsize=SUBTITLE_FONTSIZE, font=SUBTITLE_FONT, color=SUBTITLE_COLOR,
        method='caption', align='center', size=(text_width, None)
    )
    # Combina ambos clips y los posiciona en el vídeo.
    return CompositeVideoClip([border_clip, text_clip.set_position("center")]).set_position(('center', y_pos))

def generate_subtitles(audio_path: str, video_size: tuple, whisper_model, narrator_gender: str) -> list:
    """
    Genera una lista de clips de subtítulos (TextClip de moviepy), uno por cada palabra,
    con su tiempo de inicio y duración correctos.
    """
    y_pos = int(video_size[1] * 0.4) # Posición vertical de los subtítulos.
    border_color = SUBTITLE_STROKE_COLORS.get(narrator_gender, SUBTITLE_STROKE_COLORS["neutral"])
    
    # Ejecuta la transcripción en un hilo separado para no bloquear.
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(transcribe_audio, audio_path, whisper_model)
        words = future.result()

    if not words: return []
    logger.info(f"Procesando {len(words)} palabras para efecto karaoke...")
    subtitle_clips = []
    for word_data in tqdm(words, desc="Creando subtítulos palabra por palabra"):
        start, end, text = word_data.get('start'), word_data.get('end'), word_data.get('word', '').strip().upper()
        if not text: continue
        
        duration = max(end - start, 0.1) # Duración mínima para evitar clips invisibles.
        try:
            subtitle_clip = create_subtitle_clip(text, video_size, y_pos, border_color).set_start(start).set_duration(duration)
            subtitle_clips.append(subtitle_clip)
        except Exception as e:
            logger.error(f"Error al crear el subtítulo para la palabra '{text}': {e}")

    logger.info(f"Generados {len(subtitle_clips)} subtítulos con borde de color '{border_color}'.")
    return subtitle_clips

def crop_to_aspect_ratio(video_clip, target_ratio: float) -> VideoFileClip:
    """Recorta el vídeo para que se ajuste al aspect ratio deseado (9:16)."""
    w, h = video_clip.size
    current_ratio = w / h
    if abs(current_ratio - target_ratio) < 0.01: return video_clip # Ya tiene el ratio correcto.
    
    if current_ratio > target_ratio: # El vídeo es más ancho (ej. 16:9).
        new_width = round(h * target_ratio)
        return crop(video_clip, x_center=w/2, width=new_width) # Recorta los lados.
    else: # El vídeo es más alto.
        new_height = round(w / target_ratio)
        return crop(video_clip, y_center=h/2, height=new_height) # Recorta arriba y abajo.

def assemble_viral_video(background_video_path: str, audio_path: str, output_filename: str, 
                        whisper_model, narrator_gender: str):
    """
    Función principal que orquesta el ensamblaje completo del vídeo.
    """
    logger.info(f"Ensamblando vídeo final: {Path(output_filename).name}")
    final_video = None
    try:
        with managed_clip(audio_path, 'audio') as audio_clip, \
             managed_clip(background_video_path, 'video') as video_file:
            
            audio_duration = audio_clip.duration
            # Si el vídeo de fondo es más largo que el audio, se selecciona un fragmento aleatorio.
            if video_file.duration > audio_duration:
                start_time = random.uniform(0, video_file.duration - audio_duration)
                video_clip = video_file.subclip(start_time, start_time + audio_duration)
            else:
                # Si es más corto, se ajusta su duración (ralentizándolo o acelerándolo ligeramente).
                video_clip = video_file.set_duration(audio_duration)

            # Aplica el recorte y redimensionado al formato de Short.
            video_clip = crop_to_aspect_ratio(video_clip, ASPECT_RATIO)
            video_clip = resize(video_clip, height=VIDEO_RESOLUTION[1], width=VIDEO_RESOLUTION[0])
            
            # Genera los subtítulos y la barra de progreso.
            subtitles = generate_subtitles(audio_path, video_clip.size, whisper_model, narrator_gender)
            progress_bar = create_neon_progress_bar(audio_duration, video_clip.size)

            # Compone el vídeo final superponiendo todos los elementos.
            final_video = CompositeVideoClip([video_clip] + subtitles + [progress_bar])
            final_video = final_video.set_audio(audio_clip).set_duration(audio_duration)

            logger.info("Exportando vídeo final...")
            # Renderiza el archivo de vídeo con los parámetros de configuración.
            final_video.write_videofile(
                output_filename, codec="libx264", audio_codec="aac",
                fps=VIDEO_FPS, preset=VIDEO_PRESET, threads=8, 
                logger='bar', bitrate=VIDEO_BITRATE, audio_bitrate=AUDIO_BITRATE
            )
    except Exception as e:
        logger.error(f"Error crítico ensamblando el vídeo: {e}", exc_info=True)
        raise
    finally:
        # Libera la memoria de moviepy.
        if final_video: final_video.close()

def get_random_video_segment(story_id: str) -> str:
    """Función de conveniencia para obtener un segmento desde el gestor."""
    return segment_manager.get_segment(story_id)
