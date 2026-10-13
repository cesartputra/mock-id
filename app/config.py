import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEIGHTS = ROOT / 'app' / 'model' / 'weights'
DATA = Path(os.getenv('MOCK_ID_DATA_DIR', str(ROOT / 'data')))
SESSION_TTL = 15 * 60
MAX_ATTEMPTS = 3
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_FRAME_BYTES = 500 * 1024
MAX_FRAMES = 48
DEFAULT_SETTINGS = {'face_cosine': 0.40, 'pad_probability': 0.80, 'deepfake_risk': 0.80, 'blur_min': 45.0}
