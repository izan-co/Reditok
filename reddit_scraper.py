"""
Módulo Cazador de Contenido (Reddit)
------------------------------------
Este módulo se encarga de conectarse a la API de Reddit para buscar y seleccionar
historias interesantes que servirán como base para los vídeos. Utiliza una estrategia
de "temperatura" para identificar los subreddits más activos y luego busca en ellos
los posts más relevantes basados en una puntuación combinada de upvotes y comentarios.
"""

import os
import praw
import logging
from dotenv import load_dotenv
from pathlib import Path
from config import (
    ALL_SUBREDDITS, PROCESSED_POSTS_FILE, NUM_HOT_SUBREDDITS_TO_HUNT, 
    MIN_POST_TEXT_LENGTH, MIN_COMMENT_TEXT_LENGTH, POST_SCORE_WEIGHT, COMMENT_SCORE_WEIGHT
)

logger = logging.getLogger(__name__)

class RedditScraper:
    """Gestiona la conexión y la extracción de historias de Reddit."""
    def __init__(self):
        """Inicializa el scraper, carga las credenciales y la lista de posts ya procesados."""
        self._load_env()
        self.reddit = self._initialize_reddit()
        self.processed_ids = self._load_processed_posts()

    def _load_env(self):
        """Carga las variables de entorno necesarias para la API de Reddit desde el archivo .env."""
        load_dotenv(Path(__file__).resolve().parent / '.env')
        self.client_id = os.getenv("REDDIT_CLIENT_ID")
        self.client_secret = os.getenv("REDDIT_CLIENT_SECRET")
        self.user_agent = os.getenv("REDDIT_USER_AGENT")

        if not all([self.client_id, self.client_secret, self.user_agent]):
            raise ValueError("Faltan credenciales de Reddit en el archivo .env. Por favor, configúralas.")

    def _initialize_reddit(self) -> praw.Reddit:
        """Crea y devuelve una instancia de PRAW para interactuar con la API de Reddit."""
        return praw.Reddit(
            client_id=self.client_id,
            client_secret=self.client_secret,
            user_agent=self.user_agent
        )

    def _load_processed_posts(self) -> set:
        """
        Carga los IDs de los posts que ya han sido procesados desde un archivo de log
        para evitar volver a utilizarlos.
        """
        log_path = Path(PROCESSED_POSTS_FILE)
        if not log_path.exists():
            log_path.touch()
            return set()
        return set(log_path.read_text().splitlines())

    def _save_processed_post(self, post_id: str):
        """Añade el ID de un post recién procesado al archivo de log y a la memoria."""
        with open(PROCESSED_POSTS_FILE, "a") as f:
            f.write(f"{post_id}\n")
        self.processed_ids.add(post_id)

    def _get_subreddit_temperature(self, subreddit_name: str) -> int:
        """
        Calcula una "temperatura" para un subreddit sumando las puntuaciones de sus
        posts más calientes. Esto ayuda a priorizar los subreddits con más actividad.
        """
        try:
            subreddit = self.reddit.subreddit(subreddit_name)
            hot_posts = list(subreddit.hot(limit=25))
            # Suma el score de los posts que no están fijados (stickied).
            temperature = sum(post.score for post in hot_posts if not post.stickied)
            logger.info(f"  - Temperatura de r/{subreddit_name}: {temperature}")
            return temperature
        except Exception as e:
            logger.warning(f"  - Error midiendo temperatura de r/{subreddit_name}: {e}")
            return 0

    def _get_hot_subreddits(self) -> list[str]:
        """
        Analiza todos los subreddits de la lista de configuración y devuelve una lista
        ordenada de los más "calientes" (con mayor temperatura).
        """
        logger.info("\n--- Midiendo temperatura de subreddits de calidad ---")
        subreddit_temps = {name: self._get_subreddit_temperature(name) for name in ALL_SUBREDDITS}
        # Ordena los subreddits por temperatura de mayor a menor y toma los N primeros.
        hot_subreddits = sorted(subreddit_temps, key=subreddit_temps.get, reverse=True)[:NUM_HOT_SUBREDDITS_TO_HUNT]
        logger.info(f"\nCazando en los {len(hot_subreddits)} subreddits más calientes: {', '.join(hot_subreddits)}")
        return hot_subreddits

    def _hunt_candidate_posts(self, hot_subreddits: list[str], num_stories: int, post_limit_per_subreddit: int) -> list[tuple]:
        """
        Busca posts candidatos en los subreddits proporcionados. Utiliza una búsqueda
        escalonada por tiempo (día, semana, mes, año) para asegurar que siempre encuentre
        contenido, incluso si la actividad reciente es baja.
        """
        candidate_posts = []
        time_filters = ['day', 'week', 'month', 'year']
        logger.info(f"\n--- Iniciando caza escalonada (objetivo: {num_stories} historias) ---")

        for time_filter in time_filters:
            if len(candidate_posts) >= num_stories:
                break
            logger.info(f"--- Cazando en los mejores posts de la última '{time_filter}' ---")
            for name in hot_subreddits:
                if len(candidate_posts) >= num_stories:
                    continue
                try:
                    # Itera sobre los posts 'top' del subreddit para el filtro de tiempo actual.
                    for post in self.reddit.subreddit(name).top(time_filter=time_filter, limit=post_limit_per_subreddit):
                        if self._is_valid_post(post):
                            # Calcula una puntuación ponderada para el post.
                            score = (post.score * POST_SCORE_WEIGHT) + (post.num_comments * COMMENT_SCORE_WEIGHT)
                            candidate_posts.append((score, post))
                except Exception as e:
                    logger.warning(f"Error cazando en r/{name} con filtro '{time_filter}': {e}")
        return candidate_posts

    def _get_top_comment(self, post: praw.models.Submission) -> str:
        """
        Extrae el comentario más votado de un post, siempre que cumpla ciertos
        criterios de calidad (no es del autor, no es de un bot, tiene longitud mínima).
        """
        try:
            post.comment_sort = "top"  # Ordena los comentarios por los más votados.
            post.comments.replace_more(limit=0) # Evita cargar comentarios anidados para mejorar rendimiento.

            for comment in post.comments.list():
                # Filtros para asegurar que el comentario es de calidad.
                if (hasattr(comment, 'author') and comment.author and
                    comment.author.name != post.author and
                    "bot" not in comment.author.name.lower() and
                    len(comment.body) > MIN_COMMENT_TEXT_LENGTH):
                    return f"La gente respondió: {comment.body}"
            return ""
        except Exception as e:
            logger.warning(f"    - Error extrayendo comentario: {e}")
            return ""

    def _is_valid_post(self, post: praw.models.Submission) -> bool:
        """Verifica si un post cumple con los requisitos básicos para ser procesado."""
        return (post.id not in self.processed_ids and # No ha sido procesado antes.
                not post.stickied and                # No es un post fijado.
                post.is_self and                       # Es un post de texto (no un enlace o imagen).
                len(post.selftext) >= MIN_POST_TEXT_LENGTH) # Tiene una longitud mínima.

    def _create_story_package(self, post: praw.models.Submission, score: float) -> dict:
        """
        Crea un diccionario estructurado (paquete) con toda la información relevante
        de una historia seleccionada, lista para ser procesada por los siguientes módulos.
        """
        logger.info(f"\n-> Seleccionada: '{post.title[:60]}...' de r/{post.subreddit.display_name} (Puntuación: {int(score)})")

        top_comment = self._get_top_comment(post)
        # Combina título, cuerpo y comentario en un solo texto para el LLM.
        full_story_text = f"Title: {post.title}\n\nBody: {post.selftext}\n\nTop Comment: {top_comment}"

        self._save_processed_post(post.id) # Marca el post como procesado.

        return {
            "id": post.id,
            "title": post.title,
            "story_text": full_story_text,
            "subreddit": post.subreddit.display_name,
            "upvotes": post.score,
            "comments": post.num_comments
        }

    def get_best_stories(self, num_stories: int = 1, post_limit_per_subreddit: int = 50) -> list[dict]:
        """
        Método principal del scraper. Orquesta la búsqueda, selección y empaquetado
        de las mejores historias de Reddit.
        
        :param num_stories: El número de historias que se desea obtener.
        :param post_limit_per_subreddit: Límite de posts a revisar por subreddit en cada filtro de tiempo.
        :return: Una lista de diccionarios, donde cada uno es un "paquete de historia".
        """
        logger.info("\n[MODULO CAZADOR]: Iniciando búsqueda de historias...")
        logger.info(f"Memoria cargada: {len(self.processed_ids)} posts procesados.")

        try:
            hot_subreddits = self._get_hot_subreddits()
            candidate_posts = self._hunt_candidate_posts(hot_subreddits, num_stories, post_limit_per_subreddit)

            if not candidate_posts:
                logger.error("CAZA FALLIDA: No se encontraron posts candidatos válidos.")
                return []

            # Ordena los candidatos por su puntuación y selecciona los mejores.
            candidate_posts.sort(key=lambda x: x[0], reverse=True)
            top_stories = [
                self._create_story_package(post, score)
                for score, post in candidate_posts[:num_stories]
            ]

            logger.info(f"\n[MODULO CAZADOR]: Caza finalizada. {len(top_stories)} historias encontradas.")
            return top_stories

        except Exception as e:
            logger.error(f"Error crítico en [MODULO CAZADOR]: {e}", exc_info=True)
            return []