@echo off
REM Navega para a pasta do projeto
cd /d "C:\Projetos\X-Insight-Engine"

REM Ativa o ambiente virtual
call "venv\Scripts\activate.bat"

REM Executa o script Python
echo Iniciando o scraper...
python scraper.py
echo Scraper finalizado.