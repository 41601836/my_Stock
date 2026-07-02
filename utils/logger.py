import logging
import os

log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(log_dir, "scheduler.log"), encoding="utf-8"),
        logging.StreamHandler()
    ]
)

scheduler_log = logging.getLogger('scheduler')
scheduler_log.setLevel(logging.INFO)