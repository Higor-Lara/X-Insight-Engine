# utils.py
import json
import os

# --- Constantes de Arquivos ---
CONFIG_FILE = "config.json"
PROFILES_FILE = "profiles.json"
ENV_FILE = ".env"
LOG_FILE = "execution.log"

# --- Funções para Gerenciar Arquivos ---

def load_config():
    """Carrega o arquivo de configuração."""
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_config(data):
    """Salva dados no arquivo de configuração."""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

def load_profiles():
    """Carrega a lista de perfis do arquivo JSON."""
    try:
        with open(PROFILES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_profiles(profiles_list):
    """Salva a lista de perfis no arquivo JSON."""
    with open(PROFILES_FILE, 'w', encoding='utf-8') as f:
        json.dump(profiles_list, f, ensure_ascii=False, indent=4)

def load_env_vars():
    """Carrega as variáveis do arquivo .env para exibição."""
    if not os.path.exists(ENV_FILE):
        return {"NOTION_TOKEN": "", "NOTION_PAGE_ID": "", "GEMINI_API_KEY": ""}
    
    env_vars = {}
    with open(ENV_FILE, 'r') as f:
        for line in f:
            if '=' in line:
                key, value = line.strip().split('=', 1)
                env_vars[key] = value.strip('"\'')
    return env_vars

def save_env_vars(vars_dict):
    """Salva as chaves de API no arquivo .env."""
    with open(ENV_FILE, 'w', encoding='utf-8') as f:
        for key, value in vars_dict.items():
            f.write(f'{key}="{value}"\n')