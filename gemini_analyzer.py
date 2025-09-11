import os
import json # Importa a biblioteca JSON
import time
import google.generativeai as genai
from dotenv import load_dotenv

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

# --- CONFIGURAÇÃO DA API GEMINI ---
try:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("A variável de ambiente GEMINI_API_KEY não foi encontrada.")
    genai.configure(api_key=api_key)
except Exception as e:
    print(f"Erro na configuração da API Gemini: {e}")
    exit()

# --- MODELO E CONFIGURAÇÕES DE GERAÇÃO (ATUALIZADO PARA MODO JSON) ---
# Nota: Ainda estou mantendo o `gemini-1.5-flash-latest` pois "2.5-flash" não é um modelo publicamente disponível no momento.
# Se e quando ele for lançado, você só precisa mudar o nome aqui. A lógica funcionará.
model = genai.GenerativeModel('gemini-2.5-flash')

# ATUALIZAÇÃO: Forçamos a saída para ser um JSON estruturado.
# Isso é MUITO mais confiável do que analisar texto.
generation_config = {
    "temperature": 0.0,
    "response_mime_type": "application/json",
    "response_schema": {
        "type": "OBJECT",
        "properties": {
            "relevance": {
                "type": "STRING",
                # Garante que a resposta só pode ser 'yes' ou 'no'
                "enum": ["yes", "no"] 
            }
        },
        "required": ["relevance"]
    },
}

# Configurações de segurança para evitar bloqueios por falso-positivo.
safety_settings = {
    'HATE': 'BLOCK_NONE',
    'HARASSMENT': 'BLOCK_NONE',
    'SEXUAL' : 'BLOCK_NONE',
    'DANGEROUS' : 'BLOCK_NONE'
}

# A função clean_llm_response não é mais necessária com o modo JSON, mas podemos mantê-la caso precise no futuro.
# def clean_llm_response(...):

def is_post_related(post_text, topic_prompt, max_retries=5):
    """
    Usa a API do Gemini no modo JSON para verificar a relevância de um post.
    """
    # Adicionamos uma instrução para o modelo pensar em JSON.
    full_prompt = f"{topic_prompt}\n\n--- TASK: ANALYZE THE FOLLOWING POST and respond in the required JSON format ---\n\nPost Text: \"{post_text}\""

    for attempt in range(max_retries):
        print(f"   > Enviando para API Gemini (JSON Mode). Tentativa {attempt + 1}/{max_retries}...")
        try:
            response = model.generate_content(
                full_prompt,
                generation_config=generation_config,
                safety_settings=safety_settings,
            )
            
            # ATUALIZAÇÃO: Analisa a resposta JSON
            raw_answer = response.text.strip()
            print(f"   > Resposta bruta do Gemini (JSON): '{raw_answer}'")
            
            parsed_json = json.loads(raw_answer)
            answer = parsed_json.get("relevance")

            if answer == 'yes':
                return True
            elif answer == 'no':
                return False
            else:
                # Este caso é raro com o schema JSON, mas é uma boa prática
                print(f"   > AVISO: Resposta JSON inválida ('{raw_answer}'). Tentando novamente...")

        except json.JSONDecodeError:
            print(f"   > AVISO: Resposta não foi um JSON válido ('{raw_answer}'). Tentando novamente...")
        except Exception as e:
            print(f"   > !!! Erro ao contatar a API do Gemini: {e}. Tentando novamente em 5 segundos...")
            time.sleep(5)
            
    print(f"   > !!! ERRO FINAL: Gemini não forneceu uma resposta válida após {max_retries} tentativas.")
    return False

