import json
import random
import re
import time
from datetime import datetime, timezone, timedelta

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from gemini_analyzer import is_post_related
from notion_handler import append_post_to_page, send_notification_to_notion

STATE_FILE = "run_state.json"

# --- Funções de Estado ---
def load_last_run_timestamp():
    """Carrega o timestamp da última execução."""
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            state_data = json.load(f)
            last_timestamp_str = state_data.get("latest_post_timestamp")
            if last_timestamp_str:
                print(f"Estado anterior encontrado. Iniciando a partir de: {last_timestamp_str}")
                return datetime.fromisoformat(last_timestamp_str)
    except (FileNotFoundError, json.JSONDecodeError):
        print("Arquivo de estado não encontrado ou inválido. Iniciando a partir das últimas 24 horas.")
    return datetime.now(timezone.utc) - timedelta(days=1)

def save_latest_timestamp(posts):
    """Salva o timestamp mais recente no arquivo de estado."""
    if not posts:
        print("Nenhum post novo encontrado. O arquivo de estado não será atualizado.")
        return
    latest_post = max(posts, key=lambda post: datetime.fromisoformat(post['datetime']))
    latest_timestamp = latest_post['datetime']
    state_data = {"latest_post_timestamp": latest_timestamp}
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state_data, f, indent=4)
    print(f"Estado salvo. A próxima execução começará a partir de: {latest_timestamp}")

# --- Funções de Scraping e Extração ---
def get_nitter_profile_url(username, nitter_instance):
    """Gera a URL de um perfil do X no Nitter."""
    return f"{nitter_instance}/{username}"

def parse_nitter_datetime(dt_string):
    """Converte a string de data/hora do Nitter para um objeto datetime."""
    formats = ["%b %d, %Y · %I:%M %p %Z", "%b %d, %Y · %H:%M %Z"]
    for fmt in formats:
        try:
            if "UTC" in dt_string:
                dt_string_no_tz = dt_string.replace(" UTC", "").strip()
                dt_obj = datetime.strptime(dt_string_no_tz, fmt.replace(" %Z", ""))
                return dt_obj.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Não foi possível analisar a data/hora: {dt_string}")

def extract_initial_post_data(post_container, base_url):
    """Extrai os dados iniciais (link e data) da página de perfil."""
    link_tag = post_container.find('a', class_='tweet-link')
    post_link = base_url + link_tag['href'] if link_tag else None
    time_tag = post_container.find('span', class_='tweet-date')
    datetime_str = time_tag.find('a')['title'] if time_tag and time_tag.find('a') else None
    post_datetime = None
    if datetime_str:
        try:
            post_datetime = parse_nitter_datetime(datetime_str)
        except ValueError:
            post_datetime = None
    return {"link": post_link, "datetime": post_datetime}

def find_posts_on_profile_page(username, start_date, nitter_instance, driver):
    """Navega pela página de perfil e retorna (sucesso, lista_de_links)."""
    profile_url = get_nitter_profile_url(username, nitter_instance)
    print(f"\nBuscando links de posts em: {profile_url}")
    try:
        driver.get(profile_url)
        print("-> Aguardando 5 segundos para a página de perfil carregar...")
        time.sleep(5)
        html_content = driver.page_source
    except Exception as e:
        print(f"!!! Erro de conexão ao acessar {profile_url}: {e}")
        return False, []

    soup = BeautifulSoup(html_content, 'html.parser')
    posts_containers = soup.find_all('div', class_='timeline-item')

    if not posts_containers:
        print(f"-> AVISO: Nenhum post encontrado em {nitter_instance}. Instância considerada falha.")
        return False, []

    print(f"-> Encontrados {len(posts_containers)} posts na página de perfil.")
    links_to_process = []
    for container in posts_containers:
        post = extract_initial_post_data(container, nitter_instance)
        if post["datetime"] and post["datetime"] > start_date and post["link"]:
            links_to_process.append({
                "username": username,
                "link": post["link"],
                "datetime": post["datetime"].isoformat()
            })
    print(f"-> {len(links_to_process)} posts atendem ao critério de data e serão processados.")
    return True, links_to_process

def get_thread_root_url_and_content(post_url, driver, base_url):
    """Encontra a URL raiz de uma thread e retorna o conteúdo da página."""
    print(f"  -> Verificando URL: {post_url}")
    try:
        driver.get(post_url)
        time.sleep(3)
        soup = BeautifulSoup(driver.page_source, 'html.parser')
    except Exception as e:
        print(f"  -> !!! Erro ao acessar a página do post: {e}")
        return None, None
    before_tweet_div = soup.find('div', class_='before-tweet')
    if before_tweet_div and before_tweet_div.find('a'):
        root_href = before_tweet_div.find('a')['href']
        root_url = base_url + root_href
        print(f"  -> Post filho detectado. Navegando para a raiz da thread: {root_url}")
        return get_thread_root_url_and_content(root_url, driver, base_url)
    print(f"  -> Raiz da thread encontrada: {post_url}")
    return post_url, soup

# --- NOVA FUNÇÃO PARA EXTRAIR CONTEÚDO DETALHADO (TEXTO E MÍDIA) ---
def extract_detailed_post_content(timeline_item_div, base_url):
    """Extrai texto e anexos (imagens/vídeos) de um único 'timeline-item'."""
    text_content = ""
    content_div = timeline_item_div.find('div', class_='tweet-content')
    if content_div:
        text_content = content_div.get_text(separator='\n', strip=True)

    attachments = []
    attachments_container = timeline_item_div.find('div', class_='attachments')
    if attachments_container:
        # Encontra links de imagens (href em tags <a>)
        image_tags = attachments_container.select('.attachment a img')
        for tag in image_tags:
            if tag.has_attr('src'):
                # Constrói a URL completa
                attachments.append(base_url + tag['src'])
        
        # Encontra posters de vídeos (poster em tags <video>)
        video_tags = attachments_container.select('.attachment video')
        for tag in video_tags:
            if tag.has_attr('poster'):
                attachments.append(base_url + tag['poster'])

    return {"text": text_content, "attachments": list(set(attachments))} # Usa set() para remover duplicatas caso haja

# --- FUNÇÃO ATUALIZADA PARA USAR A NOVA LÓGICA ---
def extract_full_thread_content(soup, base_url):
    """
    Extrai o conteúdo completo (texto e anexos) de uma thread.
    Retorna uma lista de dicionários, um para cada parte da thread.
    """
    main_thread_container = soup.find('div', class_='main-thread')
    if not main_thread_container:
        return []

    content_parts = []
    main_tweet_div = main_thread_container.find('div', class_='main-tweet')
    if main_tweet_div:
        # O main-tweet contém um timeline-item
        timeline_item = main_tweet_div.find('div', class_='timeline-item')
        if timeline_item:
            content_parts.append(extract_detailed_post_content(timeline_item, base_url))

    after_tweet_container = main_thread_container.find('div', class_='after-tweet')
    if after_tweet_container:
        continuation_posts = after_tweet_container.find_all('div', class_='timeline-item', recursive=False)
        print(f"    -> Encontradas {len(continuation_posts)} continuações na thread.")
        for post in continuation_posts:
            content_parts.append(extract_detailed_post_content(post, base_url))
            
    return content_parts

# --- BLOCO PRINCIPAL ---
if __name__ == "__main__":
    usernames_to_scrape = ["NexusLabs", "GoKiteAI"]
    start_collecting_from = load_last_run_timestamp()
    
    nitter_instances = [
        "https://nitter.net",
        "https://nitter.tiekoetter.com",
        "https://nitter.privacyredirect.com",
        "https://nuku.trabun.org",
    ]

    all_posts_to_process = []
    processed_thread_ids = set()
    failed_instances = set()

    print("Iniciando o navegador Selenium em segundo plano...")
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
    options.add_experimental_option('excludeSwitches', ['enable-logging'])
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    all_final_data = []
    try:
        # ETAPA 1: SCRAPING
        for user in usernames_to_scrape:
            page_successfully_loaded = False
            for instance_url in nitter_instances:
                if instance_url in failed_instances:
                    print(f"\n-> Pulando instância já falha: {instance_url}")
                    continue
                
                page_load_success, posts_found_for_this_user = find_posts_on_profile_page(user, start_collecting_from, instance_url, driver)
                
                if page_load_success:
                    print(f"-> Sucesso no carregamento para '{user}' usando {instance_url}.")
                    all_posts_to_process.extend(posts_found_for_this_user)
                    page_successfully_loaded = True
                    break
                else:
                    print(f"-> Tentativa de carregamento falhou para '{user}' em {instance_url}. Adicionando à blacklist...")
                    failed_instances.add(instance_url)
            
            if not page_successfully_loaded:
                 print(f"!!! ERRO GERAL: Nenhuma instância funcional encontrada para carregar a página do usuário '{user}'.")

        # ETAPA 2: PROCESSAMENTO
        if all_posts_to_process:
            print("\n" + "="*50)
            print("INICIANDO PROCESSAMENTO DETALHADO DOS POSTS COLETADOS")
            print("="*50)
            
            for post_data in all_posts_to_process:
                base_instance_url = '/'.join(post_data["link"].split('/')[:3])
                root_url, soup = get_thread_root_url_and_content(post_data["link"], driver, base_instance_url)

                if not root_url or not soup: continue
                match = re.search(r'/status/(\d+)', root_url)
                if not match: continue
                thread_id = match.group(1)

                if thread_id in processed_thread_ids:
                    print(f"  -> Thread ID {thread_id} já processada. Pulando.")
                    continue

                print(f"  -> Processando nova thread com ID {thread_id}.")
                # ATUALIZAÇÃO: Chama a nova função e usa a chave "content"
                content_parts = extract_full_thread_content(soup, base_instance_url)

                if content_parts:
                    post_data["link"] = root_url
                    post_data["content"] = content_parts # Salva a nova estrutura de dados
                    all_final_data.append(post_data)
                    processed_thread_ids.add(thread_id)
                time.sleep(random.uniform(1, 2))
    finally:
        print("\nFechando o navegador Selenium.")
        driver.quit()

    output_filename = "extracted_x_posts.json"
    with open(output_filename, 'w', encoding='utf-8') as f:
        json.dump(all_final_data, f, ensure_ascii=False, indent=4)
    print(f"\nExtração concluída! {len(all_final_data)} posts/threads únicos salvos em '{output_filename}'.")
    
    # ETAPA 3: ANÁLISE COM LLM
    if all_final_data:
        save_latest_timestamp(all_final_data)
        print("\n" + "="*50)
        print("INICIANDO A ANÁLISE COM A API DO GEMINI")
        print("="*50)

        
        task_description = """
**1. Your Role and Objective:**
You are an expert analyst monitoring cryptocurrency projects for airdrop opportunities. Your task is to analyze the following social media post.
Your goal is to determine if the post contains information relevant to an "airdrop hunter" monitoring this project.

**2. Core Rules:**
- Analyze the post and answer the question: "If I were farming an airdrop from this project, would this post be relevant to me?"
- **Your entire response MUST be a single word: 'yes' or 'no'. Do not include any other text, reasoning, or explanation.**

**3. Relevance Criteria (Triggers for "yes"):**
- Direct mention of "airdrop", rewards, token distribution, or "snapshot".
- Gamified campaigns: mentions of "points", "badges", NFTs for participation, or tasks on platforms like Galxe, Zealy, Layer3.
- Testnet phases: announcements of new testnets where participation might be rewarded.
- Funding news: announcements of new investment rounds (fundraising), as these often lead to future community rewards.

**4. Irrelevance Criteria (Triggers for "no"):**
- General market discussions or price speculation.
- Standard partnerships or technical updates without direct user rewards.
- Generic community engagement posts ("GM", "happy Monday", contests for swag).

**5. Training Examples (Few-Shot Learning):**

--- START EXAMPLE 1 ---
Post Input: "Big news! We just closed our Series B funding round with major VCs. Thanks to our amazing community for the support as we build the future of DeFi."
Final Answer: yes
--- END EXAMPLE 1 ---

--- START EXAMPLE 2 ---
Post Input: "Don't forget to claim your 'Early Supporter Badge' on Galxe! This recognizes everyone who joined us in Phase 1."
Final Answer: yes
--- END EXAMPLE 2 ---

--- START EXAMPLE 3 ---
Post Input: "Our dev team just pushed update 1.4.2, fixing minor UI bugs on the platform. Great work team!"
Final Answer: no
--- END EXAMPLE 3 ---
"""

        filtered_posts = []
    
        # --- NOVO: LÓGICA DE CONTROLE DE FREQUÊNCIA (THROTTLING) ---
        # Usamos 9 como limite para ter uma margem de segurança.
        REQUEST_LIMIT_PER_MINUTE = 9 
        request_count = 0
        minute_start_time = time.time()
        # --- FIM DA NOVA LÓGICA ---

        for i, post in enumerate(all_final_data):
            # --- NOVO: VERIFICAÇÃO DO LIMITE ANTES DE CADA CHAMADA ---
            if request_count >= REQUEST_LIMIT_PER_MINUTE:
                elapsed_time = time.time() - minute_start_time
                if elapsed_time < 60:
                    wait_time = 60 - elapsed_time
                    print("\n" + "-"*20)
                    print(f"!!! LIMITE DE RPM ATINGIDO. AGUARDANDO {wait_time:.1f} SEGUNDOS... !!!")
                    print("-" * 20 + "\n")
                    time.sleep(wait_time)
                
                # Zera o contador para o novo minuto
                request_count = 0
                minute_start_time = time.time()
            # --- FIM DA VERIFICAÇÃO ---

            full_text = "\n\n---\n\n".join([part['text'] for part in post.get('content', []) if part.get('text')])
            
            if not full_text.strip():
                continue

            print(f"\n({i+1}/{len(all_final_data)}) Analisando post: {post.get('link', 'Link não disponível')}")
            
            if is_post_related(full_text, task_description):
                print("   > Veredito: Relevante. Adicionando ao resultado final.")
                filtered_posts.append(post)
            else:
                print("   > Veredito: Não relevante. Ignorando.")
            
            # --- NOVO: INCREMENTA O CONTADOR APÓS CADA CHAMADA BEM-SUCEDIDA ---
            request_count += 1
            # --- FIM DO INCREMENTO ---

        # ... (o resto do seu código para salvar o JSON e enviar para o Notion continua igual) ...

        filtered_output_filename = "filtered_posts.json"
        with open(filtered_output_filename, 'w', encoding='utf-8') as f:
            json.dump(filtered_posts, f, ensure_ascii=False, indent=4)
        
        print("\n" + "="*50)
        print(f"ANÁLISE CONCLUÍDA!")
        print(f"{len(filtered_posts)} posts relevantes foram salvos em '{filtered_output_filename}'.")
        print("="*50)

        if filtered_posts:
            print("\nINICIANDO ENVIO PARA O NOTION...")
            for post in filtered_posts:
                append_post_to_page(post)
                # Pausa para respeitar os limites da API do Notion (3 req/s)
                time.sleep(0.5)
            print("ENVIO PARA O NOTION CONCLUÍDO!")
        else:
            print("\nNenhum post relevante para enviar ao Notion.")

            total_posts_found = len(all_final_data)
            timestamp = datetime.now().strftime("%d/%m/%Y %H:%M")
            notification_message = (
                f"Relatório de Execução ({timestamp}):\n"
                f"Total de tweets que batem com a data: {total_posts_found} \n"
                f"Nenhum desses posts se enquadram no assunto."
            )
            send_notification_to_notion(notification_message)

    else:
        print("\nNenhum post novo coletado, etapa de análise pulada.")
        total_posts_found = len(all_final_data)
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M")
        notification_message = (
            f"Relatório de Execução ({timestamp}):\n"
            f"Nenhum tweet novo foi encontrado. \n"
        )
        send_notification_to_notion(notification_message)