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
.\.venv\Scripts\python.exe -m region_comparison report
powershell -NoProfile -ExecutionPolicy RemoteSigned -File .\scripts\build-review-bundle.ps1
```

Przed integracją utwórz dedykowaną bazę `region_test`; nigdy nie ustawiaj TEST_DATABASE_URL na produkcję. Normalne testy offline celowo nie wybierają grupy `postgres`; nie jest to dowód zaliczenia integracji.

Odświeżenie źródła jest świadomą operacją:

```powershell
powershell -NoProfile -ExecutionPolicy RemoteSigned -File .\scripts\refresh-data.ps1
.\.venv\Scripts\python.exe -m region_comparison load --snapshot 'output/snapshots/<id-z-wyniku-fetch>'
```

`load` wymaga DATABASE_URL. Niepełny fetch pozostawia checkpoint i nie aktywuje zbioru. Poprzedni poprawny snapshot pozostaje dostępny. GUS_CLIENT_ID jest opcjonalnym kluczem przekazywanym wyłącznie w nagłówku X-ClientId.

Typowe problemy: brak Pythona 3.12 — zainstaluj właściwą wersję i wskaż ją `-Python`; zajęty port — `run-demo.ps1 -Port 8505`; brak połączenia z bazą — sprawdź Docker Desktop i `docker compose logs`; blokada skryptów przez politykę systemu — nie zmieniaj globalnego ExecutionPolicy, użyj bezpośrednio `.venv\Scripts\python.exe -m streamlit run app.py` z REGION_DATA_MODE=snapshot. Ograniczeń organizacji nie obchodzimy.
Nowe `refresh-data.ps1` za każdym razem tworzy unikalny snapshot i pobiera nowe odpowiedzi.
Wznowienie: `-Mode resume -Snapshot 'output/snapshots/<id>'`; jawne reuse kompletnego zbioru:
`-Mode reuse -Snapshot 'data/sample'`. Żaden z tych kroków nie aktywuje danych w bazie.
`initialize` seeduje pustą bazę i zachowuje istniejący poprawny aktywny snapshot; `load` jawnie go zmienia.

CLI Python nie wczytuje automatycznie lokalnego `.env`. Działająca konfiguracja PowerShell:

```powershell
$env:GUS_CLIENT_ID = 'lokalny-identyfikator'
.\\scripts\\refresh-data.ps1
Remove-Item Env:GUS_CLIENT_ID
```

Jawny argument klienta ma pierwszeństwo nad GUS_CLIENT_ID; starszy alias GUS_API_KEY jest używany
wyłącznie przy braku zmiennej kanonicznej. Pusta wartość kanoniczna oznacza pracę anonimową.

Raporty domyślnie trafiają do `output/reports/<run_id>/`, paczki do `output/review/<run_id>/`,
a testy zapisują log i JUnit w `output/codex_runs/<run_id>/logs/`.
Własny `--output` musi pozostać w projektowym output po rozwiązaniu ścieżki; root, docs oraz katalog
nadrzędny są odrzucane. Skrypty korzystają ze wspólnego common.ps1 i modułu paths.
Dowody v0.1.0 zachowano lokalnie w `output/codex_runs/legacy-v0_1_0/`; ilustracje README są utrzymywanymi
zasobami dokumentacji. Nowe zrzuty tworzy `scripts/capture-screenshots.py` w output.
