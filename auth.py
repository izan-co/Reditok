"""
Script de Autorización para la API de YouTube
---------------------------------------------
Este es un script de ejecución única que guía al usuario a través del flujo de
autorización OAuth 2.0 de Google para permitir que la aplicación suba vídeos
en su nombre.

Funcionamiento:
1. Inicia un servidor web local temporal en el puerto 8080.
2. Abre una URL de autorización de Google en el navegador del usuario.
3. El usuario concede los permisos a la aplicación.
4. Google redirige al usuario de vuelta al servidor local con un código de autorización.
5. El script captura este código y lo intercambia por un token de acceso y un
   token de refresco, que se guardan en `token.json`.

Este script solo necesita ejecutarse una vez, o si el archivo `token.json` se
corrompe o se elimina.
"""
import os
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
import http.server
import socketserver
import urllib.parse as urlparse
import threading
import time

# Permiso solicitado: solo para subir vídeos.
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

# Carga la ruta al archivo de secretos del cliente desde una variable de entorno,
# con un valor por defecto. Este archivo se obtiene de la Google Cloud Console.
CLIENT_SECRETS_FILE = Path(os.getenv("YOUTUBE_SECRETS_FILE", "client_secret.json"))
TOKEN_FILE = Path("token.json")

if not CLIENT_SECRETS_FILE.exists():
    print(f"❌ Archivo de secretos del cliente no encontrado: {CLIENT_SECRETS_FILE}")
    print("   Descárgalo desde tu proyecto en Google Cloud Console y colócalo en la raíz del proyecto.")
    exit(1)

# Variables globales para comunicar el código de autorización entre hilos.
auth_code = None
server_running = True

class AuthHandler(http.server.BaseHTTPRequestHandler):
    """
    Un manejador de peticiones HTTP simple para capturar la redirección de OAuth.
    """
    def do_GET(self):
        global auth_code, server_running
        
        parsed_path = urlparse.urlparse(self.path)
        query_params = urlparse.parse_qs(parsed_path.query)
        
        # Si la URL de redirección contiene el parámetro 'code', lo capturamos.
        if 'code' in query_params:
            auth_code = query_params['code'][0]
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b'<html><body><h1>Autorizacion exitosa!</h1><p>Puedes cerrar esta ventana.</p></body></html>')
            server_running = False # Detiene el servidor una vez que tenemos el código.
        else:
            self.send_response(400)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b'<html><body><h1>Fallo en la autorizacion!</h1></body></html>')
    
    def log_message(self, format, *args):
        # Suprime los logs del servidor para una salida más limpia.
        pass  

def run_auth_server():
    """Inicia el servidor HTTP en un bucle."""
    global server_running
    with socketserver.TCPServer(("0.0.0.0", 8080), AuthHandler) as httpd:
        while server_running:
            httpd.handle_request()

# Configura el flujo de autorización. `redirect_uri` debe coincidir con la configurada en Google Cloud Console.
flow = InstalledAppFlow.from_client_secrets_file(
    str(CLIENT_SECRETS_FILE),
    SCOPES,
    redirect_uri="http://localhost:8080/"
)

# Genera la URL que el usuario debe visitar.
# `access_type='offline'` es crucial para obtener un token de refresco.
auth_url, _ = flow.authorization_url(
    prompt="consent", 
    access_type="offline",
    include_granted_scopes='true'
)

print(f"Por favor, visita esta URL para autorizar la aplicacion: {auth_url}")

# Inicia el servidor web en un hilo separado para no bloquear el script.
server_thread = threading.Thread(target=run_auth_server, daemon=True)
server_thread.start()

print("Esperando la autorizacion...")
# Bucle de espera hasta que el servidor capture el código de autorización.
while auth_code is None and server_running:
    time.sleep(0.1)

if auth_code:
    try:
        # Intercambia el código de autorización por las credenciales (token de acceso y de refresco).
        flow.fetch_token(code=auth_code)
        credentials = flow.credentials
        
        # Guarda las credenciales en el archivo token.json para uso futuro.
        with open(TOKEN_FILE, "w") as token:
            token.write(credentials.to_json())
        
        print(f"✅ Credenciales guardadas con exito en {TOKEN_FILE}")
    except Exception as e:
        print(f"❌ Error al intercambiar el codigo por el token: {e}")
else:
    print("❌ La autorizacion fallo o se agoto el tiempo de espera.")