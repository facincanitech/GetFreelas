@echo off
title GetFreelas Admin

:: Inicia o servidor local em background
start "GetFreelas Server" /min python "%~dp0scraper\server.py"

:: Aguarda o servidor subir
timeout /t 2 /nobreak >nul

:: Abre o painel no navegador padrão
start "" "%~dp0admin.html"
