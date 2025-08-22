"""
Módulo Procesador de Texto con IA (LLM)
---------------------------------------
Este módulo actúa como una interfaz con los Modelos de Lenguaje Grandes (LLM) como Gemini.
Su responsabilidad es tomar el texto crudo de una historia de Reddit y transformarlo en:
1. Un guion de vídeo optimizado para la viralidad.
2. Metadatos útiles como el género del narrador.
3. Títulos y descripciones atractivos para YouTube.

Utiliza Pydantic para validar rigurosamente las respuestas JSON de la IA y tiene un
sistema de fallback para intentar con un modelo secundario si el principal falla.
"""

import os
import re
import json
import logging
from typing import Optional, Any, Type, Literal, List
from pathlib import Path
import google.generativeai as genai
from pydantic import BaseModel, Field, ValidationError
from config import LLM_PROVIDERS

logger = logging.getLogger(__name__)

# --- Modelos de Validación de Datos con Pydantic ---
# Estos modelos definen la estructura JSON esperada de la respuesta de la IA.
# Si la IA devuelve un JSON con un formato diferente, Pydantic lanzará un error.

class ScriptResponse(BaseModel):
    """Define la estructura para la respuesta del guion."""
    word_count: int = Field(..., description="El número exacto de palabras del script.")
    narrator_gender: Literal["male", "female", "neutral"] = Field(..., description="Género detectado del narrador.")
    script: str = Field(..., min_length=1, description="El guion completo en español.")

class DescriptionsResponse(BaseModel):
    """Define la estructura para la respuesta de las descripciones."""
    youtube_short_title: str = Field(..., min_length=1, max_length=70)
    youtube_short_desc: str = Field(..., min_length=1, max_length=200)

# --- Clases de Proveedor de IA ---
# Esta arquitectura permite cambiar o añadir fácilmente nuevos proveedores de LLM (ej. OpenAI).

class LLMProvider:
    """Clase base abstracta para un proveedor de LLM."""
    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise ValueError(f"Se requiere una API key para {self.__class__.__name__}")
        self.api_key = api_key
        self.model = model
    def generate_content(self, prompt: str) -> Optional[str]:
        raise NotImplementedError("Este método debe ser implementado por una clase hija.")

class GeminiProvider(LLMProvider):
    """Implementación específica para la API de Google Gemini."""
    def __init__(self, api_key: str, model: str):
        super().__init__(api_key, model)
        # Configuración para forzar la salida en JSON y ajustar la creatividad.
        self.generation_config = genai.types.GenerationConfig(
            temperature=0.7, response_mime_type="application/json"
        )
        # Desactiva los filtros de seguridad para evitar bloqueos por contenido sensible de las historias.
        self.safety_settings = [
            {"category": c, "threshold": "BLOCK_NONE"} for c in [
                "HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH", 
                "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT"
            ]
        ]
        self.client = genai.GenerativeModel(self.model, safety_settings=self.safety_settings)

    def generate_content(self, prompt: str) -> Optional[str]:
        try:
            response = self.client.generate_content(prompt, generation_config=self.generation_config)
            # Maneja el caso en que la respuesta es bloqueada a pesar de los settings.
            if not response.parts:
                if response.prompt_feedback.block_reason:
                    logger.warning(f"Respuesta de Gemini ({self.model}) bloqueada. Razón: {response.prompt_feedback.block_reason.name}")
                return None
            return response.text.strip()
        except Exception as e:
            logger.error(f"Error en GeminiProvider ({self.model}): {e}")
            return None

# Mapea los nombres de proveedores de la configuración a sus clases correspondientes.
PROVIDER_MAP = {"gemini": GeminiProvider}

class TextProcessor:
    """Orquesta la interacción con los LLMs para procesar una historia."""
    def __init__(self):
        """Inicializa los proveedores de IA y carga los prompts desde archivos."""
        self.providers = self._initialize_providers()
        if not self.providers:
            raise RuntimeError("No se pudo inicializar ningún proveedor de IA. Verifique config.py y .env.")
        self.prompts = self._load_prompts()

    def _initialize_providers(self) -> List[LLMProvider]:
        """Crea instancias de los proveedores de LLM definidos en config.py."""
        initialized_providers = []
        api_key_gemini = os.getenv("GOOGLE_API_KEY")
        if api_key_gemini: genai.configure(api_key=api_key_gemini)
        
        for provider_config in LLM_PROVIDERS:
            name, api_key_env, model = provider_config["name"], provider_config["api_key_env"], provider_config["model"]
            api_key = os.getenv(api_key_env)
            if name in PROVIDER_MAP and api_key:
                try:
                    provider_class = PROVIDER_MAP[name]
                    initialized_providers.append(provider_class(api_key=api_key, model=model))
                    logger.info(f"Proveedor de IA '{name}' con modelo '{model}' inicializado con éxito.")
                except Exception as e:
                    logger.error(f"Fallo al inicializar '{name}' con modelo '{model}': {e}")
        return initialized_providers

    def _call_llm_with_fallback(self, prompt: str) -> Optional[str]:
        """
        Llama a los proveedores de LLM en orden. Si el primero falla, intenta con el siguiente.
        Esto proporciona resiliencia si un modelo está caído o falla.
        """
        for provider in self.providers:
            response_text = provider.generate_content(prompt)
            if response_text:
                return response_text
            logger.warning(f"Fallo con {provider.model}. Intentando con el siguiente proveedor...")
        logger.error("Fallo definitivo al llamar a todos los proveedores de IA.")
        return None

    def _load_prompts(self) -> dict[str, str]:
        """Carga el contenido de los archivos de prompt en un diccionario."""
        prompt_dir = Path(__file__).resolve().parent / "prompts"
        prompts = {}
        for prompt_type in ["full_script", "viral_descriptions"]:
            try:
                prompts[prompt_type] = (prompt_dir / f"{prompt_type}_prompt.txt").read_text(encoding="utf-8")
            except FileNotFoundError:
                logger.error(f"Archivo de prompt no encontrado: {prompt_type}_prompt.txt")
                prompts[prompt_type] = ""
        return prompts

    def _parse_and_validate_json(self, response_text: str, validation_model: Type[BaseModel]) -> Optional[dict]:
        """
        Extrae un bloque JSON de la respuesta de texto de la IA y lo valida contra
        el modelo Pydantic proporcionado.
        """
        if not response_text: return None
        try:
            # La IA a veces añade texto antes o después del JSON. Esta regex extrae solo el JSON.
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if not json_match:
                logger.error(f"No se encontró un objeto JSON en la respuesta de la IA. Respuesta recibida:\n{response_text}")
                return None
            data = json.loads(json_match.group(0))
            # Pydantic valida que la estructura y los tipos de datos son correctos.
            validated_data = validation_model.parse_obj(data)
            return validated_data.dict()
        except json.JSONDecodeError as e:
            logger.error(f"No se pudo parsear el JSON. Error: {e}. Respuesta recibida:\n{response_text}")
            return None
        except ValidationError as e:
            logger.error(f"Fallo de validación de Pydantic contra '{validation_model.__name__}':\n{e}")
            return None

    def process_story(self, story_text: str) -> Optional[dict[str, Any]]:
        """
        Método principal que orquesta el procesamiento completo de una historia.
        
        :param story_text: El texto completo de la historia de Reddit.
        :return: Un diccionario con el guion, las descripciones y el género del narrador, o None si falla.
        """
        if not story_text or not story_text.strip():
            logger.error("Se proporcionó un texto de historia vacío.")
            return None
        
        # 1. Generar el guion y metadatos.
        logger.info("-> Generando guion y metadata...")
        full_script_prompt = self.prompts["full_script"].format(story_text=story_text)
        script_response = self._call_llm_with_fallback(full_script_prompt)
        parsed_script_data = self._parse_and_validate_json(script_response, ScriptResponse)
        if not parsed_script_data:
            logger.error("Fallo crítico: no se pudo generar un guion válido.")
            return None
        
        script = parsed_script_data["script"]
        narrator_gender = parsed_script_data["narrator_gender"]
        
        # 2. Generar las descripciones de marketing usando el guion ya creado.
        logger.info("-> Generando descripciones de marketing para YouTube...")
        desc_prompt = self.prompts["viral_descriptions"].format(script=script) 
        desc_response = self._call_llm_with_fallback(desc_prompt)
        descriptions = self._parse_and_validate_json(desc_response, DescriptionsResponse)
        if not descriptions:
            # No es un error crítico; el proceso puede continuar sin descripciones.
            logger.warning("No se pudieron generar las descripciones de marketing. Se continuará sin ellas.")
        
        return {
            "script": script, 
            "descriptions": descriptions or {}, 
            "narrator_gender": narrator_gender
        }