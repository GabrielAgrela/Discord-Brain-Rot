import os
import aiohttp
import json
import logging
from typing import Optional, List, Dict, Any
from .base import LLMProvider

logger = logging.getLogger(__name__)

class AnthropicProvider(LLMProvider):
    """
    Provider for interacting with Anthropic.
    """
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.base_url = "https://api.anthropic.com/v1/messages"
        if not self.model:
            self.model = "claude-3-5-sonnet-20240620"

    async def prompt(self, text: str, active_users: Optional[List[str]] = None, 
                     audio_data: Optional[bytes] = None, memories: Optional[List[tuple]] = None) -> dict:
        if not self.api_key:
            return {"response": "Erro: Chave da API Anthropic não encontrada.", "transcription": ""}

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        
        content = [{"type": "text", "text": text}]
        
        # If active users provided, add context
        if active_users:
             content[0]["text"] += f" (Users: {', '.join(active_users)})"

        data = {
            "model": self.model,
            "system": self.system_prompt,
            "messages": [
                {"role": "user", "content": content}
            ],
            "max_tokens": 1024,
            "temperature": self.config.get("temperature", 0.9)
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.base_url, headers=headers, json=data) as response:
                    if response.status == 200:
                        result = await response.json()
                        llm_out = result['content'][0]['text'].strip()
                        return self._parse_response(llm_out)
                    else:
                        logger.error(f"Anthropic Error: {await response.text()}")
                        return {"response": "Erro na API da Anthropic.", "transcription": ""}
        except Exception as e:
            logger.exception(f"Anthropic Exception: {e}")
            return {"response": "Erro interno.", "transcription": ""}

    def _parse_response(self, text: str) -> dict:
        try:
            clean_text = text.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean_text)
            if isinstance(data, dict):
                return data
        except:
            pass
        return {"response": text, "transcription": ""}

    async def process_text_for_tts(self, text: str) -> str:
        # Implementation for Anthropic if needed, or just return text
        return text
