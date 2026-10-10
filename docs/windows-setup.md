# Uruchomienie na Windows

Wymagania demo: Python 3.12, Git i PowerShell. Nie wymaga WSL, Docker ani PostgreSQL. Polecenia można wywoływać z dowolnej lokalizacji, ponieważ skrypty wyznaczają katalog projektu ze swojej ścieżki.

```powershell
Set-Location 'C:\projekty\region-comparison'
powershell -NoProfile -ExecutionPolicy RemoteSigned -File .\scripts\bootstrap.ps1
powershell -NoProfile -ExecutionPolicy RemoteSigned -File .\scripts\run-demo.ps1
```

Otwórz http://localhost:8503. RemoteSigned dotyczy wyłącznie nowego procesu PowerShell, nie zmienia ustawień użytkownika/systemu i nie ma pierwszeństwa przed Group Policy. Przy zezwoleniu na skrypty w bieżącej sesji można też wywołać je bezpośrednio. Pierwsza instalacja wymaga dostępu do PyPI; późniejsze uruchomienia aplikacji korzystają z wersjonowanego snapshotu bez sieci GUS. Interpreter `.venv` jest używany bez aktywacji.

Jeżeli `py` nie jest dostępne, wskaż interpreter Python 3.12:

```powershell
powershell -NoProfile -ExecutionPolicy RemoteSigned -File .\scripts\bootstrap.ps1 -Python 'C:\path with spaces\Python312\python.exe'
```

Pełny tryb wymaga działającego Docker Desktop z backendem Linux. Nie instalujemy ani nie przełączamy backendu automatycznie.

```powershell
docker compose up -d --build --wait --wait-timeout 180
docker compose ps
```

Otwórz http://localhost:8602. Baza dostępna jest lokalnie na porcie 55432. Zwykłe zatrzymanie: `docker compose down`, bez `-v`, aby zachować dane. Nie trzeba tworzyć `.env`; wartości domyślne są jawnie przeznaczone do lokalnego demo. Własny `.env` pozostaje poza Git i nie jest nadpisywany przez skrypty.

```powershell
powershell -NoProfile -ExecutionPolicy RemoteSigned -File .\scripts\check.ps1
$env:TEST_DATABASE_URL = 'postgresql+psycopg://region:region_demo_local_only@127.0.0.1:55432/region_test'
powershell -NoProfile -ExecutionPolicy RemoteSigned -File .\scripts\check.ps1 -Postgres
.\.venv\Scripts\python.exe -m region_comparison doctor
.\.venv\Scripts\python.exe -m region_comparison report --output docs/findings.md
powershell -NoProfile -ExecutionPolicy RemoteSigned -File .\scripts\build-review-bundle.ps1
```

Przed integracją utwórz dedykowaną bazę `region_test`; nigdy nie ustawiaj TEST_DATABASE_URL na produkcję. Normalne testy offline celowo nie wybierają grupy `postgres`; nie jest to dowód zaliczenia integracji.

Odświeżenie źródła jest świadomą operacją:

```powershell
powershell -NoProfile -ExecutionPolicy RemoteSigned -File .\scripts\refresh-data.ps1 -Destination 'data/raw/new-snapshot'
.\.venv\Scripts\python.exe -m region_comparison load --snapshot 'data/raw/new-snapshot'
```

`load` wymaga DATABASE_URL. Niepełny fetch pozostawia checkpoint i nie aktywuje zbioru. Poprzedni poprawny snapshot pozostaje dostępny. GUS_CLIENT_ID jest opcjonalnym kluczem przekazywanym wyłącznie w nagłówku X-ClientId.

Typowe problemy: brak Pythona 3.12 — zainstaluj właściwą wersję i wskaż ją `-Python`; zajęty port — `run-demo.ps1 -Port 8505`; brak połączenia z bazą — sprawdź Docker Desktop i `docker compose logs`; blokada skryptów przez politykę systemu — nie zmieniaj globalnego ExecutionPolicy, użyj bezpośrednio `.venv\Scripts\python.exe -m streamlit run app.py` z REGION_DATA_MODE=snapshot. Ograniczeń organizacji nie obchodzimy.
