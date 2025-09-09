import os
import notion_client
from dotenv import load_dotenv
from datetime import datetime
import re

# Carrega as variáveis do arquivo .env
load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_PAGE_ID = os.getenv("NOTION_PAGE_ID") 

# Verifica se as variáveis foram carregadas
if not NOTION_TOKEN or not NOTION_PAGE_ID:
    print("Erro fatal: NOTION_TOKEN ou NOTION_PAGE_ID não definidos no arquivo .env")
    exit()

notion = notion_client.Client(auth=NOTION_TOKEN)

# --- Função Auxiliar de Fatiamento (Chunking Function) ---
def create_paragraph_blocks_from_text(text_content, chunk_size=2000):
    """
    Divide um texto longo em múltiplos blocos de parágrafo do Notion,
    respeitando o limite de caracteres por bloco.
    """
    # Garante que text_content seja uma string, caso contrário retorna lista vazia
    if not isinstance(text_content, str):
        return []
        
    text_chunks = [text_content[i:i + chunk_size] for i in range(0, len(text_content), chunk_size)]
    blocks = []
    for chunk in text_chunks:
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": chunk}
                }]
            }
        })
    return blocks

def clean_text_for_notion(text):
    """Aplica regras de limpeza avançadas para melhorar a formatação no Notion."""
    
    # 1. Protege parágrafos: Substitui quebras de linha duplas (ou mais) por um marcador temporário.
    # Isso garante que não vamos destruir parágrafos intencionais na próxima etapa.
    # Usamos \n{2,} para pegar 2 ou mais quebras de linha seguidas.
    text_with_paragraphs = re.sub(r'\n{2,}', ' __PARAGRAPH_BREAK__ ', text)
    
    # 2. Remove quebras de linha únicas: Substitui todas as quebras de linha restantes por um espaço.
    # É aqui que corrigimos o problema de "@PayPal\nVentures", transformando em "@PayPal Ventures".
    text_no_single_breaks = re.sub(r'\n', ' ', text_with_paragraphs)
    
    # 3. Restaura os parágrafos: Troca o marcador temporário de volta para quebras de linha duplas.
    cleaned_text = re.sub(r'\s*__PARAGRAPH_BREAK__\s*', '\n\n', text_no_single_breaks)
    
    # 4. Remove espaços múltiplos que podem ter sido criados no processo.
    cleaned_text = re.sub(r' +', ' ', cleaned_text)
    
    # 5. Remove espaços em branco ou quebras de linha no início ou fim do texto final.
    return cleaned_text.strip()

# --- Função Principal de Criação de Blocos (Modificada) ---
def create_blocks_for_post(post_data):
    """Cria a lista de blocos do Notion para um único post e suas mídias."""
    username = post_data.get('username', 'Usuário Desconhecido')
    post_date_str = post_data.get('datetime')
    if post_date_str:
        post_date = datetime.fromisoformat(post_date_str).strftime("%d/%m/%Y %H:%M")
    else:
        post_date = "Data desconhecida"
        
    link = post_data.get('link', '#')
    content_parts = post_data.get('content', [])

    # Bloco de cabeçalho
    blocks = [
        {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": f"Post de @{username} em {post_date}"}}]}},
        {"type": "paragraph", "paragraph": {
            "rich_text": [
                {"type": "text", "text": {"content": "Link original: "}},
                {"type": "text", "text": {"content": link, "link": {"url": link}}}
            ]
        }}
    ]
    
    # Processa cada parte do conteúdo (texto e anexos)
    for part in content_parts:
        text_to_add = part.get('text')
        attachments_to_add = part.get('attachments', [])

        if text_to_add:
             # 1. Limpa o texto antes de enviá-lo para a função de fatiamento.
            cleaned_text = clean_text_for_notion(text_to_add)
            
            # 2. Chama a função de fatiamento com o texto limpo.
            paragraph_blocks = create_paragraph_blocks_from_text(cleaned_text)
            
            blocks.extend(paragraph_blocks)

        for attachment_url in attachments_to_add:
            print(f"    [Debug Notion] Tentando incorporar URL: {attachment_url}")
            blocks.append({
                "type": "embed",
                "embed": {
                    "url": attachment_url
                }
            })
    
    blocks.append({"type": "divider", "divider": {}})
    return blocks

# --- Função de Envio para a API do Notion ---
def append_post_to_page(post_data):
    """Anexa os dados de um post ao final de uma página específica do Notion."""
    # A verificação das variáveis de ambiente já foi feita no início.

    blocks_to_add = create_blocks_for_post(post_data)

    try:
        print(f"  -> Anexando post de {post_data.get('username', 'N/A')} à página do Notion...")
        notion.blocks.children.append(
            block_id=NOTION_PAGE_ID,
            children=blocks_to_add
        )
        print("  -> Sucesso! Blocos adicionados ao Notion.")
    except notion_client.errors.APIResponseError as e:
        print(f"!!! ERRO ao anexar blocos ao Notion: {e}")

# --- Função de Envio de Notificação Simples ---
def send_notification_to_notion(message_text, add_divider=True):
    print(f" N-> Enviando notificação para o Notion: '{message_text[:50]}...'")

    notification_blocks = [
        {
            "type": "callout",
            "callout": {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": message_text}
                }],
                "icon": {"emoji": "ℹ️"} # Ícone de informação
            }
        }
    ]

    if add_divider:
        notification_blocks.append({"type": "divider", "divider": {}})

    try:
        notion.blocks.children.append(
            block_id=NOTION_PAGE_ID,
            children=notification_blocks
        )
        print(" N-> Notificação enviada com sucesso ao Notion.")
    except notion_client.errors.APIResponseError as e:
        print(f"!!! ERRO ao enviar notificação ao Notion: {e}")