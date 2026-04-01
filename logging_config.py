# logging_config.py
import logging
import os
from datetime import datetime


def setup_logging():
    """Configura el sistema de logging"""

    # Crear directorio de logs si no existe
    if not os.path.exists('logs'):
        os.makedirs('logs')

    # Configuración básica
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(f'logs/app_{datetime.now().strftime("%Y%m%d")}.log'),
            logging.StreamHandler()
        ]
    )

    # Logger específico para accesos
    access_logger = logging.getLogger('access')
    access_handler = logging.FileHandler('logs/accesos.log')
    access_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
    access_logger.addHandler(access_handler)
    access_logger.setLevel(logging.INFO)

    return access_logger