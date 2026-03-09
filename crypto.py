import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv, set_key

ENV_PATH = os.path.join(os.path.dirname(__file__), '.env')

def _get_fernet() -> Fernet:
    load_dotenv(ENV_PATH)
    key = os.getenv('ENCRYPTION_KEY', '').strip()
    if not key:
        key = Fernet.generate_key().decode()
        set_key(ENV_PATH, 'ENCRYPTION_KEY', key)
        os.environ['ENCRYPTION_KEY'] = key
    return Fernet(key.encode())

def encrypt(text: str) -> str:
    return _get_fernet().encrypt(text.encode()).decode()

def decrypt(text: str) -> str:
    return _get_fernet().decrypt(text.encode()).decode()
