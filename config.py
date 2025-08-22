# Módulo de Configuración Central
# -------------------------------
# Este archivo actúa como el panel de control de toda la aplicación.
# Contiene todas las variables y parámetros que definen el comportamiento del bot,
# desde la programación de publicaciones hasta los detalles estéticos de los vídeos.
# Modificar valores aquí permite ajustar la estrategia de contenido sin tocar la lógica del código.

import os
from pathlib import Path

# --- 1. Configuración General de Publicación ---
TIMEZONE = "Europe/Madrid"  # Zona horaria para la programación de publicaciones.
PUBLISHING_SCHEDULE = [  # Horas del día (en formato 24h) en las que se intentará publicar un vídeo.
    "08:00",
    "13:00",
    "18:00",
    "20:00",
    "22:00",
]
PUBLISH_TOLERANCE_MINUTES = 30  # Margen de tiempo (en minutos) para decidir si publicar inmediatamente o reprogramar.
YOUTUBE_VIDEO_CATEGORY_ID = "24"  # ID de categoría de YouTube ("Entretenimiento").

# --- 2. Gestión de la Biblioteca de Assets ---
MIN_SEGMENTS_IN_LIBRARY = 10  # Si el número de segmentos de vídeo listos para usar cae por debajo de este umbral, se activa el ciclo de mantenimiento.

# --- 3. Directorios Fundamentales ---
BASE_DIR = Path(__file__).parent.absolute()
ASSETS_FOLDER = BASE_DIR / "assets"
RAW_VIDEOS_FOLDER = ASSETS_FOLDER / "raw_videos"  # Vídeos largos descargados de YouTube.
SEGMENTS_FOLDER = ASSETS_FOLDER / "segments"  # Vídeos cortos, procesados y listos para usar.
SESSIONS_FOLDER = ASSETS_FOLDER / "sessions"  # Carpetas temporales para cada ejecución del proceso de creación.
OUTPUT_FOLDER = BASE_DIR / "ready_to_upload"  # (Opcional) Donde se podrían guardar los vídeos finales.

# --- 4. Archivos de Log y Memoria ---
PROCESSED_POSTS_FILE = BASE_DIR / "processed_posts.txt"  # Guarda los IDs de posts de Reddit ya usados.
PROCESSED_VIDEOS_LOG = BASE_DIR / "processed_raw_videos.txt"  # Guarda los IDs de vídeos de YouTube ya descargados.

# --- 5. Parámetros de la Lógica de Negocio ---
MAX_STORIES_PER_RUN = 1  # Cuántas historias buscar y procesar en cada ciclo de trabajo.
MAX_SCRIPT_WORD_COUNT = 145  # Límite de palabras para el guion generado por la IA (clave para la duración del Short).

# --- 6. Configuración de Voces para Coqui TTS ---
VOICE_SAMPLES_BASE_FOLDER = ASSETS_FOLDER / "voice_samples"
GENDER_VOICE_SAMPLES = {  # Rutas a las carpetas con muestras .wav para la clonación de voz.
    "male": str(VOICE_SAMPLES_BASE_FOLDER / "male"),
    "female": str(VOICE_SAMPLES_BASE_FOLDER / "female"),
}

# --- 7. Parámetros del Cazador de Reddit ---
NUM_HOT_SUBREDDITS_TO_HUNT = 30  # Cuántos de los subreddits más "calientes" (activos) se escanearán.
MIN_POST_TEXT_LENGTH = 80  # Longitud mínima del texto de un post para ser considerado.
MIN_COMMENT_TEXT_LENGTH = 25  # Longitud mínima de un comentario para ser considerado.
POST_SCORE_WEIGHT = 1.0  # Peso de los upvotes del post en la puntuación de relevancia.
COMMENT_SCORE_WEIGHT = 1.0  # Peso del número de comentarios en la puntuación de relevancia.
ALL_SUBREDDITS = [ # Lista de subreddits donde se buscarán historias.
    "AmItheAsshole",
    "AITAH",
    "AmItheButtface",
    "AmITheDevil",
    "AmItheJerk",

    "TrueOffMyChest",
    "offmychest",
    "confession",
    "confessions",
    "Desahogo",
    "self",
    "Vent",
    "venting",
    "rant",
    "cuentaleareddit",
    "stories",
    "CrazyFuckingStories",
    "ThatHappened",

    "relationship_advice",
    "relationships",
    "dating_advice",
    "relaciones",
    "JustNoMIL",
    "JUSTNOFAMILY",
    "weddingdrama",
    "bridezillas",
    "stepparents",
    "raisedbynarcissists",
    "breakups",
    "divorce",
    "datinghell",

    "ProRevenge",
    "MaliciousCompliance",
    "pettyrevenge",
    "NuclearRevenge",

    "talesfromretail",
    "TalesFromYourServer",
    "TalesFromTechSupport",
    "TalesFromTheCustomer",
    "TalesFromTheFrontDesk",
    "TalesFromCallCenters",
    "TalesFromSecurity",
    "talesfromHR",
    "ITdept",
    "IDontWorkHereLady",
    "antiwork",
    "workreform",
    "recruitinghell",

    "tifu",

    "AskReddit",
    "AskRedditespanol",
    "AskMen",
    "AskWomen",
    "TooAfraidToAsk",

    "legaladvice",
    "BestofLegalAdvice",
    "legaladviceofftopic",
    "esLegal",

    "entitledparents",
    "entitledpeople",
    "EntitledKarens",

    "nosleep",
    "LetsNotMeet",
    "creepyencounters",
    "Paranormal",
    "Glitch_in_the_Matrix",
    "ScaryStories",
    "UnresolvedMysteries",

    "unpopularopinion",
    "TrueUnpopularOpinion",
    "The10thDentist",
    "Showerthoughts",

    "TodayILearned",
    "nottheonion",
    "ExplainLikeImFive",
    "AskScience",
    "AskHistorians",

    "espanol",
    "Mexico",
    "es",
    "Colombia",
    "argentina",
    "chile",
    "PERU",

    "BestofRedditorUpdates"
]

# --- 8. Parámetros de Pre-procesamiento y Descarga de Vídeo ---
ENABLE_VIDEO_TRIMMING = True  # Si es True, recorta el inicio y el final de los vídeos descargados.
TRIM_START_SECONDS = 30  # Segundos a recortar del inicio.
TRIM_END_SECONDS = 30  # Segundos a recortar del final.
MAX_RAW_VIDEOS_IN_LIBRARY = 8  # Número de vídeos crudos a mantener en la biblioteca.
CHANNEL_SCAN_LIMIT = 50  # Cuántos de los últimos vídeos de un canal de YouTube se escanearán.
HUNTING_TIERS = [  # Estrategia para buscar vídeos: de más largos a más cortos.
    {"tier_name": "Ideal (Más de 45m)", "min_duration_seconds": 2700},
    {"tier_name": "Aceptable (Más de 20m)", "min_duration_seconds": 1200},
    {"tier_name": "Mínimo (Más de 10m)", "min_duration_seconds": 600},
]
CURATED_CHANNEL_IDS = [ # Canales de YouTube de donde se obtendrá el material de fondo.
    "UC7eAfUjR9gdIjoaoQaS0W-A", "UCMlSf7BCzfdRsIGAIpCnrXA", "UCxFQofXJq9WxWWqlsTiQ-Aw",
    "UCns4T9U8VSIRovKa1a_r7rA", "UCTSg06MQbQ5j3slP4mjzUEg", "UCERExzbCGBxhhWBtFnMLInA",
    "UC4r6nalq_1-9rc80qdVLatQ", "UCB5POybzno8F7lwLEr_C8og", "UCCZIevhN62jJ2gb-u__M95g",
    "UCSNIT8Z40XgB4RKk9Vhf1eA", "UCrI3dm4qgAEV67Jc6797WIA", "UCIGEtjevANE0Nqain3EqNSg",
    "UCTGjE7hWuBRNqU-OnVSzq3Q", "UCEoEkMVF0b_9SUnJaThEYRA", "UChgkHw9M_OUTjYtFqkA1WOQ",
]

# --- 9. Parámetros del Segmentador y Ensamblador de Vídeo ---
SEGMENT_DURATION_SECONDS = 120  # Duración de cada segmento de vídeo extraído.
WHISPER_MODEL = "base"  # Modelo de OpenAI Whisper a utilizar para la transcripción. `base` es un buen equilibrio entre velocidad y precisión.

# --- 10. Herramientas Externas ---
YOUTUBE_COOKIES_FILE = BASE_DIR / "cookies.txt"  # (Opcional) Archivo de cookies para evitar el throttling de YouTube.
FFMPEG_PATH = "ffmpeg"  # Ruta al ejecutable de FFmpeg. 'ffmpeg' asume que está en el PATH del sistema.
IMAGEMAGICK_PATH = "/usr/bin/convert"  # Ruta al ejecutable de ImageMagick, necesario para `moviepy` en Linux.

# --- 11. Parámetros de Renderización de Vídeo y Subtítulos ---
VIDEO_RESOLUTION = (1080, 1920)  # Resolución vertical (formato Short).
VIDEO_FPS = 30
VIDEO_BITRATE = "8000k"
AUDIO_BITRATE = "192k"
VIDEO_PRESET = "superfast"  # Preset de codificación de x264. 'superfast' prioriza velocidad sobre tamaño de archivo.
ASPECT_RATIO = 9 / 16
SUBTITLE_FONT = "/app/assets/fonts/Anton-Regular.ttf"  # Ruta a la fuente dentro del contenedor Docker.
SUBTITLE_FONTSIZE = 138
SUBTITLE_COLOR = "#FFFFFF"
SUBTITLE_STROKE_COLORS = {  # Colores del borde del subtítulo, cambian según el género del narrador.
    "male": "#FF4500",
    "female": "#49B6C2",
    "neutral": "#000000"
}
SUBTITLE_STROKE_WIDTH = 14
SUBTITLE_SHADOW_COLOR = "#000000B3"  # (No usado en la implementación actual, pero disponible para futuros estilos).
SUBTITLE_SHADOW_OFFSET = 6  # (No usado en la implementación actual).

# --- 12. Parámetros de Limpieza y Gestión ---
MAX_SESSIONS_TO_KEEP = 5  # Número de carpetas de sesión antiguas a conservar.
MIN_SEGMENT_SIZE_BYTES = 102400  # 100 KB. Los segmentos más pequeños se consideran corruptos.

# --- 13. Parámetros de Validación de Calidad de Assets ---
ENABLE_QUALITY_VALIDATION = True  # Activa/desactiva el análisis de calidad de los segmentos de vídeo.
VALIDATION_FRAME_SAMPLES = 5  # Número de fotogramas a analizar en cada segmento.
MIN_BRIGHTNESS = 30  # Brillo mínimo aceptable (en una escala de 0 a 255).
MAX_BRIGHTNESS = 220  # Brillo máximo aceptable.
MIN_MOTION_SCORE = 1.0  # Umbral mínimo de "movimiento" (cambio entre fotogramas) para que un clip no sea estático.

# --- 14. Parámetros de Proveedores de IA (LLM) ---
LLM_PROVIDERS = [ # Lista de modelos a usar, en orden de prioridad. Si el primero falla, se intentará con el siguiente.
    {
        "name": "gemini",
        "model": "gemini-2.5-pro", # Modelo principal, más potente.
        "api_key_env": "GOOGLE_API_KEY"
    },
    {
        "name": "gemini",
        "model": "gemini-2.5-flash", # Modelo de fallback, más rápido y económico.
        "api_key_env": "GOOGLE_API_KEY"
    }
]