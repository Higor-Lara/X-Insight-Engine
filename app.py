import streamlit as st
from datetime import datetime
import os

# Importa as funções da lógica principal e as funções utilitárias
from scraper_logic import run_with_logging_and_state
from utils import (
    load_config, save_config, load_profiles, save_profiles, 
    load_env_vars, save_env_vars, LOG_FILE
)

# --- Configuração da Página ---
st.set_page_config(page_title="X-Insight Engine", layout="wide")

# --- Injeção de CSS para o Scroll na Coluna da Direita ---
st.markdown("""
<style>
/* Seleciona o stVerticalBlock que está dentro de um stForm, que está dentro da segunda coluna */
div[data-testid="stColumn"]:nth-of-type(2) div[data-testid="stForm"] div[data-testid="stVerticalBlock"] {
    max-height: 80vh !important; /* Aumentei um pouco para dar mais espaço */
    overflow-y: auto !important;
    padding-right: 15px;
}
</style>
""", unsafe_allow_html=True)

# --- Barra Lateral para Configurações ---
with st.sidebar:
    st.header("⚙️ Configurações")
    
    current_env = load_env_vars()
    with st.form("api_keys_form"):
        st.subheader("Chaves de API")
        notion_token = st.text_input("Notion Token", value=current_env.get("NOTION_TOKEN", ""), type="password")
        notion_page_id = st.text_input("Notion Page ID", value=current_env.get("NOTION_PAGE_ID", ""), type="password")
        gemini_api_key = st.text_input("Gemini API Key", value=current_env.get("GEMINI_API_KEY", ""), type="password")
        
        submitted = st.form_submit_button("Salvar Chaves")
        if submitted:
            new_env = {
                "NOTION_TOKEN": notion_token,
                "NOTION_PAGE_ID": notion_page_id,
                "GEMINI_API_KEY": gemini_api_key
            }
            save_env_vars(new_env)

# --- Layout Principal com Duas Colunas ---
left_col, right_col = st.columns([2, 3])

# --- COLUNA ESQUERDA: Título e Controle ---
with left_col:
    st.title("🚀 X-Insight Engine")
    st.markdown("Seu painel de controle para monitorar e analisar oportunidades de airdrop.")
    
    st.subheader("Status e Controle")

    config = load_config()
    last_manual = config.get("last_manual_run_timestamp")
    last_scheduled = config.get("last_scheduled_run_timestamp")

    if last_manual or last_scheduled:
        last_manual_dt = datetime.fromisoformat(last_manual) if last_manual else datetime.min
        last_scheduled_dt = datetime.fromisoformat(last_scheduled) if last_scheduled else datetime.min
        latest_run_dt = max(last_manual_dt, last_scheduled_dt)
        latest_run_type = "manual" if latest_run_dt == last_manual_dt else "automática"
        st.info(f"Última análise ({latest_run_type}): **{latest_run_dt.strftime('%d/%m/%Y às %H:%M:%S')}**")
    else:
        st.info("Nenhuma análise executada ainda.")

    if st.button("▶️ Iniciar Análise Manual", use_container_width=True, type="primary"):
        with st.spinner("Análise em andamento... Isso pode levar alguns minutos."):
            profiles_to_scan = load_profiles()
            if not profiles_to_scan:
                st.error("Nenhum perfil para analisar. Adicione e salve um perfil ao lado.")
            else:
                posts_sent = run_with_logging_and_state(profiles_to_scan, run_type="manual")
                st.toast(f"Análise Concluída! {posts_sent} posts enviados para o Notion.", icon="🎉")
                st.rerun()

# --- COLUNA DIREITA: Gerenciamento de Perfis ---
with right_col:
    st.subheader("Perfis Monitorados e Contexto")

    if 'profiles' not in st.session_state:
        st.session_state.profiles = load_profiles()
    
    with st.form("profiles_form"):
        
        # --- ALTERAÇÃO PRINCIPAL AQUI ---
        # Criamos um container com altura fixa. Somente este container terá a barra de rolagem.
        # O `height` é definido em pixels.
        with st.container(height=600):
            for i, profile in enumerate(st.session_state.profiles):
                
                with st.container(border=True): # O `border=True` cria uma borda visual
                    header_col, delete_col = st.columns([4, 1])
                    
                    with header_col:
                        st.caption(f"Perfil #{i+1}")
                    
                    with delete_col:
                        if st.form_submit_button("🗑️ Remover", key=f"delete_{i}"):
                            st.session_state.profiles.pop(i)
                            st.rerun()
                    
                    new_name = st.text_input(
                        "nome",
                        value=profile['name'], 
                        key=f"name_{i}",
                        placeholder="Ex: NexusLabs"
                    )
                    st.session_state.profiles[i]['name'] = new_name

                    new_context = st.text_area(
                        "contexto",
                        value=profile['context'], 
                        key=f"context_{i}",
                        height=100,
                        placeholder="Ex: Projeto em mainnet com pontos Lux. Farmando apenas na rede Bob..."
                    )
                    st.session_state.profiles[i]['context'] = new_context
        
        # --- Os botões ficam FORA do container com altura fixa ---
        # Por isso, eles não rolam e ficam sempre visíveis no final do formulário.
        st.markdown("---") # Adiciona um separador antes dos botões
        col_add, col_save = st.columns(2)
        
        with col_add:
            if st.form_submit_button("➕ Adicionar Novo Perfil", use_container_width=True):
                st.session_state.profiles.append({"name": "", "context": ""})
                st.rerun()
        
        with col_save:
            if st.form_submit_button("💾 Salvar Alterações", type="primary", use_container_width=True):
                valid_profiles = [p for p in st.session_state.profiles if p['name'].strip()]
                save_profiles(valid_profiles)
                st.session_state.profiles = valid_profiles
                st.toast("Lista de perfis atualizada com sucesso!", icon="📝")
                st.rerun()


# --- Seção de Logs (Abaixo das colunas) ---
st.markdown("---")
with st.expander("📄 Ver Logs da Última Execução"):
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            log_content = f.read()
        st.code(log_content, language="log")
    else:
        st.warning("Nenhum arquivo de log encontrado. Execute uma análise para gerá-lo.")