from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any

class LLMProvider(ABC):
    """
    Abstract base class for LLM providers.
    """
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.api_key = config.get("api_key")
        self.model = config.get("model")
        self.system_prompt = config.get("system_prompt", "")

    @abstractmethod
    async def prompt(self, text: str, active_users: Optional[List[str]] = None, 
                     audio_data: Optional[bytes] = None, memories: Optional[List[tuple]] = None) -> dict:
        """
        Send a prompt to the LLM and return the response.
        Should return a dictionary with "response" and "transcription" keys.
        """
        pass

    @abstractmethod
    async def process_text_for_tts(self, text: str) -> str:
        """
        Process text to add TTS tags or other formatting.
        """
        pass
