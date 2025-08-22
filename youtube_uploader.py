"""
Módulo de Subida a YouTube
--------------------------
Este módulo se encarga de la comunicación con la API de YouTube v3.
Sus responsabilidades son:
1. Gestionar la autenticación a través de OAuth 2.0, incluyendo la
   actualización de tokens de acceso caducados.
2. Subir el archivo de vídeo final a YouTube, configurando su título,
   descripción, etiquetas, categoría y, opcionalmente, programando su
   publicación para una fecha y hora futuras.
"""
import os
import logging
from pathlib import Path
from typing import Optional
from datetime import datetime
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from config import YOUTUBE_VIDEO_CATEGORY_ID

logger = logging.getLogger("ReditokApp.YouTubeUploader")

# Los 'scopes' definen los permisos que la aplicación solicita al usuario.
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
API_SERVICE_NAME = "youtube"
API_VERSION = "v3"
TOKEN_FILE = Path("token.json")  # Archivo donde se guardan las credenciales de OAuth.

def get_authenticated_service() -> Optional[build]:
    """
    Gestiona la autenticación con la API de Google y devuelve un objeto de servicio
    listo para usar. Maneja la carga, validación y refresco de credenciales.
    
    :return: Un objeto 'build' de la API de Google, o None si la autenticación falla.
    """
    credentials = None
    try:
        # 1. Intenta cargar las credenciales desde el archivo token.json.
        if TOKEN_FILE.exists():
            credentials = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        
        # 2. Si no hay credenciales o no son válidas, intenta refrescarlas.
        if not credentials or not credentials.valid:
            if credentials and credentials.expired and credentials.refresh_token:
                try:
                    logger.info("El token de acceso ha expirado, intentando refrescarlo...")
                    credentials.refresh(Request())
                except Exception as e:
                    logger.error(f"Error al refrescar el token de acceso: {e}", exc_info=True)
                    # Si el refresco falla, el token es inválido. Se elimina para forzar una nueva autenticación.
                    if TOKEN_FILE.exists(): TOKEN_FILE.unlink()
                    logger.critical("No se pudo refrescar el token. Por favor, ejecuta auth.py de nuevo.")
                    return None
                else:
                    # Guarda las credenciales actualizadas con el nuevo token de acceso.
                    with open(TOKEN_FILE, "w") as token:
                        token.write(credentials.to_json())
                    logger.info("Token refrescado y guardado con éxito.")
            else:
                # Si no hay credenciales o no hay token de refresco, el usuario debe autenticarse.
                logger.critical(f"No se encontraron credenciales válidas en {TOKEN_FILE}. Ejecuta auth.py primero.")
                return None
        
        # 3. Construye y devuelve el objeto de servicio de la API.
        return build(API_SERVICE_NAME, API_VERSION, credentials=credentials)
    
    except Exception as e:
        logger.critical(f"Error crítico durante la autenticación de YouTube: {e}", exc_info=True)
        return None

def upload_to_youtube(video_path: Path, title: str, description: str, tags: list[str], publish_at: Optional[datetime]) -> Optional[str]:
    """
    Sube un vídeo a YouTube con los metadatos proporcionados.

    :param video_path: Ruta al archivo de vídeo a subir.
    :param title: Título del vídeo.
    :param description: Descripción del vídeo.
    :param tags: Lista de etiquetas para el vídeo.
    :param publish_at: Objeto datetime para programar la publicación. Si es None, se publica inmediatamente.
    :return: El ID del vídeo de YouTube si la subida es exitosa, de lo contrario None.
    """
    if not video_path.is_file():
        logger.error(f"El archivo de vídeo no existe: {video_path}")
        return None

    youtube = get_authenticated_service()
    if not youtube:
        logger.error("No se pudo autenticar con YouTube. Imposible subir el vídeo.")
        return None

    try:
        # Si 'publish_at' está definido, el vídeo se sube como 'privado' y YouTube lo hará público en la fecha indicada.
        # Si no, se sube como 'público' inmediatamente.
        privacy_status = "private" if publish_at else "public"
        
        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": YOUTUBE_VIDEO_CATEGORY_ID
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": False # Importante para evitar restricciones de la ley COPPA.
            }
        }
        if publish_at:
            # El formato debe ser ISO 8601.
            body["status"]["publishAt"] = publish_at.isoformat()

        # `MediaFileUpload` permite subidas reanudables y en fragmentos (chunks).
        media = MediaFileUpload(str(video_path), chunksize=(1024 * 1024 * 8), resumable=True)
        
        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media
        )
        
        # Bucle para subir el vídeo en fragmentos.
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                logger.info(f"Subido {int(status.progress() * 100)}%")
        
        logger.info(f"✅ Vídeo subido con éxito. ID de YouTube: {response.get('id')}")
        return response.get("id")

    except HttpError as e:
        logger.error(f"Error de la API de Google: {e.resp.status} {e.error_details}")
        return None
    except Exception as e:
        logger.error(f"Error inesperado durante la subida del vídeo: {e}", exc_info=True)
        return None