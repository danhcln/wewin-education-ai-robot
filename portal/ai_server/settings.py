import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def whisper_path():
    if (ROOT/'data/ai-whisper-base/model.bin').is_file():return str(ROOT/'data/ai-whisper-base')
    candidates=list((Path.home()/'.cache/huggingface/hub/models--Systran--faster-whisper-base.en/snapshots').glob('*/model.bin'))
    return str(candidates[0].parent) if candidates else ''


@dataclass
class Settings:
    db: Path=field(default_factory=lambda:Path(os.environ.get('WEWIN_AI_DB',ROOT/'data/ai-staging.sqlite3')))
    key_file: Path=field(default_factory=lambda:Path(os.environ.get('WEWIN_AI_ADMIN_KEY_FILE',ROOT/'.secrets/ai_admin_key')))
    ollama: str=field(default_factory=lambda:os.environ.get('WEWIN_AI_OLLAMA','http://127.0.0.1:11434'))
    asr_model: str=field(default_factory=lambda:os.environ.get('WEWIN_AI_ASR_MODEL',whisper_path()))
    tts_models: str=field(default_factory=lambda:os.environ.get('WEWIN_AI_TTS_MODELS',str(Path.home()/'.cache/supertonic3')))
    public_ws: str=field(default_factory=lambda:os.environ.get('WEWIN_AI_PUBLIC_WS','ws://127.0.0.1:8010/xiaozhi/v1/'))
    device_origin: str=field(default_factory=lambda:os.environ.get('WEWIN_AI_DEVICE_ORIGIN','http://127.0.0.1:8010'))
    trusted_tls_edge: bool=field(default_factory=lambda:os.environ.get('WEWIN_AI_TRUST_TLS_EDGE')=='1')
    real_devices: bool=field(default_factory=lambda:os.environ.get('WEWIN_AI_ALLOW_REAL_DEVICES')=='1')
    mqtt_enabled: bool=field(default_factory=lambda:os.environ.get('WEWIN_AI_MQTT_ENABLED')=='1')
    mqtt_bind: str=field(default_factory=lambda:os.environ.get('WEWIN_AI_MQTT_BIND','127.0.0.1'))
    mqtt_port: int=field(default_factory=lambda:int(os.environ.get('WEWIN_AI_MQTT_PORT','18883')))
    mqtt_public_host: str=field(default_factory=lambda:os.environ.get('WEWIN_AI_MQTT_PUBLIC_HOST','127.0.0.1'))
    udp_bind: str=field(default_factory=lambda:os.environ.get('WEWIN_AI_UDP_BIND','127.0.0.1'))
    udp_port: int=field(default_factory=lambda:int(os.environ.get('WEWIN_AI_UDP_PORT','18884')))
    mqtt_cert: str=field(default_factory=lambda:os.environ.get('WEWIN_AI_MQTT_TLS_CERT',''))
    mqtt_key: str=field(default_factory=lambda:os.environ.get('WEWIN_AI_MQTT_TLS_KEY',''))
    provider_timeout: float=field(default_factory=lambda:float(os.environ.get('WEWIN_AI_PROVIDER_TIMEOUT','90')))
    llm_stream: bool=field(default_factory=lambda:os.environ.get('WEWIN_AI_LLM_STREAM','1')=='1')
    tokenizer: str=field(default_factory=lambda:os.environ.get('WEWIN_AI_TOKENIZER',str(ROOT/'data/ai-qwen3-tokenizer/tokenizer.json')))
    qwen25_tokenizer: str=field(default_factory=lambda:os.environ.get('WEWIN_AI_QWEN25_TOKENIZER',str(ROOT/'data/ai-qwen25-tokenizer/tokenizer.json')))
    llm_gpu_layers: int=field(default_factory=lambda:int(os.environ.get('WEWIN_AI_LLM_GPU_LAYERS','-1')))
    connector_db: Path=field(default_factory=lambda:Path(os.environ.get('WEWIN_AI_CONNECTOR_DB', (ROOT.parent/'connector/data/wewin_fts.db' if (ROOT.parent/'connector/data/wewin_fts.db').exists() else (ROOT.parent/'Wewin Connector/Wewin_AI_Connector/data/wewin_fts.db' if (ROOT.parent/'Wewin Connector/Wewin_AI_Connector/data/wewin_fts.db').exists() else ROOT.parent/'connector/data/wewin_fts.db')))))

    def admin_key(self):
        try:
            value=self.key_file.read_text(encoding='utf-8').strip()
            return value if 32<=len(value)<=512 else ''
        except OSError:
            return ''

    @property
    def device_issuer_file(self):
        return Path(os.environ.get('WEWIN_AI_DEVICE_ISSUER_KEY_FILE',self.key_file.parent/'ai_device_issuer_key'))
