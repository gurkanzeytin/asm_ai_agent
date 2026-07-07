import logging

from app.core.settings import Settings

logger = logging.getLogger(__name__)

try:
    # Instantiate and validate settings at module load time
    settings = Settings()
except Exception as e:
    logger.critical(f"Failed to load or validate application settings: {e}")
    raise e
