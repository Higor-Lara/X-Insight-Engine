import ollama
import time
import re

def clean_llm_response(response_text):
    """Limpa a resposta do LLM para extrair 'yes' ou 'no'."""
    match = re.search(r'\b(yes|no)\b', response_text.lower())
    if match:
        return match.group(1)
    return None

# --- MUDANÇA 1: Atualize a assinatura da função para aceitar 'knowledge_base' ---
def is_post_related(post_text, topic, llm_model='llama3:8b', max_retries=5):
    """
    Usa o Ollama e o LLM para verificar se um post está relacionado a um tópico,
    usando uma base de conhecimento fornecida.
    """
    
    # --- MUDANÇA 2: Novo prompt estruturado ---
    prompt = f"""
{topic}

--- POST TEXT TO ANALYZE ---
{post_text}
--- END OF POST TEXT TO ANALYZE ---

**CRITICAL INSTRUCTIONS FOR ANALYSIS:**
All answers must always be ONLY “yes” or “no”.
If it is not possible to understand the meaning of what is written, if the post contains no text, or if the text is ambiguous, the default answer to be returned must be “yes”.
Your Answer:"""

    for attempt in range(max_retries):
        # Simplificando o print do log para não poluir o terminal com o tópico inteiro,
        # já que a base de conhecimento é grande e fixa.
        if attempt == 0:
             print(f"    > Verificando relevância para o tópico: '{topic}'")
        print(f"    > Tentativa {attempt + 1}/{max_retries}...")

        try:
            response = ollama.chat(
                model=llm_model,
                messages=[{'role': 'user', 'content': prompt}],
                options={'temperature': 0.1}
            )
            
            raw_answer = response['message']['content'].strip()
            clean_answer = clean_llm_response(raw_answer) 
            
            print(f"    > Resposta bruta do LLM: '{raw_answer}'")

            if clean_answer == 'yes':
                return True
            elif clean_answer == 'no':
                return False
            else:
                print(f"    > AVISO: Resposta inválida do LLM ('{raw_answer}'). Tentando novamente...")

        except Exception as e:
            print(f"    > !!! Erro ao contatar o Ollama: {e}. Tentando novamente...")
        
        time.sleep(2)

    print(f"    > !!! ERRO FINAL: O LLM não forneceu uma resposta válida após {max_retries} tentativas.")
    return False