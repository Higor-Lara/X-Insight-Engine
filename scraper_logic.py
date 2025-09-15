import json
import random
import re
import time
from datetime import datetime, timezone, timedelta
from contextlib import redirect_stdout

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from gemini_analyzer import is_post_related
from notion_handler import append_post_to_page, send_notification_to_notion
from utils import load_config, save_config, LOG_FILE, load_profiles

# --- Constantes ---
STATE_FILE = "run_state.json"

# --- Funções de Estado (sem alterações) ---
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

# --- Funções de Scraping e Extração (sem alterações na lógica interna) ---
def get_nitter_profile_url(username, nitter_instance):
    return f"{nitter_instance}/{username}"

def parse_nitter_datetime(dt_string):
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
    print(f"   -> Verificando URL: {post_url}")
    try:
        driver.get(post_url)
        time.sleep(3)
        soup = BeautifulSoup(driver.page_source, 'html.parser')
    except Exception as e:
        print(f"   -> !!! Erro ao acessar a página do post: {e}")
        return None, None
    before_tweet_div = soup.find('div', class_='before-tweet')
    if before_tweet_div and before_tweet_div.find('a'):
        root_href = before_tweet_div.find('a')['href']
        root_url = base_url + root_href
        print(f"   -> Post filho detectado. Navegando para a raiz da thread: {root_url}")
        return get_thread_root_url_and_content(root_url, driver, base_url)
    print(f"   -> Raiz da thread encontrada: {post_url}")
    return post_url, soup

def extract_detailed_post_content(timeline_item_div, base_url):
    text_content = ""
    content_div = timeline_item_div.find('div', class_='tweet-content')
    if content_div:
        text_content = content_div.get_text(separator='\n', strip=True)
    attachments = []
    attachments_container = timeline_item_div.find('div', class_='attachments')
    if attachments_container:
        image_tags = attachments_container.select('.attachment a img')
        for tag in image_tags:
            if tag.has_attr('src'):
                attachments.append(base_url + tag['src'])
        video_tags = attachments_container.select('.attachment video')
        for tag in video_tags:
            if tag.has_attr('poster'):
                attachments.append(base_url + tag['poster'])
    return {"text": text_content, "attachments": list(set(attachments))}

def extract_full_thread_content(soup, base_url):
    main_thread_container = soup.find('div', class_='main-thread')
    if not main_thread_container:
        return []
    content_parts = []
    main_tweet_div = main_thread_container.find('div', class_='main-tweet')
    if main_tweet_div:
        timeline_item = main_tweet_div.find('div', class_='timeline-item')
        if timeline_item:
            content_parts.append(extract_detailed_post_content(timeline_item, base_url))
    after_tweet_container = main_thread_container.find('div', class_='after-tweet')
    if after_tweet_container:
        continuation_posts = after_tweet_container.find_all('div', class_='timeline-item', recursive=False)
        print(f"     -> Encontradas {len(continuation_posts)} continuações na thread.")
        for post in continuation_posts:
            content_parts.append(extract_detailed_post_content(post, base_url))
    return content_parts

# --- Função Principal Refatorada ---
def run_full_analysis(profiles_to_scan): # <-- MUDANÇA: O parâmetro agora é a lista de perfis com contexto
    start_collecting_from = load_last_run_timestamp()
    
    nitter_instances = [
        "https://nitter.net", "https://nitter.tiekoetter.com",
        "https://nitter.privacyredirect.com", "https://nuku.trabun.org",
    ]

    print("Iniciando o navegador Selenium em segundo plano...")
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
    options.add_experimental_option('excludeSwitches', ['enable-logging'])
    
    try:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    except Exception as e:
        print(f"!!! Falha ao iniciar o ChromeDriver: {e}")
        return 0

    all_final_data = []
    filtered_posts_count = 0
    try:
        all_posts_to_process = []
        processed_thread_ids = set()
        failed_instances = set()
        
        # <-- MUDANÇA: O loop de scraping agora itera sobre a lista de perfis
        for profile in profiles_to_scan:
            username = profile['name'] # Pega o nome do perfil do dicionário
            page_successfully_loaded = False
            for instance_url in nitter_instances:
                if instance_url in failed_instances: continue
                
                # Usa o 'username' para fazer a busca
                page_load_success, posts_found = find_posts_on_profile_page(username, start_collecting_from, instance_url, driver)
                
                if page_load_success:
                    all_posts_to_process.extend(posts_found)
                    page_successfully_loaded = True
                    break
                else:
                    failed_instances.add(instance_url)
            
            if not page_successfully_loaded:
                print(f"!!! ERRO GERAL: Nenhuma instância funcional para '{username}'.")

        if all_posts_to_process:
            print("\n" + "="*50 + "\nINICIANDO PROCESSAMENTO DETALHADO\n" + "="*50)
            for post_data in all_posts_to_process:
                base_instance_url = '/'.join(post_data["link"].split('/')[:3])
                root_url, soup = get_thread_root_url_and_content(post_data["link"], driver, base_instance_url)
                if not root_url or not soup: continue
                match = re.search(r'/status/(\d+)', root_url)
                if not match: continue
                thread_id = match.group(1)
                if thread_id in processed_thread_ids:
                    print(f"   -> Thread ID {thread_id} já processada. Pulando.")
                    continue
                print(f"   -> Processando nova thread com ID {thread_id}.")
                content_parts = extract_full_thread_content(soup, base_instance_url)
                if content_parts:
                    post_data["link"] = root_url
                    post_data["content"] = content_parts
                    all_final_data.append(post_data)
                    processed_thread_ids.add(thread_id)
                time.sleep(random.uniform(1, 2))
    finally:
        print("\nFechando o navegador Selenium.")
        driver.quit()

    output_filename = "extracted_x_posts.json"
    with open(output_filename, 'w', encoding='utf-8') as f:
        json.dump(all_final_data, f, ensure_ascii=False, indent=4)
    print(f"\nExtração concluída! {len(all_final_data)} posts salvos em '{output_filename}'.")
    
    if all_final_data:
        save_latest_timestamp(all_final_data)
        print("\n" + "="*50 + "\nINICIANDO A ANÁLISE COM A API DO GEMINI\n" + "="*50)
        
        task_description = """
        **1. Your Role and Objective:**
        You are a specialized AI assistant for an expert airdrop hunter. Your only task is to act as a personalized filter. In each request, you will receive my current "Project & Farming Status" and a "Social Media Post" from that project. Your goal is to determine if the post is relevant **TO ME**, based on my status. If there is no project context and/or my airdrop farming status, consider any relevant signal related to the "Airdrop" theme as a "yes" answer.

        **2. The Core Question:**
        "Does this post contain new, actionable information for my specific farming strategy, OR does it announce critical, universal airdrop logistics?"

        **3. High-Relevance Triggers (Always answer 'yes'):**
        - **Universal Airdrop Logistics:** The post mentions critical, general information like: a "claim" process, a wallet "checker", official "snapshot" dates, "TGE" (Token Generation Event), token "listing" dates, or new, universal "eligibility" tasks that apply to everyone.
        - **Strategy-Specific News:** The post announces updates, new tasks, or information **directly related** to the specific network, platform, or campaign mentioned in my "Project & Farming Status".

        **4. Irrelevance Triggers (Always answer 'no'):**
        - **Different Strategy Announcements:** This is a critical filter. If the post announces a new campaign, integration, or opportunity on a **different network or platform** than the one specified in my "Farming Status", it is considered noise and is NOT relevant.
        - **General Noise:** General market discussions, price speculation, standard technical updates without direct user rewards, or generic community engagement posts ("GM", "happy Monday").

        **5. Example Logic to Follow:**
        - If my status is "Farming on Bob Network" and the post says "We are now live on Solana!", your answer is 'no'.
        - If my status is "Farming on Bob Network" and the post says "New quest for all Bob Network users!", your answer is 'yes'.
        - If my status is "I have 100,000 Lux points" and the post says "The snapshot for Lux points has been taken", your answer is 'yes'.
        """
        
        # <-- MUDANÇA: Cria um mapa de 'username' -> 'contexto' para busca rápida
        profile_context_map = {p['name']: p['context'] for p in profiles_to_scan}

        filtered_posts = []
        REQUEST_LIMIT_PER_MINUTE = 9 
        request_count = 0
        minute_start_time = time.time()

        for i, post in enumerate(all_final_data):
            if request_count >= REQUEST_LIMIT_PER_MINUTE:
                elapsed_time = time.time() - minute_start_time
                if elapsed_time < 60:
                    wait_time = 60 - elapsed_time
                    print(f"\n!!! LIMITE DE RPM ATINGIDO. AGUARDANDO {wait_time:.1f} SEGUNDOS. !!!\n")
                    time.sleep(wait_time)
                request_count = 0
                minute_start_time = time.time()
            
            full_text = "\n\n---\n\n".join([part['text'] for part in post.get('content', []) if part.get('text')])
            if not full_text.strip(): continue

            print(f"\n({i+1}/{len(all_final_data)}) Analisando post de '{post['username']}': {post.get('link', 'N/A')}")
            
            # <-- MUDANÇA: Pega o contexto específico para este post usando o mapa
            current_context = profile_context_map.get(post['username'], "Nenhum contexto específico foi fornecido.")
            
            # <-- MUDANÇA: Passa o contexto para a função de análise do Gemini
            if is_post_related(full_text, task_description, current_context):
                print("   > Veredito: Relevante. Adicionando ao resultado final.")
                filtered_posts.append(post)
            else:
                print("   > Veredito: Não relevante. Ignorando.")
            request_count += 1
        
        filtered_output_filename = "filtered_posts.json"
        with open(filtered_output_filename, 'w', encoding='utf-8') as f:
            json.dump(filtered_posts, f, ensure_ascii=False, indent=4)
        print("\n" + "="*50 + f"\nANÁLISE CONCLUÍDA! {len(filtered_posts)} posts relevantes salvos.\n" + "="*50)

        if filtered_posts:
            print("\nINICIANDO ENVIO PARA O NOTION...")
            for post in filtered_posts:
                append_post_to_page(post)
                time.sleep(0.5)
            print("ENVIO PARA O NOTION CONCLUÍDO!")
            filtered_posts_count = len(filtered_posts)
        else:
            print("\nNenhum post relevante para enviar ao Notion.")
            filtered_posts_count = 0 # Garante que a variável exista
        
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M")
        message = (
            f"Relatório ({timestamp}):\n"
            f"Tweets encontrados desde a última execução: {len(all_final_data)}\n"
            f"Tweets relevantes enviados ao Notion: {filtered_posts_count}"
        )
        send_notification_to_notion(message)
    else:
        print("\nNenhum post novo coletado, etapa de análise pulada.")
    
    return filtered_posts_count

def run_with_logging_and_state(profiles_to_scan, run_type="manual"):
    with open(LOG_FILE, 'w', encoding='utf-8') as log_f:
        with redirect_stdout(log_f):
            print(f"--- Iniciando execução {'automática' if run_type == 'scheduled' else 'manual'} em {datetime.now()} ---")
            posts_sent = run_full_analysis(profiles_to_scan)
            config = load_config()
            config[f"last_{run_type}_run_timestamp"] = datetime.now().isoformat()
            save_config(config)
            print(f"--- Execução {'automática' if run_type == 'scheduled' else 'manual'} finalizada em {datetime.now()} ---")
    return posts_sent

# --- Bloco de Execução para o Agendador de Tarefas ---
if __name__ == "__main__":
    # <-- MUDANÇA: O agendador agora também usa a nova estrutura
    try:
        profiles = load_profiles() # Carrega a lista de dicionários do profiles.json
    except FileNotFoundError:
        print("!!! ERRO: Arquivo 'profiles.json' não encontrado.")
        profiles = []

    if profiles:
        # A função `run_with_logging_and_state` já espera a lista de dicionários
        run_with_logging_and_state(profiles, run_type="scheduled")