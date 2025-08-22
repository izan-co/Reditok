"""
Módulo Generador de Audio (Text-to-Speech)
------------------------------------------
Este módulo utiliza el motor Coqui TTS para convertir el guion de texto generado
por el LLM en un archivo de audio (voz en off). Implementa una funcionalidad de
clonación de voz, seleccionando una muestra de audio de referencia basada en el
género del narrador para dar variedad y personalidad a las narraciones.
"""
import torch
import logging
import random
from pathlib import Path

from TTS.api import TTS
from config import GENDER_VOICE_SAMPLES

logger = logging.getLogger(__name__)

# Determina si se usará GPU (cuda) o CPU para la inferencia del modelo TTS.
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
MODEL_NAME = "tts_models/multilingual/multi-dataset/xtts_v2"
TTS_MODEL = None  # El modelo se cargará una sola vez en memoria.

def preload_coqui_models():
    """
    Carga el modelo de Coqui TTS en la memoria al inicio del programa.
    Esto evita tener que cargarlo cada vez que se genera un audio, lo cual es
    un proceso lento.
    """
    global TTS_MODEL
    if not TTS_MODEL:
        try:
            logger.info(f"[TTS] Iniciando carga del modelo Coqui '{MODEL_NAME}' en el dispositivo '{DEVICE}'...")
            TTS_MODEL = TTS(model_name=MODEL_NAME, progress_bar=False).to(DEVICE)
            logger.info("[TTS] Modelo Coqui cargado y listo.")
        except Exception as e:
            logger.critical(f"[TTS] Fallo crítico al cargar el modelo Coqui: {e}", exc_info=True)
            raise

def get_voice_sample_for_gender(gender: str) -> str | None:
    """
    Selecciona aleatoriamente un archivo de muestra de voz (.wav) de la carpeta
    correspondiente al género especificado. Esto permite que cada vídeo tenga
    una voz ligeramente diferente dentro de la misma categoría de género.

    :param gender: 'male', 'female', o 'neutral'.
    :return: La ruta al archivo .wav seleccionado o None si no se encuentra.
    """
    # Si el género es 'neutral', se elige al azar entre 'male' y 'female'.
    target_gender = random.choice(["male", "female"]) if gender == "neutral" else gender
    logger.info(f"Género '{gender}' detectado, se seleccionará voz de tipo: '{target_gender}'")

    sample_folder_path_str = GENDER_VOICE_SAMPLES.get(target_gender)
    if not sample_folder_path_str:
        logger.error(f"[TTS] No se encontró una carpeta de muestras definida para el género: '{target_gender}'")
        return None

    sample_folder_path = Path(sample_folder_path_str)
    if not sample_folder_path.is_dir():
        logger.error(f"[TTS] La carpeta de muestras de voz no existe: {sample_folder_path}")
        return None

    wav_files = list(sample_folder_path.glob("*.wav"))
    if not wav_files:
        logger.error(f"[TTS] ¡CRÍTICO! No se encontró ningún archivo .wav en '{sample_folder_path}' para la clonación de voz.")
        return None
    
    selected_wav = random.choice(wav_files)
    logger.info(f"[TTS] Usando muestra de voz '{selected_wav.name}' para clonación.")
    return str(selected_wav)

def generate_audio(text: str, filename: str, narrator_gender: str) -> str | None:
    """
    Genera un archivo de audio a partir de un texto utilizando el modelo TTS cargado.

    :param text: El guion que se va a convertir en voz.
    :param filename: La ruta donde se guardará el archivo de audio generado.
    :param narrator_gender: El género del narrador para seleccionar la muestra de voz.
    :return: La ruta al archivo de audio si se generó con éxito, o None si falló.
    """
    global TTS_MODEL
    if not TTS_MODEL:
        logger.error("[TTS] El modelo de Coqui no está cargado. Llama a preload_coqui_models() primero.")
        return None

    if not text or not text.strip():
        logger.error("[TTS] Se ha proporcionado un texto vacío para la generación de audio.")
        return None

    speaker_wav_path_str = get_voice_sample_for_gender(narrator_gender)
    if not speaker_wav_path_str:
        logger.error(f"[TTS] No se pudo obtener una muestra de voz para el género '{narrator_gender}'. Abortando.")
        return None
    
    logger.info(f"[TTS] Iniciando síntesis de voz...")

    try:
        output_path = Path(filename)
        # Llama a la función principal de Coqui TTS para generar el audio.
        TTS_MODEL.tts_to_file(
            text=text,
            speaker_wav=speaker_wav_path_str,
            language="es",  # Define el idioma del texto.
            file_path=str(output_path)
        )
        
        # Verifica que el archivo se haya creado y no esté vacío.
        if output_path.exists() and output_path.stat().st_size > 1024:
            logger.info(f"[TTS] Audio sintetizado y guardado con éxito en '{output_path}'")
            return str(output_path)
        else:
            logger.error("[TTS] Coqui TTS produjo un archivo de audio vacío o inválido.")
            return None

    except Exception as e:
        logger.error(f"[TTS] Fallo en la generación de audio con Coqui TTS: {e}", exc_info=True)
        return None