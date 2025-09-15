import os
import json
import time
import google.generativeai as genai
from dotenv import load_dotenv

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

# --- CONFIGURAÇÃO DA API GEMINI (sem alterações) ---
try:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("A variável de ambiente GEMINI_API_KEY não foi encontrada.")
    genai.configure(api_key=api_key)
except Exception as e:
    print(f"Erro na configuração da API Gemini: {e}")
    exit()

# --- MODELO E CONFIGURAÇÕES DE GERAÇÃO (sem alterações) ---
# Se e quando o modelo "gemini-2.5-flash" for lançado oficialmente, este nome estará correto.
# Por agora, para testes, talvez precise usar 'gemini-1.5-flash-latest'.
model = genai.GenerativeModel('gemini-2.5-flash')

generation_config = {
    "temperature": 0.0,
    "response_mime_type": "application/json",
    "response_schema": {
        "type": "OBJECT",
        "properties": {
            "relevance": {
                "type": "STRING",
                "enum": ["yes", "no"] 
            }
        },
        "required": ["relevance"]
    },
}

safety_settings = {
    'HATE': 'BLOCK_NONE',
    'HARASSMENT': 'BLOCK_NONE',
    'SEXUAL' : 'BLOCK_NONE',
    'DANGEROUS' : 'BLOCK_NONE'
}

def is_post_related(post_text, topic_prompt, project_context, max_retries=5):
    """
    Usa a API do Gemini no modo JSON para verificar a relevância de um post,
    usando um contexto específico do projeto.
    """
    
    full_prompt = f"""{topic_prompt}

--- CONTEXT ABOUT THE PROJECT AND MY FARMING STATUS ---
{project_context}
--- END OF CONTEXT ---

--- TASK: ANALYZE THE FOLLOWING POST and respond in the required JSON format ---

Post Text: \"{post_text}\"
"""

    for attempt in range(max_retries):
        print(f"   > Enviando para API Gemini (JSON Mode). Tentativa {attempt + 1}/{max_retries}...")
        try:
            response = model.generate_content(
                full_prompt,
                generation_config=generation_config,
                safety_settings=safety_settings,
            )
            
            raw_answer = response.text.strip()
            print(f"   > Resposta bruta do Gemini (JSON): '{raw_answer}'")
            
            parsed_json = json.loads(raw_answer)
            answer = parsed_json.get("relevance")

            if answer == 'yes':
                return True
            elif answer == 'no':
                return False
            else:
                print(f"   > AVISO: Resposta JSON inválida ('{raw_answer}'). Tentando novamente...")

        except json.JSONDecodeError:
            print(f"   > AVISO: Resposta não foi um JSON válido ('{raw_answer}'). Tentando novamente...")
        except Exception as e:
            print(f"   > !!! Erro ao contatar a API do Gemini: {e}. Tentando novamente em 5 segundos...")
            time.sleep(5)
            
    print(f"   > !!! ERRO FINAL: Gemini não forneceu uma resposta válida após {max_retries} tentativas.")
    return False