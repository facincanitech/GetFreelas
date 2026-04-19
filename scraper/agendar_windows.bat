@echo off
:: Agenda o scraper para rodar todo dia às 7h
:: Execute este .bat uma vez como Administrador

schtasks /create /tn "GetFreelas Scraper" ^
  /tr "python \"%~dp0scraper.py\"" ^
  /sc daily /st 07:00 ^
  /f

echo.
echo Agendado! O scraper vai rodar todo dia as 07:00.
echo Para testar agora: python scraper.py
pause
