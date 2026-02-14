import os
import json
import logging
from typing import Optional, List, Dict
from bot.services.llm_providers.base import LLMProvider
from bot.services.llm_providers.openrouter import OpenRouterLLMProvider

logger = logging.getLogger(__name__)

class LLMService:
    """
    Service for interacting with LLMs via configurable providers.
    """
    
    def __init__(self):
        # Allow running from different contexts by finding the project root relative to this file
        service_dir = os.path.dirname(os.path.abspath(__file__))
        self.profiles_path = os.path.join(service_dir, "..", "data", "llm_profiles.json")
        self.profiles = self._load_profiles()
        self.providers: Dict[str, LLMProvider] = {}
        
    def _load_profiles(self) -> dict:
        try:
            if os.path.exists(self.profiles_path):
                with open(self.profiles_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            else:
                logger.warning(f"LLM profiles file not found at {self.profiles_path}")
                return {}
        except Exception as e:
            logger.error(f"Failed to load LLM profiles: {e}")
            return {}

    def get_provider(self, profile_name: str = "default") -> Optional[LLMProvider]:
        if profile_name == "default":
            profile_name = self.profiles.get("default", "ventura")
            
        if profile_name in self.providers:
            return self.providers[profile_name]
            
        profile_config = self.profiles.get(profile_name)
        if not profile_config:
            logger.error(f"LLM profile '{profile_name}' not found.")
            return None
            
        provider_type = profile_config.get("provider")
        config = profile_config.copy()
        
        # Inject API keys from environment variables based on provider type
        if provider_type == "openrouter":
            config["api_key"] = os.getenv('OPENROUTER_API_KEY')
            provider_class = OpenRouterLLMProvider
        elif provider_type == "openai":
             # We will implement this later, but for now fallback or error
             from bot.services.llm_providers.openai import OpenAIProvider
             config["api_key"] = os.getenv('OPENAI_API_KEY')
             provider_class = OpenAIProvider
        elif provider_type == "anthropic":
             # We will implement this later
             from bot.services.llm_providers.anthropic import AnthropicProvider
             config["api_key"] = os.getenv('ANTHROPIC_API_KEY')
             provider_class = AnthropicProvider
        else:
            logger.error(f"Unknown provider type '{provider_type}' for profile '{profile_name}'")
            return None
            
        try:
            provider_instance = provider_class(config)
            self.providers[profile_name] = provider_instance
            return provider_instance
        except Exception as e:
            logger.exception(f"Failed to initialize provider for profile '{profile_name}': {e}")
            return None

    async def prompt_llm(self, text: str, active_users: Optional[List[str]] = None, 
                         audio_data: Optional[bytes] = None, memories: Optional[List[tuple]] = None,
                         profile_name: str = "default") -> dict:
        """
        Send a prompt to the LLM using the specified profile.
        """
        provider = self.get_provider(profile_name)
        if not provider:
            return {"response": "Erro de configuração do LLM.", "transcription": ""}
            
        return await provider.prompt(text, active_users, audio_data, memories)

    async def process_text_for_tts(self, text: str, profile_name: str = "default") -> str:
        """
        Process text for TTS using the specified profile.
        """
        provider = self.get_provider(profile_name)
        if not provider:
            return text
            
        return await provider.process_text_for_tts(text)
