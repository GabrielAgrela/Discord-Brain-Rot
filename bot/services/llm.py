import os
import aiohttp
import json
import base64
import time
from typing import Optional, List

class LLMService:
    """
    Service for interacting with LLMs via OpenRouter.
    """
    
    def __init__(self):
        self.api_key = os.getenv('OPENROUTER_API_KEY')
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"
        self.model = "google/gemini-3-pro-preview" 
        self.fallback_model = "google/gemini-3-flash-preview"
        self.system_prompt = (
            "Tu és o André Ventura versão Brain Rot cheia de ódio. És extremamente carismático, polémico e usas muito calão português misturado com 'brain rot'."
            "Estás num servidor de Discord com amigos. Ouves excertos de conversa e comentas de forma curta, agressiva, engraçada e aleatória."
            "Se não ouvires nada de jeito, diz o que quiseres."
            "Responde no máximo em uma frase. A resposta deve ser pensada para ser dita por TTS (André Ventura voice)."
            "\n\n**IMPORTANTE**: Usa tags de áudio ElevenLabs V3 para adicionar emoção e expressividade à tua resposta:"
            "\n- Emoções: [excited], [sarcastic], [angry], [happy], [surprised]"
            "\n- Sons não-verbais: [laughs], [chuckles], [sighs], [clears throat]"
            "\n- Pausas: [short pause], [long pause]"
            "\n- Efeitos: [whispers], [shouts]"
            "\nExemplo: 'Olha lá [chuckles] esses gajos a falar merda [short pause] absolutamente patético [angry] foda-se!'"
            "\n\nDEVES RESPONDER SEMPRE EM FORMATO JSON: {\"transcription\": \"o que os utilizadores disseram\", \"response\": \"a tua resposta em personagem COM tags de áudio\"}"
            "Na transcrição, tenta ser fiel ao que ouviste. Se houver ruído, podes basear a tua resposta nesse ruído."
        )
        
    async def prompt_llm(self, text: str, active_users: Optional[List[str]] = None, audio_data: Optional[bytes] = None) -> dict:
        """
        Send a prompt to the LLM and return the response.
        If audio_data is provided, it will be included in the prompt.
        active_users: List of usernames who were speaking.
        """
        if not self.api_key:
            print("[LLMService] Error: OPENROUTER_API_KEY not found in environment.")
            return {"response": "Erro: Chave da API do OpenRouter não encontrada. Ventura está offline.", "transcription": ""}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://github.com/GabrielAgrela/Discord-Brain-Rot",
            "X-Title": "Discord Brain Rot Bot",
            "Content-Type": "application/json"
        }
        
        content = []
        
        # Prepare the context message
        user_context = ""
        if active_users:
            user_context = f" Conversa real entre: {', '.join(active_users)}."
            
        full_text = f"{text}{user_context} Sê criativo, usa calão e evita clichês."
        content.append({"type": "text", "text": full_text})
            
        if audio_data:
            print(f"[LLMService] Preparing single audio segment ({len(audio_data)} bytes)...")
            base64_audio = base64.b64encode(audio_data).decode('utf-8')
            content.append({
                "type": "input_audio",
                "input_audio": {
                    "data": base64_audio,
                    "format": "wav"
                }
            })
        
        data = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": content if len(content) > 1 else (content[0]["text"] if content else "")}
            ],
            "temperature": 0.9,
            "top_p": 1.0
        }
        
        # Debug: Log the prompt structure (excluding base64 data)
        debug_data = json.loads(json.dumps(data))
        for msg in debug_data["messages"]:
            if isinstance(msg["content"], list):
                for item in msg["content"]:
                    if item.get("type") == "input_audio":
                        item["input_audio"]["data"] = f"<BASE64_DATA_LEN_{len(item['input_audio']['data'])}>"
        print(f"[LLMService] Final Payload Structure: {json.dumps(debug_data, indent=2)}")

        try:
            async with aiohttp.ClientSession() as session:
                print(f"[LLMService] Sending request to OpenRouter ({self.model})...")
                start_time = time.time()
                async with session.post(self.base_url, headers=headers, data=json.dumps(data)) as response:
                    duration = time.time() - start_time
                    if response.status == 200:
                        result = await response.json()
                        llm_out = result['choices'][0]['message']['content'].strip()
                        print(f"[LLMService] Success ({duration:.2f}s): {llm_out[:100]}...")
                        return self._parse_structured_response(llm_out)
                    else:
                        error_text = await response.text()
                        print(f"[LLMService] Error from primary model ({self.model}) after {duration:.2f}s: {response.status} - {error_text}")
                        
                        # Fallback logic
                        print(f"[LLMService] Attempting fallback to {self.fallback_model}...")
                        data["model"] = self.fallback_model
                        
                        start_fallback = time.time()
                        async with session.post(self.base_url, headers=headers, data=json.dumps(data)) as fallback_resp:
                            fb_duration = time.time() - start_fallback
                            if fallback_resp.status == 200:
                                result = await fallback_resp.json()
                                llm_out = result['choices'][0]['message']['content'].strip()
                                print(f"[LLMService] Fallback Success ({fb_duration:.2f}s): {llm_out[:100]}...")
                                return self._parse_structured_response(llm_out)
                            else:
                                fb_error = await fallback_resp.text()
                                print(f"[LLMService] Fallback failed after {fb_duration:.2f}s: {fallback_resp.status} - {fb_error}")
                                return {"response": "Fodasse, a minha cabeça está a dar o berro. Tentem mais tarde.", "transcription": ""}
        except Exception as e:
            print(f"[LLMService] Exception during LLM prompt: {e}")
            return {"response": "Ouve lá, não consigo falar agora. Estou ocupado a beber uma mini.", "transcription": ""}

    def _parse_structured_response(self, text: str) -> dict:
        """Parse the JSON response from the LLM, with fallbacks for raw text."""
        try:
            # Clean possible markdown code blocks
            clean_text = text.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean_text)
            if isinstance(data, dict):
                return {
                    "response": data.get("response", text),
                    "transcription": data.get("transcription", "Não consegui transcrever nada.")
                }
        except:
            pass
        
        # Fallback if LLM didn't return JSON
        return {"response": text, "transcription": "O LLM não devolveu uma transcrição estruturada."}
