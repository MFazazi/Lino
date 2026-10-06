from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=Path(__file__).with_name('.env'), extra='ignore')

    lino_host: str = '127.0.0.1'
    lino_port: int = 8765
    lino_model: str = 'qwen3:4b'
    ollama_host: str = 'http://127.0.0.1:11434'

    whisper_model: str = 'small'
    whisper_device: str = 'cpu'
    whisper_compute_type: str = 'int8'

    brave_search_api_key: str = ''
    web_search_country: str = 'FR'
    web_search_lang: str = 'fr'
    web_results: int = 8

    tts_enabled: bool = True
    tts_rate: int = 185
    tts_voice_hint: str = 'fr'

    download_dir: str = str(Path.home() / 'Downloads' / 'Lino')
    n8n_webhook_base_url: str = ''

    gmail_credentials_path: str = 'google_credentials.json'
    gmail_token_path: str = 'google_token.json'


settings = Settings()
