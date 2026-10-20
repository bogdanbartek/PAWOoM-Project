# Scooter Rental Service — LAB1

Mikroserwis REST w FastAPI do zarządzania flotą hulajnóg elektrycznych i ich wypożyczaniem. Dane są przechowywane w pamięci procesu.

## Uruchomienie i testy

Wymagania: Python 3.12 lub nowszy, PowerShell. Otwórz terminal w katalogu z tym README i `requirements.txt`.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8101
```

W drugim terminalu: `Invoke-RestMethod http://localhost:8101/health`. Dokumentacja: [Swagger UI](http://localhost:8101/docs). Zatrzymanie serwera: `Ctrl+C`. Nie trzeba aktywować środowiska.

Nazwa usługi zwracana przez `/health` to `Scooter Rental Service` (ta sama w aplikacji i w teście).

## 1. Problem i granice

**Problem.** Wypożyczalnia hulajnóg działa na zasadzie wypożyczalni rowerów miejskich: klient bierze hulajnogę ze stacji, jeździ i oddaje ją z powrotem do systemu (to nie są hulajnogi „na ulicy" znajdowane w aplikacji, jak w Bolt czy Lime). Wypożyczalnia musi wiedzieć, które pojazdy ma we flocie i które są w danej chwili wolne. Bez tego dwóch klientów mogłoby wypożyczyć tę samą hulajnogę albo ktoś mógłby „zwrócić" pojazd, którego nikt nie wypożyczył.

**Użytkownik.** Klient wypożyczalni (np. przez aplikację lub terminal przy stacji), który sprawdza dostępność oraz wypożycza i zwraca hulajnogę, oraz operator floty, który rejestruje nowe hulajnogi.

**Za co usługa odpowiada:**

- rejestr hulajnóg (identyfikator, nazwa, model),
- aktualny status każdej hulajnogi (`available`, `rented`, `maintenance`),
- pilnowanie poprawnych przejść między statusami (wypożyczenie i zwrot).

**Za co usługa nie odpowiada:**

- konta i dane klientów,
- historia wypożyczeń, czas jazdy, cennik i płatności,
- lokalizacja GPS i telemetria (bateria, prędkość),
- uwierzytelnianie i autoryzacja,
- trwałe przechowywanie danych (na LAB1 tylko pamięć procesu).

**Pojęcia domenowe:**

- **Hulajnoga (Scooter)** - pojedynczy pojazd we flocie, identyfikowany liczbą całkowitą dodatnią.
- **Model** - typ/model sprzętu (np. „Xiaomi Mi 4 Pro").
- **Status** - stan hulajnogi: `available` (do wypożyczenia), `rented` (wypożyczona), `maintenance` (w serwisie).
- **Wypożyczenie (rent)** - operacja zmieniająca status z `available` na `rented`.
- **Zwrot (return)** - operacja zmieniająca status z `rented` na `available`.

|Planowana usługa|Odpowiedzialność|Własne dane|Operacje|Potrzebne informacje od innej usługi|
|---|---|---|---|---|
|Pierwsza — implementowana teraz: **Scooter Rental Service** (flota)|Rejestr hulajnóg i ich statusów; pilnowanie reguł zmiany statusu|Hulajnogi: `id`, `name`, `model`, `status`|Lista, szczegóły, dodanie, wypożyczenie, zwrot|Brak na tym etapie|
|Druga — implementowana później: **Payment Service** (płatności za hulajnogi)|Rejestrowanie płatności za hulajnogi i ich statusów|Płatności (`id`, `scooter_id`, `amount`, `status`)|Utworzenie płatności, lista, szczegóły, opłacenie|Od usługi floty: czy hulajnoga o danym `scooter_id` istnieje|

**Granice biznesowe i właściciel zapisu.** Status hulajnogi zmienia wyłącznie usługa floty - to ona jest jedynym właścicielem tych danych. Usługa płatności przechowuje tylko `scooter_id` jako odniesienie i nigdy nie zmienia ani nie kopiuje danych hulajnogi - w razie potrzeby pyta usługę floty przez HTTP. Dzięki temu reguła „nie wypożyczysz zajętej hulajnogi" jest egzekwowana w jednym miejscu.

**Plan całego projektu (4 usługi):** 1) wypożyczalnia hulajnóg (ta usługa), 2) płatności za hulajnogi, 3) ubezpieczenia, 4) serwis hulajnóg. Na LAB1 implementowana jest tylko pierwsza.

**Przyszłe wywołanie HTTP między usługami (nie jest implementowane na LAB1):**

- **Nadawca:** Payment Service, **odbiorca:** Scooter Rental Service. Wywołanie następuje przy tworzeniu płatności (`POST /payments` w usłudze płatności).
- **Metoda i ścieżka:** `GET /scooters/{scooter_id}` (np. `GET /scooters/1`) - istniejący endpoint szczegółów.
- **Żądanie:** bez ciała (identyfikator w ścieżce).
- **Odpowiedź sukcesu:** `200` z obiektem hulajnogi, np. `{"id": 1, "name": "Hulajnoga 1", "model": "Xiaomi Mi 4 Pro", "status": "available"}`. Po otrzymaniu takiej odpowiedzi usługa płatności zapisuje płatność.
- **Odpowiedź błędu:** `404` (brak hulajnogi) - usługa płatności nie tworzy płatności i zwraca klientowi błąd (np. `404` albo `422`).
- **Niedostępność odbiorcy:** żądanie ma ustawiony krótki timeout. Przy braku połączenia lub przekroczeniu czasu usługa płatności **nie zapisuje płatności** i zwraca klientowi `503 Service Unavailable` z informacją, by spróbował ponownie. Dzięki temu nie powstaje płatność za hulajnogę, której istnienia nie potwierdzono.

## 2. Model i reguła biznesowa

**Dane wejściowe przy tworzeniu (`ScooterCreate`):**

|Pole|Typ|Wymagania|
|---|---|---|
|`id`|liczba całkowita|wymagane, `> 0`|
|`name`|tekst|wymagane, 1–100 znaków|
|`model`|tekst|wymagane, 1–100 znaków|

**Zasób zwracany przez API (`Scooter`):** pola `id`, `name`, `model` oraz `status`.

**Statusy:** `available`, `rented`, `maintenance`. Nowa hulajnoga zawsze dostaje `available` - klient nie może ustawić statusu przy tworzeniu. Status `maintenance` jest częścią modelu, ale w obecnej wersji API nie ma operacji, która do niego prowadzi.

**Identyfikatory.** Nadaje je klient w żądaniu `POST /scooters` (np. numer inwentarzowy pojazdu); usługa nie generuje ich automatycznie. Identyfikator musi być unikalny w ramach instancji usługi.

**Reguła biznesowa (maszyna stanów):**

- Hulajnogę można wypożyczyć **tylko wtedy, gdy ma status `available`**.
- Hulajnogę można zwrócić **tylko wtedy, gdy ma status `rented`**.

|Operacja|Dozwolona, gdy status to|Niedozwolona, gdy status to|Kod błędu|
|---|---|---|---|
|`POST /scooters/{id}/rent`|`available` → `rented`|`rented`, `maintenance`|`409`|
|`POST /scooters/{id}/return`|`rented` → `available`|`available`, `maintenance`|`409`|

Wszystkie warunki odrzucenia (brak zasobu, zły status) są sprawdzane **przed** zmianą stanu. Zmiana następuje dopiero po przejściu walidacji - tworzona jest zaktualizowana kopia obiektu (`model_copy`) i wstawiana do magazynu. Odrzucona operacja nie zostawia więc częściowo zmienionych danych.

## 3. Kontrakt API

|Metoda|Ścieżka|Znaczenie|Sukces|Błędy|
|---|---|---|---|---|
|GET|`/health`|Status i nazwa usługi|200|brak|
|GET|`/scooters`|Lista hulajnóg|200|brak (pusta lista `[]` gdy nie ma danych)|
|GET|`/scooters/{id}`|Szczegóły hulajnogi|200|404, 422 (id nie jest liczbą)|
|POST|`/scooters`|Dodanie hulajnogi|201|409 (duplikat `id`), 422 (złe dane)|
|POST|`/scooters/{id}/rent`|Wypożyczenie|200|404, 409 (status ≠ `available`), 422|
|POST|`/scooters/{id}/return`|Zwrot|200|404, 409 (status ≠ `rented`), 422|

### Przykłady

**Health** - `GET /health` → `200`:

```json
{"status": "ok", "service": "Scooter Rental Service"}
```

**Dodanie hulajnogi** - `POST /scooters` → `201`:

```json
{"id": 1, "name": "Hulajnoga 1", "model": "Xiaomi Mi 4 Pro"}
```

```json
{"id": 1, "name": "Hulajnoga 1", "model": "Xiaomi Mi 4 Pro", "status": "available"}
```

**Lista** - `GET /scooters` → `200`:

```json
[{"id": 1, "name": "Hulajnoga 1", "model": "Xiaomi Mi 4 Pro", "status": "available"}]
```

**Szczegóły** - `GET /scooters/1` → `200`:

```json
{"id": 1, "name": "Hulajnoga 1", "model": "Xiaomi Mi 4 Pro", "status": "available"}
```

**Wypożyczenie** - `POST /scooters/1/rent` → `200`:

```json
{"id": 1, "name": "Hulajnoga 1", "model": "Xiaomi Mi 4 Pro", "status": "rented"}
```

**Zwrot** - `POST /scooters/1/return` → `200`:

```json
{"id": 1, "name": "Hulajnoga 1", "model": "Xiaomi Mi 4 Pro", "status": "available"}
```

**404 - brak zasobu** - `GET /scooters/999` → `404`:

```json
{"detail": "Scooter not found"}
```

**409 - duplikat identyfikatora** - ponowne `POST /scooters` z `id: 1` → `409`:

```json
{"detail": "Scooter with this ID already exists"}
```

**409 - naruszenie reguły biznesowej** - `POST /scooters/1/rent` na już wypożyczonej hulajnodze → `409`:

```json
{"detail": "Scooter is not available for rental"}
```

Analogicznie `POST /scooters/1/return` na hulajnodze, która nie jest wypożyczona → `409`:

```json
{"detail": "Scooter is not currently rented"}
```

**422 - błędne dane** - `POST /scooters` z `{"id": 0, "name": "", "model": "X"}` → `422` (lista błędów w formacie Pydantic/FastAPI, skrócona):

```json
{
  "detail": [
    {"type": "greater_than", "loc": ["body", "id"], "msg": "Input should be greater than 0", "input": 0, "ctx": {"gt": 0}},
    {"type": "string_too_short", "loc": ["body", "name"], "msg": "String should have at least 1 character", "input": "", "ctx": {"min_length": 1}}
  ]
}
```

### Format `detail` i dobór kodów

- Błędy zgłaszane przez kod (`HTTPException`) mają `detail` jako **pojedynczy tekst**, np. `"Scooter not found"`.
- Błędy walidacji generowane automatycznie przez FastAPI/Pydantic (`422`) mają `detail` jako **listę obiektów** z polami `type`, `loc`, `msg`, `input`. Klient musi więc obsłużyć oba kształty.
- **404** - zasób o podanym `id` nie istnieje.
- **409 Conflict** - żądanie jest poprawne składniowo, ale koliduje z aktualnym stanem zasobu (duplikat `id`, hulajnoga w niewłaściwym statusie). Nie jest to 400/422, bo dane są poprawne - problemem jest stan.
- **422** - dane nie spełniają schematu (brak pola, `id <= 0`, pusty lub zbyt długi tekst, `id` w ścieżce niebędące liczbą).
- **201** przy utworzeniu zasobu, **200** przy odczycie i zmianie stanu.

## 4. Testy i stan danych

Każdy test dostaje świeżą aplikację z `create_app()` (fixture `client` w `tests/`), więc zaczyna od pustego magazynu. Testy sprawdzają kod odpowiedzi, kluczowe pola JSON oraz wynik ponownego odczytu.

|Scenariusz|Stan początkowy i dokładne żądanie|Oczekiwany status, treść i stan|Wynik rzeczywisty|Reset danych|
|---|---|---|---|---|
|Health|Pusty magazyn; `GET /health`|`200`, `{"status": "ok", "service": "Scooter Rental Service"}`|`200`, `{"status":"ok","service":"Scooter Rental Service"}`; `test_health` przeszedł|Nowa aplikacja na test|
|Lista i szczegóły|Pusty magazyn; `GET /scooters`, potem `POST /scooters` (`id=1`) i `GET /scooters`, `GET /scooters/1`|`200 []`; po dodaniu lista ma 1 element, szczegóły zwracają tę hulajnogę ze statusem `available`|`GET /scooters` → `200 []`; po `POST` (`201`) lista miała 1 element, `GET /scooters/1` → `200` ze statusem `available`; `test_list_and_detail` przeszedł|Nowa aplikacja na test|
|Zapis → odczyt|Pusty magazyn; `POST /scooters` z `{"id":1,"name":"Hulajnoga 1","model":"Xiaomi Mi 4 Pro"}`, potem `GET /scooters/1`|`201` z `status: available`; odczyt `200` z tymi samymi danymi|`POST` → `201`, `status: available`; `GET /scooters/1` → `200` z identyczną treścią; `test_create_then_read` przeszedł|Nowa aplikacja na test|
|Brak zasobu|Pusty magazyn; `GET /scooters/999`|`404`, `{"detail": "Scooter not found"}`|`404`, `{"detail":"Scooter not found"}`; `test_not_found` przeszedł|Nowa aplikacja na test|
|Błędne dane|Pusty magazyn; `POST /scooters` z `{"id": 0, "name": "", "model": "X"}`|`422`; `GET /scooters` nadal zwraca `[]` (stan bez zmian)|`422`; `GET /scooters` nadal `[]`; `test_invalid_data_leaves_state_unchanged` przeszedł|Nowa aplikacja na test|
|Konflikt|Dodana hulajnoga `id=1`; ponowne `POST /scooters` z `id=1` i inną nazwą|`409`, `{"detail": "Scooter with this ID already exists"}`; `GET /scooters/1` nadal zwraca oryginalne dane|`409`, `{"detail":"Scooter with this ID already exists"}`; `GET /scooters/1` nadal zwraca nazwę `Hulajnoga 1`; `test_duplicate_id_conflict_keeps_original` przeszedł|Nowa aplikacja na test|
|Reguła biznesowa: dozwolona i niedozwolona operacja|Dodana hulajnoga `id=1` (`available`); `POST /scooters/1/rent` → `200`/`rented`; ponowne `POST /scooters/1/rent` → `409`; `POST /scooters/1/return` → `200`/`available`; kolejne `POST /scooters/1/return` → `409`|Statusy i kody jak w opisie; po odrzuconej operacji status pozostaje bez zmian (potwierdzony przez `GET`)|`rent` → `200`/`rented`; drugi `rent` → `409`, status nadal `rented`; `return` → `200`/`available`; drugi `return` → `409`, status nadal `available`; `test_rent_and_return_rules` przeszedł|Nowa aplikacja na test|
|Wypożyczenie/zwrot nieistniejącej hulajnogi|Pusty magazyn; `POST /scooters/999/rent`, `POST /scooters/999/return`|`404` dla obu operacji|`404` dla obu; `test_rent_and_return_missing_scooter` przeszedł|Nowa aplikacja na test|
|Restart|Uvicorn uruchomiony ręcznie; `POST /scooters` i `GET /scooters/1`; zatrzymanie i ponowne uruchomienie; `GET /scooters/1`|Przed restartem `200` z danymi; po restarcie `404` i pusta lista|Przed restartem `POST` → `201`, `GET /scooters/1` → `200` z danymi; po restarcie `GET /scooters/1` → `404` `Scooter not found`, `GET /scooters` → `200 []` (wykonane ręcznie przez `curl` na uvicornie)|Restart procesu czyści pamięć|

**Wynik testów** (polecenie: `.\.venv\Scripts\python.exe -m pytest -q`): `8 passed` (pytest 8, Python 3.12, Windows, czyste środowisko `.venv` utworzone z `requirements.txt`; polecenie uruchomione w katalogu `lab1`). Pierwsze uruchomienie startowego testu zakończyło się błędem (`1 failed`), bo oczekiwał nazwy `replace-me`; po poprawieniu nazwy na `Scooter Rental Service` i dopisaniu testów domenowych wszystkie przechodzą.

### Eksperyment z restartem (HTTP)

Procedura (bez `--reload` i bez zmian w kodzie podczas eksperymentu):

```powershell
# Terminal 1
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8101

# Terminal 2
Invoke-RestMethod -Method Post http://localhost:8101/scooters -ContentType "application/json" -Body '{"id":1,"name":"Hulajnoga 1","model":"Xiaomi Mi 4 Pro"}'
Invoke-RestMethod http://localhost:8101/scooters/1

# Terminal 1: Ctrl+C, a potem ponowne uruchomienie tego samego polecenia

# Terminal 2
Invoke-RestMethod http://localhost:8101/scooters/1
```

**Rezultat (wykonane, `uvicorn` na porcie 8101, `curl`):**

- przed restartem: `POST /scooters` → `201`, `GET /scooters/1` → `200` `{"id":1,"name":"Hulajnoga 1","model":"Xiaomi Mi 4 Pro","status":"available"}`,
- po restarcie: `GET /scooters/1` → `404` `{"detail":"Scooter not found"}`, `GET /scooters` → `200 []`.

**Dlaczego dane przetrwały między żądaniami, ale nie restart procesu.** Magazyn to słownik `app.state.scooters` tworzony raz przez `create_app()` przy starcie procesu. Wszystkie żądania obsługiwane przez ten sam proces widzą ten sam słownik, więc zapis jest widoczny przy kolejnym odczycie. Dane żyją wyłącznie w pamięci RAM tego procesu - po jego zatrzymaniu pamięć jest zwalniana, a nowy proces wywołuje `create_app()` od zera i dostaje pusty słownik. Nic nie zapisujemy na dysku ani w bazie.

## 5. Porównanie architektur

Rozważany system: flota hulajnóg + płatności za hulajnogi (pozostałe usługi z planu, czyli ubezpieczenia i serwis, działałyby analogicznie).

**Monolit** - jeden proces, jedna baza, wywołania funkcji w obrębie jednego programu:

```
+---------------------------------------------+
|  Jeden proces                               |
|  [ Hulajnogi ] <--wywołanie funkcji--> [ Płatności ] |
|            \                    /           |
|             +--- wspólna baza ---+           |
+---------------------------------------------+
```

**Modularny monolit** - jeden proces, ale moduły z jasnymi granicami i własnymi danymi:

```
+---------------------------------------------+
|  Jeden proces                               |
|  [ Moduł Hulajnogi ] --interfejs--> [ Moduł Płatności ] |
|     (własne tabele)                (własne tabele)    |
|            \                    /           |
|             +--- jedna baza ----+           |
+---------------------------------------------+
```

**Mikrousługi** - osobne procesy, własne dane, komunikacja po HTTP:

```
[ Scooter Rental Service ]  <--- HTTP/JSON --->  [ Payment Service ]
  proces 1, port 8101                             proces 2, inny port
  własne dane: hulajnogi                          własne dane: płatności
```

**1. Dlaczego ta usługa może być mikrousługą i czym różni się od klasy/modułu?** Ma wyraźnie wydzieloną odpowiedzialność (flota i statusy), własne dane i własny publiczny kontrakt HTTP, a inny kod nie sięga do jej danych bezpośrednio. Od klasy czy modułu różni się tym, że jest osobnym procesem: można ją uruchomić, wdrożyć, skalować i zrestartować niezależnie, a komunikacja odbywa się przez sieć, nie przez wywołanie funkcji. Moduł działa w tym samym procesie i uległby awarii razem z resztą programu.

**2. Jak wyglądałby system jako monolit?** Jedna aplikacja z modułami „hulajnogi" i „płatności", wspólną bazą i jedną transakcją: sprawdzenie, czy hulajnoga istnieje, i zapis płatności w jednym wywołaniu, bez sieci pomiędzy.

**3. Co zmieni podział na usługi?**

- _Koszty sieci:_ każde wypożyczenie wymaga wywołania HTTP (opóźnienie, serializacja JSON, timeouty), zamiast taniego wywołania funkcji.
- _Awarie zależności:_ jeśli usługa floty jest niedostępna, usługa płatności nie może utworzyć płatności (patrz zachowanie `503` w sekcji 1); w monolicie awaria jednego modułu zwykle oznacza awarię całości, ale nie ma problemu częściowych awarii.
- _Spójność danych:_ nie ma wspólnej transakcji - dane w dwóch usługach mogą się rozjechać (np. hulajnoga zostanie usunięta, a płatność za nią już istnieje), więc trzeba to świadomie obsłużyć.
- _Zyski:_ niezależne wdrażanie i skalowanie, wyraźny właściciel danych, możliwość pracy zespołów niezależnie.

**4. Którą architekturę wybrałbym dla obecnej skali problemu?** Dla obecnej skali (jedna prosta domena, pamięć w procesie, brak wielu zespołów ani dużego ruchu) wystarczy **modularny monolit**: daje porządek i granice modułów bez kosztów sieci i problemów ze spójnością. Mikrousługi mają sens, gdy pojawi się potrzeba niezależnego skalowania lub wdrażania albo osobnych zespołów. Na potrzeby tego kursu usługa jest jednak od początku budowana jako mikrousługa, by ćwiczyć jej granice i kontrakt HTTP.

## 6. Dokumentacja wykorzystana podczas pracy

|Odnośnik do fragmentu|Rozwiązywany problem|Co zastosowano w kodzie|Jak sprawdzono działanie|
|---|---|---|---|
|[FastAPI: Request Body](https://fastapi.tiangolo.com/tutorial/body/)|Walidacja danych wejściowych przy tworzeniu hulajnogi|Model `ScooterCreate` (Pydantic) z `Field(gt=0)` oraz `min_length`/`max_length`; typ `Literal` dla statusu|Test z błędnymi danymi oczekujący `422` i niezmienionego stanu|
|[FastAPI: Handling Errors](https://fastapi.tiangolo.com/tutorial/handling-errors/)|Zwracanie `404` i `409` z czytelnym komunikatem|`HTTPException(status_code=..., detail=...)` przy braku zasobu, duplikacie i niedozwolonej zmianie statusu|Testy sprawdzające kod i treść `detail` dla 404 i 409|
|[FastAPI: Testing](https://fastapi.tiangolo.com/tutorial/testing/)|Testowanie API bez uruchamiania serwera i z izolowanym stanem|`TestClient` z fixture tworzącą nową aplikację przez `create_app()` w każdym teście|Uruchomienie `pytest -q`; każdy test zaczyna od pustego magazynu|

## 7. Ograniczenia, autorzy i AI

**Ograniczenia:**

- Dane są tylko w pamięci procesu: po restarcie znikają, a kilka instancji usługi (np. kilka procesów) ma osobne, niezależne magazyny bez wspólnego stanu.
- Identyfikatory nadaje klient i są unikalne tylko w obrębie jednej instancji.
- Status `maintenance` istnieje w modelu, ale brak endpointu, który do niego prowadzi, ani sposobu jego opuszczenia.
- Stacje (miejsca wypożyczenia i zwrotu) nie są jeszcze modelowane - usługa śledzi tylko status hulajnogi, nie to, na której stacji stoi.
- Brak usuwania i edycji hulajnóg, brak paginacji listy, brak uwierzytelniania.
- Brak obsługi współbieżności: operacje wypożyczenia nie są chronione blokadą, co przy jednym procesie i synchronicznych endpointach FastAPI jest w praktyce mało istotne, ale nie byłoby bezpieczne przy bazie i wielu instancjach.
- Brak historii wypożyczeń - za to ma odpowiadać druga usługa.

**Autorzy i wkład:**
- **[Oscar Borowiec]** - model danych i walidacja (`ScooterCreate`, `Scooter`), endpointy `GET /health`, `GET /scooters`, `GET /scooters/{id}`, `POST /scooters`, sekcje README 1-3.
- **[Bartłomiej Bogdan]** - logika wypożyczenia i zwrotu (`rent`, `return`, kody `409`), testy pytest, eksperyment z restartem, sekcje README 4 i 6.
- **Wspólnie** - wzajemny przegląd kodu, sekcja 5 (porównanie architektur), sekcja 7, końcowe sprawdzenie instalacji w czystym środowisku. 

**AI:** 
- Narzędzie: Claude (Anthropic).
- Do czego użyto: szkic README, napisanie i uruchomienie testów

 Weryfikacja: uruchomienie `pytest` (8 testów), ręczny eksperyment z restartem na `uvicorn`, przeczytanie i zrozumienie całego kodu przez obu autorów.



