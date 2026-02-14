import os
import aiohttp
import json
import logging
from typing import Optional, List, Dict, Any
from .base import LLMProvider

logger = logging.getLogger(__name__)

class OpenAIProvider(LLMProvider):
    """
    Provider for interacting with OpenAI.
    """
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.base_url = "https://api.openai.com/v1/chat/completions"
        if not self.model:
            self.model = "gpt-4o"

    async def prompt(self, text: str, active_users: Optional[List[str]] = None, 
                     audio_data: Optional[bytes] = None, memories: Optional[List[tuple]] = None) -> dict:
        if not self.api_key:
            return {"response": "Erro: Chave da API OpenAI não encontrada.", "transcription": ""}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # Similar logic to OpenRouter, but OpenAI handles audio differently (Whisper for transcription, separate endpoint).
        # For chat completion, we just send text. If audio_data is present, we might need a separate step for transcription.
        # But wait, GPT-4o supports audio input directly? Yes, via "input_audio" in some contexts, but let's stick to standard chat for now
        # or minimal implementation.
        
        # Note: This is a basic implementation. OpenAI API for audio input is evolving.
        # For now, we'll assume text-based interaction or just ignore audio if not supported by the specific endpoint/model in this way.
        
        content = [{"type": "text", "text": text}]
        
        # If active users provided, add context
        if active_users:
             content[0]["text"] += f" (Users: {', '.join(active_users)})"

        data = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": content}
            ],
            "temperature": self.config.get("temperature", 0.9)
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.base_url, headers=headers, json=data) as response:
                    if response.status == 200:
                        result = await response.json()
                        llm_out = result['choices'][0]['message']['content'].strip()
                        return self._parse_response(llm_out)
                    else:
                        logger.error(f"OpenAI Error: {await response.text()}")
                        return {"response": "Erro na API da OpenAI.", "transcription": ""}
        except Exception as e:
            logger.exception(f"OpenAI Exception: {e}")
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
        # Implementation for OpenAI if needed, or just return text
        return text
