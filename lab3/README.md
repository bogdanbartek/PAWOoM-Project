# Scooter Rental System — LAB3

System dwóch mikroserwisów FastAPI dla wypożyczalni hulajnóg elektrycznych:

- **Scooter Rental Service** (`scooter-service/`, nazwa w Eurece `SCOOTER-SERVICE`, port 8101) — flota hulajnóg, SQLite i cache Redis z LAB2,
- **Payment Service** (`payment-service/`, nazwa w Eurece `PAYMENT-SERVICE`, port 8102) — płatności za hulajnogi, nowa usługa w LAB3,
- **Eureka Server** (`eureka-server/` + `compose.yaml`, port 8761) — rejestr usług z pakietu pomocniczego LAB3.

Payment Service odnajduje Scooter Rental Service w Eurece po nazwie logicznej i wywołuje `GET /scooters/{id}`. Pełna instrukcja uruchomienia jest w sekcji 14.

```
lab3/
├── compose.yaml            # tylko Eureka Server
├── eureka-server/          # Spring Cloud Netflix Eureka (z pakietu LAB3)
├── scooter-service/        # usługa z LAB2 + rejestracja w Eurece
│   ├── app/ (main.py, eureka.py, repository.py, cache.py, ...)
│   └── tests/
└── payment-service/        # nowa usługa LAB3
    ├── app/ (main.py, eureka.py, models.py)
    └── tests/
```

> Sekcje 1–7 to dokumentacja LAB1, sekcje 8–12 dokumentacja LAB2, zachowane bez zmian merytorycznych. Polecenia z tych sekcji dotyczą teraz katalogu `lab3/scooter-service` (zamiast `lab2`), a testy usługi floty to od LAB3 23 testy (19 z LAB1/LAB2 + 4 nowe). Opis LAB3 zaczyna się w sekcji 13.

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

---

# LAB2 — baza SQLite i cache Redis

Sekcje 1–7 powyżej to dokumentacja z LAB1, zostawiona bez zmian. Poniżej opisuję, co zmieniło się w LAB2. Kontrakt API (ścieżki, kody, kształt JSON) z sekcji 3 nadal obowiązuje. Nowe są tylko nagłówek `X-Cache` przy `GET /scooters/{id}` i opcjonalny endpoint `/ready`.

## 8. Zmiany i decyzje

- **Co zachowano z LAB1:** temat (flota hulajnóg), fabrykę `create_app()`, modele Pydantic `ScooterCreate` i `Scooter`, wszystkie endpointy i ich kody, regułę biznesową (`rent` tylko z `available`, `return` tylko z `rented`), komunikaty `detail` i wszystkie testy LAB1 z niezmienionymi asercjami (`tests/test_lab1_api.py`).
- **Co zmieniono i dlaczego:** słownik `app.state.scooters` zastąpiła tabela `scooters` w SQLite. Wcześniej dane znikały przy restarcie procesu (eksperyment z sekcji 4). Szczegóły hulajnogi (`GET /scooters/{id}`) są teraz cache'owane w Redis według wzorca cache-aside. Kod podzielono na moduły:

  | Plik | Rola |
  |---|---|
  | `app/main.py` | `create_app(database_url=None, redis_client=None)`, `lifespan`, endpointy, mapowanie wyjątków na HTTP |
  | `app/models.py` | modele Pydantic z LAB1 (`from_attributes=True` w `Scooter`) |
  | `app/db_models.py` | model ORM `ScooterRow` (tabela `scooters`) |
  | `app/database.py` | `Base`, `make_database()`: silnik i fabryka sesji, `PRAGMA foreign_keys=ON` (z pakietu LAB2) |
  | `app/repository.py` | `ScooterRepository`: jedna sesja na operację, reguła, commit i rollback |
  | `app/cache.py` | `JsonCache` i `make_redis()`: krótkie timeouty, brak ponowień (z pakietu LAB2) |

- **Właściciel danych i granice drugiej usługi:** tabelę `scooters` zapisuje tylko ta usługa i tylko przez `ScooterRepository`. Planowana druga usługa (Payment Service, sekcja 1) **nie** dostaje dostępu do tej bazy ani do kluczy Redis. Trzyma u siebie tylko `scooter_id` i pyta o hulajnogę przez `GET /scooters/{id}`.

### Tabela decyzji

| Pytanie | Odpowiedź i uzasadnienie |
|---|---|
| Jakie dane muszą przetrwać restart? | Rejestr hulajnóg (`id`, `name`, `model`) i **aktualny status**. Gdyby status znikał po restarcie, wypożyczona hulajnoga wróciłaby jako `available` i ktoś mógłby wypożyczyć ją drugi raz. |
| Jakie tabele i powiązania są potrzebne? | Jedna tabela `scooters`. Na tym etapie nie ma innych encji w tej usłudze, więc nie ma kluczy obcych. `PRAGMA foreign_keys=ON` jest włączone na przyszłość, np. dla tabeli stacji. |
| Która usługa może je zapisywać? | Tylko Scooter Rental Service, przez `ScooterRepository`. |
| Których danych drugiej usługi tu nie zapisujemy? | Płatności (`amount`, status płatności, kto płacił), danych klientów, historii wypożyczeń. Nie przechowujemy też kopii danych z innych usług. |
| Co chroni baza, a co reguła biznesowa? | **Baza:** unikalność `id` (klucz główny), `id > 0` i dozwolone wartości statusu (`CHECK status IN ('available','rented','maintenance')`), pola `NOT NULL`. **Reguła w repozytorium:** dozwolone *przejścia* między statusami (`available → rented`, `rented → available`). Bazie wystarczy, że status jest poprawną wartością. Czy dana zmiana ma sens, ocenia kod. |
| Jaki odczyt cache'ujemy i jak długo może być nieaktualny? | `GET /scooters/{id}`. To odczyt, o który będzie pytać druga usługa (Payment Service) i klient przed wypożyczeniem. Przy sprawnym Redis odpowiedź jest zawsze aktualna, bo każda zmiana statusu usuwa kopię po commicie. Nieaktualna może być tylko po **nieudanym** unieważnieniu, najdłużej do końca TTL (60 s). Lista `GET /scooters` nie jest cache'owana, bo unieważnianie listy przy każdej zmianie jest trudniejsze, a zysk mały. |
| Jaki prefiks, klucz, TTL i sposób unieważnienia? | Prefiks `CACHE_PREFIX=lab2:131409:scooter-service` (numer albumu). Klucz `<prefiks>:scooter:<id>`, np. `lab2:131409:scooter-service:scooter:1`. TTL 60 s (`CACHE_TTL_SECONDS`). Unieważnianie: `cache.delete(id)` **po commicie** w `rent` i `return`. `POST /scooters` nie unieważnia, bo nowej hulajnogi nie było w cache (404 nie jest cache'owane). |

### Reguła biznesowa w bazie

Kolejność w `ScooterRepository._change_status` jest taka: **odczyt stanu → sprawdzenie reguły → zmiana → commit**. Wszystko dzieje się w jednym bloku `with sessions.begin()`. Jeśli reguła rzuci `ScooterStateError`, blok kończy się wyjątkiem i SQLAlchemy robi rollback. Cache nie jest wtedy ruszany.

| Operacja | Stan początkowy | Wynik | Stan po operacji |
|---|---|---|---|
| `POST /scooters/1/rent` (dozwolona) | `available` | `200`, `status: rented` | baza: `rented`, kopia w cache usunięta |
| `POST /scooters/1/rent` (odrzucona) | `rented` | `409 {"detail": "Scooter is not available for rental"}` | baza: nadal `rented`, cache bez zmian |
| `POST /scooters` z istniejącym `id` | hulajnoga `id=1` istnieje | `409 {"detail": "Scooter with this ID already exists"}` | oryginalny rekord bez zmian |

Duplikat jest wykrywany przed zapisem (`db.get`). Gdyby dwa żądania przeszły to sprawdzenie jednocześnie, klucz główny w bazie odrzuci drugie, a `IntegrityError` zostanie zamieniony na `409`. Na 409 mapujemy wyłącznie `IntegrityError`. Inne błędy bazy nie są ukrywane pod tym kodem.

### Cache-aside: `GET /scooters/{id}`

1. `cache.get(id)`: przy trafieniu odpowiedź z cache i `X-Cache: HIT`. Repozytorium nie jest wtedy wywoływane.
2. Przy chybieniu (`MISS`) odczyt z repozytorium. Brak rekordu daje `404`, którego nie zapisujemy w cache. Rekord jest zapisywany jako `Scooter.model_dump(mode="json")` z TTL. Nie zapisujemy obiektu ORM ani sesji.
3. Gdy Redis jest niedostępny przy GET albo SET, odpowiedź pochodzi z bazy z nagłówkiem `X-Cache: BYPASS`.

Wartości nagłówka `X-Cache`: `HIT`, `MISS`, `BYPASS`.

### Rozszerzenie: `GET /ready`

`/health` z LAB1 zostaje bez zmian (proces żyje). `/ready` sprawdza zależności: `SELECT 1` w bazie i `PING` w Redis.

| Baza | Redis | Kod | Treść |
|---|---|---|---|
| działa | działa | 200 | `{"status": "ok", ..., "database": "up", "cache": "up"}` |
| działa | nie działa | 200 | `{"status": "degraded", ..., "cache": "down"}` |
| nie działa | dowolnie | 503 | `{"status": "error", ..., "database": "down"}` |

## 9. Uruchomienie (LAB2)

**Wymagania:** Python 3.12+ (sprawdzone na 3.14), PowerShell. Redis 7 jest potrzebny tylko do ręcznych prób cache. Testy automatyczne go nie wymagają, a aplikacja bez Redisa działa w trybie `BYPASS`.

**Konfiguracja (zmienne środowiskowe):**

| Zmienna | Wartość domyślna | Znaczenie |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./app.db` | plik bazy, względem katalogu, z którego uruchamiany jest Uvicorn (tu: `lab2/app.db`) |
| `REDIS_URL` | `redis://localhost:6379/0` | adres Redis |
| `CACHE_PREFIX` | **brak, wymagana** | prefiks kluczy; bez niej aplikacja nie wystartuje (`RuntimeError`) |
| `CACHE_TTL_SECONDS` | `60` | czas życia kopii w cache |

Schemat tworzy `Base.metadata.create_all(engine)` w `lifespan` przy każdym starcie. Tworzy tylko brakujące tabele, nie kasuje danych i nie zmienia istniejących kolumn. Zmiana kolumn wymagałaby migracji, np. Alembic. Plik `*.db` jest w `.gitignore`.

```powershell
cd lab2
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q

# Redis lokalnie (Docker); przy kolejnym uruchomieniu: docker start lab2-redis
docker run --name lab2-redis -p 127.0.0.1:6379:6379 -d redis:7-alpine

$env:DATABASE_URL = 'sqlite:///./app.db'
$env:REDIS_URL = 'redis://localhost:6379/0'
$env:CACHE_PREFIX = 'lab2:131409:scooter-service'
$env:CACHE_TTL_SECONDS = '60'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8101
```

Sprawdzenie: `curl.exe -i http://localhost:8101/scooters/1` (nagłówek `x-cache`), `curl.exe -i http://localhost:8101/ready`.

W PowerShell 5.1 ciało JSON najłatwiej podać z pliku. Zapis w wierszu poleceń psuje się na cudzysłowach:

```powershell
'{"id":1,"name":"Hulajnoga 1","model":"Xiaomi Mi 4 Pro"}' | Out-File -Encoding ascii body.json
curl.exe -i -X POST http://localhost:8101/scooters -H "Content-Type: application/json" --data-binary "@body.json"
```

**Reset danych:** zatrzymaj Uvicorna i usuń `lab2/app.db`. W Redis usuń **tylko własny klucz**: `docker exec lab2-redis redis-cli DEL lab2:131409:scooter-service:scooter:1`. Nie używaj `FLUSHALL` ani `FLUSHDB`.

## 10. Dowody

### Testy automatyczne

Polecenie: `.\.venv\Scripts\python.exe -m pytest -q` w katalogu `lab2`. Wynik: **`19 passed, 1 warning`** (Python 3.14, Windows). Jedyne ostrzeżenie (`DeprecationWarning` o `anyio.abc.BlockingPortal`) pochodzi z biblioteki Starlette (`testclient.py`), a nie z naszego kodu.

Fixture w `tests/conftest.py` daje każdemu testowi świeżą bazę `sqlite:///<tmp_path>/test.db`, pusty zamiennik `MemoryRedis` i ustawia `CACHE_PREFIX` przez `monkeypatch`. Aplikacja powstaje przez `create_app(database_url=..., redis_client=...)` w `TestClient`, więc `lifespan` działa jak w prawdziwym uruchomieniu.

| Plik | Testy |
|---|---|
| `tests/test_lab1_api.py` | 8 testów LAB1 (health, lista/szczegóły, zapis→odczyt, 404, 422 bez zmiany stanu, 409 duplikat, reguła rent/return, 404 dla rent/return). Asercje bez zmian, teraz na bazie SQLite. |
| `tests/test_lab2_storage_cache.py` | 4 wymagane testy LAB2 i 7 dodatkowych, opisane niżej |

**Cztery wymagane testy LAB2:**

| Test | Co wykazuje |
|---|---|
| `test_data_survives_new_app_instance_with_empty_cache` | **Trwałość:** zapis i `rent`, zamknięcie aplikacji (koniec `lifespan`), nowa instancja z tą samą bazą i **nowym pustym `MemoryRedis`**. `GET` zwraca `rented` z `X-Cache: MISS`, czyli z bazy. |
| `test_miss_then_hit_does_not_touch_repository` | **HIT/MISS:** pierwszy odczyt `MISS` (kopia zapisana z TTL = 60), drugi `HIT`. Licznik (`monkeypatch` na `repository.get`) pokazuje jedno wywołanie repozytorium. |
| `test_rent_and_return_invalidate_cache` | **Unieważnienie:** cache wypełniony, `rent` usuwa klucz, kolejny `GET` to `MISS` z nowym statusem `rented`, potem `HIT`. To samo dla `return`. |
| `test_cache_outage_bypasses_and_still_commits` | **Awaria cache:** `client.down = True`. `GET` zwraca 200 z `BYPASS`, `rent` zwraca 200, a zmiana jest zatwierdzona w bazie. |

**Testy dodatkowe:** nieudany `SET` daje `BYPASS` z danymi z bazy. Nieudane unieważnienie zostawia starą wartość (`HIT` ze starym statusem, w bazie nowy). Odrzucony `rent` (409) nie zmienia bazy ani kopii w cache. `404` nie trafia do cache. Uszkodzony wpis w cache powoduje odczyt z bazy (`MISS`). Brak `CACHE_PREFIX` blokuje start. `/ready` zwraca `degraded` przy awarii Redis.

Zamiennik `MemoryRedis` **nie symuluje upływu TTL**, dlatego wygaśnięcie sprawdza się ręcznie na prawdziwym Redis.

### Próby ręczne przez HTTP (prawdziwy Uvicorn, port 8101)

| Scenariusz | Stan początkowy i żądanie | Oczekiwany wynik | Wynik rzeczywisty | Reset |
|---|---|---|---|---|
| Zapis i odczyt po restarcie bez cache | Pusta baza, Redis niedostępny. `POST /scooters` (`id=1`), `POST /scooters/1/rent`, zatrzymanie Uvicorna, ponowny start, `GET /scooters/1`, `GET /scooters` | Po restarcie `200` i `status: rented` | `POST` → `201`, `rent` → `200 rented`. Po restarcie `GET /scooters/1` → `200 {"id":1,...,"status":"rented"}`, `x-cache: BYPASS`; `GET /scooters` → lista z tą hulajnogą. **Dane przetrwały restart** (w LAB1 po restarcie było `404`). | usunięcie `app.db` |
| Reguła: sukces i odrzucenie bez zmiany | Hulajnoga `id=1` ze statusem `available`. `rent`, drugi `rent`, ponowny duplikat `POST` | `200`, potem `409` i status bez zmian; duplikat `409` | `rent` → `200 rented`; drugi `rent` → `409 {"detail":"Scooter is not available for rental"}`; `GET` nadal `rented`; duplikat `POST` → `409 {"detail":"Scooter with this ID already exists"}` | usunięcie `app.db` |
| Awaria GET, SET, DELETE cache | Redis niedostępny (brak serwera na `localhost:6379`). `GET /scooters/1`, `rent`, `/ready` | `GET` 200 z `BYPASS`, zapis działa, `/ready` → `degraded` | `GET` → `200`, `x-cache: BYPASS`; `rent` → `200` i zmiana widoczna w bazie; `/ready` → `200 {"status":"degraded",...,"cache":"down"}`. Odpowiedzi przychodzą od razu dzięki timeoutowi 0,3 s i braku ponowień. | brak |
| Brak `CACHE_PREFIX` | Zmienna usunięta, start Uvicorna | Start przerwany | Proces kończy się z `RuntimeError: CACHE_PREFIX environment variable must be set before start` | ustawienie zmiennej |
| MISS → HIT | Redis 7 (`redis:7-alpine` w Dockerze), pusta baza. `POST /scooters` (`id=1`), dwa razy `GET /scooters/1`, `redis-cli TTL`/`GET` klucza | pierwszy `GET` `MISS`, drugi `HIT`; `TTL` ≤ 60 | `POST` → `201`; `EXISTS` przed odczytem → `0`. Pierwszy `GET` → `200`, `x-cache: MISS`; `TTL` → `60`, w Redis JSON `{"id": 1, ..., "status": "available"}`. Drugi `GET` → `200`, `x-cache: HIT`, ta sama treść. Klucz to `lab2:131409:scooter-service:scooter:1` (jedyny klucz z naszym prefiksem). | `DEL` własnego klucza |
| Wygaśnięcie TTL | Kopia w cache (`TTL` → `55`), odczekanie 62 s | po > 60 s `GET` znowu `MISS` (`redis-cli TTL` → `-2`) | Po 62 s `TTL` → `-2` (klucz wygasł); `GET` → `x-cache: MISS` z danymi z bazy, nowa kopia z `TTL` → `60` | — |
| Zmiana i unieważnienie | Kopia `available` w cache (`HIT`). `rent`, `GET`, `GET`, `return`, `GET` | po `rent` `EXISTS` → `0`, `GET` → `MISS` z `rented`, potem `HIT` | `rent` → `200 rented`; `EXISTS` → `0`; `GET` → `MISS` `rented`; kolejny `GET` → `HIT` `rented`. `return` → `200 available`, `EXISTS` → `0`, `GET` → `MISS` `available`. | `DEL` własnego klucza |
| Awaria Redis w trakcie pracy, `/ready` | Kopia w cache, `docker pause lab2-redis`. `rent`, `GET`, `/ready` | zapis działa, `GET` z `BYPASS`, `/ready` → `degraded` | `rent` → `200 rented` w ok. 0,5 s (timeouty 0,3 s), commit w bazie; `GET` → `200`, `x-cache: BYPASS`, `rented`; `/ready` → `200 {"status":"degraded",...,"cache":"down"}`. Po `docker unpause` `/ready` → `{"status":"ok",...,"cache":"up"}`. | `docker unpause lab2-redis` |
| Przywrócenie Redis, możliwa stara wartość | Kopia `available` (`TTL` 60), `docker stop lab2-redis`, `rent` (commit OK, `DELETE` nieudany), `docker start lab2-redis` | `GET` → `HIT` ze **starym** statusem, po TTL → `MISS` z aktualnym | Po starcie Redis klucz wrócił z dysku (`TTL` → `55`). `GET` → `x-cache: HIT` `{"status":"available"}`, a w bazie `SELECT id, status FROM scooters` → `(1, 'rented')`: **stara wartość**. Po wygaśnięciu (`TTL` → `-2`) `GET` → `MISS` `{"status":"rented"}`. | `DEL` własnego klucza |
| Restart aplikacji przy działającym Redis | Hulajnoga `rented` w bazie. Zatrzymanie Uvicorna, `DEL` klucza, ponowny start | dane z bazy, `MISS`, potem `HIT` | `GET /scooters/1` → `MISS` `rented`, kolejny → `HIT`; `GET /scooters` → lista z hulajnogą; `/ready` → `ok` | usunięcie `app.db`, `DEL` klucza |

**Obserwacja przy próbie ze starą wartością.** Najpierw zasymulowaliśmy awarię przez `docker pause lab2-redis`. Wtedy stara wartość **nie** została: `rent` trwał ok. 0,5 s (timeout), ale zamrożony Redis miał już komendę `DEL` w buforze TCP i wykonał ją po `docker unpause`. Kolejny `GET` dał `MISS` z poprawnym `rented`. Wniosek: timeout po stronie klienta nie oznacza, że operacja nie została wykonana. Dopiero `docker stop` (zerwane połączenie, a klucz odtworzony z pliku RDB przy starcie) pokazał scenariusz ze starą wartością do końca TTL.

Wszystkie próby wykonano 2026-11-09 na Windows 11, Python 3.14, Redis 7 (`redis:7-alpine`) w Docker Desktop, Uvicorn na porcie 8101, `CACHE_PREFIX=lab2:131409:scooter-service`. Używaliśmy tylko własnego klucza (`DEL`), bez `FLUSHALL`/`FLUSHDB`.

## 11. Porównanie i ograniczenia

**Co zmieniło się dla klienta API, a co wewnątrz usługi?** Dla klienta prawie nic: te same ścieżki, kody i JSON. Doszedł nagłówek `X-Cache` i `/ready`. Najważniejsza różnica jest taka, że dane nie znikają po restarcie. Wewnątrz usługi słownik w pamięci zastąpiły SQLite i repozytorium z transakcjami, a odczyt szczegółów przechodzi przez cache.

**Dlaczego baza i cache nie zmieniają automatycznie aplikacji w system mikroserwisowy?** Nadal jest jeden proces z jedną odpowiedzialnością. Baza i Redis to szczegóły implementacji tej usługi. System mikroserwisowy powstanie dopiero wtedy, gdy obok będzie działać druga niezależna usługa z własnymi danymi, komunikująca się przez HTTP (LAB3).

**Czy druga usługa powinna pisać do tych samych tabel?** Nie. Gdyby Payment Service zmieniał `scooters.status` bezpośrednio, ominąłby regułę z repozytorium i unieważnianie cache. W Redis zostałaby stara kopia, a reguła „nie wypożyczysz zajętej hulajnogi” przestałaby być pilnowana w jednym miejscu. Druga usługa korzysta wyłącznie z API.

**Jakie skutki ma awaria procesu aplikacji, Redis i bazy?**
- *Proces aplikacji:* usługa nie odpowiada, ale dane w SQLite zostają. Po restarcie działa dalej (pierwszy odczyt `MISS`).
- *Redis:* usługa działa w trybie `BYPASS`, czyta i zapisuje bezpośrednio w bazie, tylko wolniej. Nieudane unieważnienie może zostawić starą kopię do końca TTL.
- *Baza:* usługa nie może bezpiecznie odpowiadać. `/ready` zwraca `503`. Cache nie zastępuje bazy, bo przechowuje tylko część danych i wygasa.

**Jakie opóźnienie aktualizacji dopuszcza odbiorca?** Status hulajnogi decyduje o tym, czy klient może ją wypożyczyć. Nieaktualny status `available` przy faktycznym `rented` skończyłby się dla klienta komunikatem `409` przy próbie wypożyczenia. Reguła jest sprawdzana na bazie, nie na cache, więc podwójnego wypożyczenia nie będzie, ale klient dostałby mylącą informację. Dlatego TTL jest krótki (60 s), a unieważnianie odbywa się po każdej zmianie. Opis hulajnogi (`name`, `model`) mógłby mieć dłuższy TTL.

**Co wymaga sprawdzenia przy zmianie SQLite na PostgreSQL?** Adres `DATABASE_URL` i sterownik (`psycopg`). Opcję `check_same_thread`, która dotyczy tylko SQLite (`make_database` ustawia ją tylko dla `sqlite`). Zachowanie `CHECK`, `PRAGMA foreign_keys`, która jest specyficzna dla SQLite (PostgreSQL zawsze sprawdza klucze obce). Pulę połączeń, poziom izolacji transakcji i blokady przy współbieżnym `rent` (np. `SELECT ... FOR UPDATE`). Migracje schematu zamiast `create_all`.

**Analiza z części A w odniesieniu do własnej domeny:**
- *Dlaczego dane przetrwały nowy proces?* Są w pliku `app.db` na dysku, a nie w pamięci procesu. Nowy proces otwiera ten sam plik.
- *Co pokazuje HIT, a czego nie dowodzi?* Pokazuje, że odpowiedź pochodziła z Redisa, a repozytorium nie zostało wywołane (test z licznikiem). Nie dowodzi, że odpowiedź jest szybsza. Przy lokalnym SQLite i jednym rekordzie różnica może być pomijalna albo odwrotna, bo dochodzi narzut sieci do Redisa.
- *Dlaczego błąd zapisu nie powinien zatwierdzić części danych?* Częściowy zapis zostawiłby niespójny stan, np. hulajnogę w statusie niepasującym do reguły. Transakcja (`sessions.begin()`) zatwierdza wszystko albo nic.
- *Dlaczego obsługujemy awarię GET, SET i DELETE?* Każda z tych operacji może trafić na niedziałający Redis. Cache jest opcjonalny, więc żadna jego awaria nie może zamienić się w błąd 500 ani cofnąć commitu w bazie.
- *Co grozi po nieudanym unieważnieniu?* Stara kopia (np. `available` po `rent`) zostaje w Redis do końca TTL i klienci ją widzą. Pokazuje to test `test_failed_invalidation_can_leave_stale_value_until_ttl`.

**Ograniczenia:**
- **Nieudane unieważnienie:** po awarii Redisa w chwili `DELETE` stara wartość może być zwracana do 60 s.
- **Współbieżność:** cache-aside nie gwarantuje ścisłej spójności. Żądanie A może odczytać stary rekord (MISS), żądanie B zmienić status i usunąć klucz, a A dopiero potem zapisać starą wartość do cache. Wypożyczenie też nie jest atomowe przy wielu instancjach: dwa równoległe `rent` mogą oba odczytać `available`. Przy jednym procesie i SQLite ryzyko jest małe. W PostgreSQL rozwiązałaby to blokada wiersza albo warunkowy `UPDATE ... WHERE status = 'available'`.
- **Zmiany schematu:** `create_all` nie migruje istniejących kolumn. Zmiana modelu wymaga usunięcia lokalnej bazy albo migracji (Alembic).
- **Zakres:** lista `GET /scooters` nie jest cache'owana. Wciąż nie ma operacji ustawiającej `maintenance`, usuwania ani edycji hulajnóg.

**Czy cache jest właściwy dla odbiorcy?** Dla odczytu szczegółów hulajnogi tak, w ograniczonym zakresie: odczyt jest częsty (klient przed wypożyczeniem, w przyszłości Payment Service), a reguła i tak jest sprawdzana na bazie, więc nieaktualny cache nie pozwoli wypożyczyć zajętej hulajnogi. Przy obecnej skali (SQLite, jeden proces) cache nie jest potrzebny wydajnościowo. Stosujemy go, żeby przećwiczyć mechanizm i jego ograniczenia.

## 12. Dokumentacja LAB2 i autorzy

| Źródło | Problem | Zastosowanie | Weryfikacja |
|---|---|---|---|
| [SQLAlchemy 2.0: Session Basics – Framing out a begin / commit / rollback block](https://docs.sqlalchemy.org/en/20/orm/session_basics.html#framing-out-a-begin-commit-rollback-block) | Jak zapewnić, że odrzucona operacja (409) nie zostawi częściowej zmiany i że sesja zostanie zamknięta | `with self.sessions.begin() as db:` w `ScooterRepository`: commit przy normalnym wyjściu, rollback przy wyjątku, zamknięcie sesji w obu przypadkach. Jedna sesja na operację. | `test_rejected_rent_rolls_back_and_keeps_cache` i `test_duplicate_id_conflict_keeps_original`: po 409 baza bez zmian |
| [redis-py: Retry Helpers / Connection](https://redis.readthedocs.io/en/stable/retry.html) i [`Redis.from_url`](https://redis.readthedocs.io/en/stable/connections.html) | Przy niedziałającym Redisie każde żądanie wisiało na domyślnych ponowieniach połączenia | `make_redis()`: `socket_connect_timeout=0.3`, `socket_timeout=0.3`, `retry=Retry(NoBackoff(), 0)`, `decode_responses=True` | Próba ręczna bez Redisa: `GET` od razu zwraca `200` z `x-cache: BYPASS`, `/ready` → `degraded` |
| [FastAPI: Lifespan Events](https://fastapi.tiangolo.com/advanced/events/) | Gdzie tworzyć silnik bazy i klienta Redis raz na aplikację i jak je zamknąć | `lifespan` w `create_app()`: tworzy `engine`, `repository`, `cache`, zapisuje je w `app.state`, po `yield` wywołuje `client.close()` i `engine.dispose()` | Testy uruchamiają `TestClient` jako context manager. `test_data_survives_new_app_instance_with_empty_cache` zamyka pierwszą instancję i otwiera drugą na tym samym pliku bazy. |

**Autorzy i wkład (LAB2):**
- **Oscar Borowiec (nr albumu 131409):** warstwa bazy danych: model ORM `ScooterRow` z ograniczeniami `CHECK`/`NOT NULL` (`db_models.py`), `make_database()` (`database.py`), `ScooterRepository` z transakcjami i regułą przejść statusów (`repository.py`), mapowanie `IntegrityError` na `409`, przeniesienie testów LAB1 na SQLite (`conftest.py`, `test_lab1_api.py`), testy trwałości i rollbacku (`test_data_survives_new_app_instance_with_empty_cache`, `test_rejected_rent_rolls_back_and_keeps_cache`, `test_duplicate_id_conflict_keeps_original`), próby ręczne trwałości po restarcie i reguły 409. README: sekcja 8 (zmiany, tabela decyzji, reguła w bazie) i część sekcji 11 (PostgreSQL, granice drugiej usługi).
- **Bartłomiej Bogdan (nr albumu 131407):** warstwa cache: `JsonCache` i `make_redis()` z timeoutami (`cache.py`), cache-aside w `GET /scooters/{id}` z nagłówkiem `X-Cache`, unieważnianie po commicie w `rent`/`return`, endpoint `/ready`, zamiennik `MemoryRedis` i testy cache (`test_miss_then_hit_does_not_touch_repository`, `test_rent_and_return_invalidate_cache`, `test_cache_outage_bypasses_and_still_commits` i testy awarii SET/DELETE), próby ręczne z prawdziwym Redisem w Dockerze (MISS/HIT, TTL, unieważnienie, stara wartość). README: sekcje 9 i 10.
- **Wspólnie:** `lifespan` i `create_app(database_url, redis_client)` w `main.py`, wzajemny przegląd kodu, sekcja 11 (porównanie, skutki awarii, ograniczenia), sekcja 12 (źródła dokumentacji), końcowe uruchomienie testów i prób w czystym środowisku.

**AI:**
- Narzędzie: Claude (Anthropic), Claude Code.
- Zakres: przeniesienie magazynu na SQLAlchemy (`db_models.py`, `repository.py`), integracja `JsonCache` z endpointami, testy LAB2, szkic README LAB2, pomoc przy wykonaniu i opisaniu prób ręcznych z Redisem.
- Weryfikacja: `pytest -q` (19 testów), ręczne uruchomienie Uvicorna z prawdziwym Redisem (Docker) i sprawdzenie przez `curl` i `redis-cli` (trwałość po restarcie, 409 bez zmiany stanu, MISS/HIT, TTL, unieważnienie, BYPASS, stara wartość po nieudanym `DELETE`), przeczytanie i zrozumienie kodu przez obu autorów.

**Kolejny etap (LAB3):** pierwsza usługa zostaje bez zmian w zakresie danych. Powstaje druga usługa, Payment Service, z własnym magazynem płatności. Przy tworzeniu płatności pyta o hulajnogę przez `GET /scooters/{id}` (odnajdywaną przez Eurekę po nazwie logicznej) i nie zapisuje danych hulajnogi u siebie.

---

# LAB3 — rejestracja i odnajdywanie usług (Eureka)

Sekcje 1–12 opisują LAB1 i LAB2. W LAB3 usługa floty zachowuje swoje API, bazę SQLite i cache Redis bez zmian. Dochodzi do niej rejestracja w Eurece. Powstaje też druga, niezależna usługa: Payment Service.

## 13. Usługi i granice odpowiedzialności

| Usługa | Odpowiedzialność | Właściciel danych | Nazwa w Eurece | Port |
|---|---|---|---|---:|
| Scooter Rental Service (`scooter-service/`) | Rejestr hulajnóg, ich status, reguła wypożyczenia i zwrotu (LAB1), trwałość i cache (LAB2) | Tabela `scooters` w SQLite (`app.db`) i klucze Redis `lab3:131409:scooter-service:*` | `SCOOTER-SERVICE` | 8101 |
| Payment Service (`payment-service/`) | Rejestrowanie płatności za hulajnogi i ich statusu (`pending` → `paid`) | Płatności `id`, `scooter_id`, `amount`, `status`, przechowywane w pamięci procesu | `PAYMENT-SERVICE` | 8102 |
| Eureka Server (`eureka-server/`) | Rejestr instancji: nazwa logiczna → adres i port. Nie przekazuje danych domenowych. | Wpisy rejestru (nie dane biznesowe) | — | 8761 |

**Granice:**
- Payment Service **nie** ma dostępu do bazy ani do Redisa usługi floty. Trzyma tylko odniesienie `scooter_id`, a dane hulajnogi czyta wyłącznie przez `GET /scooters/{id}`. Nie zapisuje ich kopii.
- Payment Service **nie** zmienia statusu hulajnogi. `rent` i `return` zostają w usłudze floty, więc reguła „nie wypożyczysz zajętej hulajnogi” jest pilnowana w jednym miejscu.
- Payment Service przechowuje płatności w pamięci procesu. Na LAB3 to wystarcza: instrukcja dopuszcza mały zbiór danych w pamięci. Po restarcie płatności znikają (sekcja 17). Trwałość można dodać później, tak jak w LAB2.
- Sprawdzenie, czy hulajnoga istnieje, jest zdalnym odczytem. Nie jest rezerwacją: między odczytem a zapisem płatności stan hulajnogi może się zmienić.

**Endpointy Payment Service:**

| Metoda i ścieżka | Opis | Kody |
|---|---|---|
| `GET /health` | Proces żyje (nie sprawdza zależności) | 200 |
| `GET /payments` | Lista płatności | 200 |
| `GET /payments/{id}` | Szczegóły płatności (tylko własne dane, bez wywołania zależności) | 200, 404 |
| `POST /payments` | Utworzenie płatności `{"id", "scooter_id", "amount"}`. **Wywołuje `SCOOTER-SERVICE`.** | 201, 404, 409, 422, 502, 503 |
| `POST /payments/{id}/pay` | Opłacenie: tylko z `pending` do `paid` | 200, 404, 409 |
| `GET /payments/{id}/details` | Płatność razem z **aktualnymi** danymi hulajnogi. **Wywołuje `SCOOTER-SERVICE`.** | 200, 404, 502, 503 |

Reguła biznesowa Payment Service: płatność powstaje tylko dla hulajnogi, której istnienie potwierdziła usługa floty. Płatność można opłacić tylko raz (drugi `pay` daje `409 {"detail": "Payment is already paid"}`). Walidacja: `id > 0`, `scooter_id > 0`, `0 < amount ≤ 10000`. Błędne dane dają `422` bez wywołania zależności.

## 14. Konfiguracja i uruchomienie (LAB3)

- **Wersje:** Windows 11, Python 3.14.0, FastAPI 0.162.2, Starlette 0.47.3, Uvicorn 0.54.0, Pydantic 2.14.3, httpx 0.28.1, pytest 8.4.2, `py-eureka-client==0.13.3`, SQLAlchemy 2.0.57, redis-py 6.4.0 (usługa floty), Redis 7 (`redis:7-alpine`), Docker Desktop (Docker 29.9.3). Eureka Server: Spring Boot 4.1.1, Spring Cloud 2025.1.3, Java 21 (obraz `maven:3.9.11-eclipse-temurin-21`).
- **Zależności:** każda usługa ma własny `requirements.txt` i własne `.venv`. Do pliku LAB2 usługi floty dopisano tylko `py-eureka-client==0.13.3`, plik nie został zastąpiony plikiem z demo.
- **Adres Eureka Server:** `EUREKA_SERVER_URL=http://127.0.0.1:8761` (bez `/eureka`). Prefiks ścieżki `eureka_context="/eureka"` jest ustawiony w kodzie (`app/eureka.py`), zgodnie z serwerem Spring Cloud.
- **Rejestr uruchamiany lokalnie przez Docker** (`compose.yaml` zawiera tylko serwis `eureka` z pakietu pomocniczego, port opublikowany na `127.0.0.1:8761`). Panel: <http://localhost:8761/>.
- **Konfiguracja instancji (zmienne środowiskowe):**

  | Zmienna | `SCOOTER-SERVICE` | `PAYMENT-SERVICE` | Znaczenie |
  |---|---|---|---|
  | `EUREKA_SERVER_URL` | `http://127.0.0.1:8761` | `http://127.0.0.1:8761` | adres rejestru |
  | `SERVICE_NAME` | `SCOOTER-SERVICE` | `PAYMENT-SERVICE` | nazwa logiczna (domyślna ustawiona w kodzie) |
  | `SERVICE_PORT` | `8101` | `8102` | port rejestrowany, **musi być równy** `--port` Uvicorna |
  | `INSTANCE_IP` | `127.0.0.1` | `127.0.0.1` | adres osiągalny dla wywołującego (nigdy `0.0.0.0`) |
  | `INSTANCE_HOST` | `localhost` | `localhost` | nazwa hosta tej samej maszyny |
  | `DATABASE_URL`, `REDIS_URL`, `CACHE_PREFIX`, `CACHE_TTL_SECONDS` | jak w LAB2, `CACHE_PREFIX=lab3:131409:scooter-service` | — | zasoby LAB2 |

- **Cykl życia klienta Eureki i zasoby LAB2:** `create_app(database_url=None, redis_client=None, eureka_client=None)` tworzy `EurekaClient` w fabryce, a test może podać zamiennik. Lifespan z LAB2 nazywa się teraz `storage_lifespan`. Nowy `lifespan` go opakowuje: **otwarcie bazy i Redisa → `eureka_client.start()` (rejestracja) → obsługa żądań → `eureka_client.stop()` (wyrejestrowanie) → zamknięcie Redisa i bazy**. Instancja zgłasza się do rejestru dopiero wtedy, gdy ma gotowe zasoby, i wyrejestrowuje się, zanim je zamknie (test `test_eureka_client_started_and_stopped_with_storage`). Payment Service nie ma zasobów LAB2, więc jej lifespan tylko tworzy magazyn w pamięci i uruchamia oraz zatrzymuje klienta.
- `strict_service_error_policy=False`: błąd HTTP zależności dociera do kodu endpointu jako `HTTPError`, więc to my mapujemy go na kod odpowiedzi.

**Uruchomienie** (PowerShell, z katalogu `lab3`; każdy proces w osobnym terminalu, bez `--reload`):

```powershell
# 0. Rejestr i Redis
docker compose up --build -d eureka
docker start lab2-redis      # pierwszy raz: docker run --name lab2-redis -p 127.0.0.1:6379:6379 -d redis:7-alpine

# 1. Terminal 1 - Scooter Rental Service
cd scooter-service
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:EUREKA_SERVER_URL = 'http://127.0.0.1:8761'
$env:SERVICE_NAME = 'SCOOTER-SERVICE'
$env:SERVICE_PORT = '8101'
$env:INSTANCE_IP = '127.0.0.1'
$env:INSTANCE_HOST = 'localhost'
$env:DATABASE_URL = 'sqlite:///./app.db'
$env:REDIS_URL = 'redis://localhost:6379/0'
$env:CACHE_PREFIX = 'lab3:131409:scooter-service'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8101

# 2. Terminal 2 - Payment Service
cd payment-service
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:EUREKA_SERVER_URL = 'http://127.0.0.1:8761'
$env:SERVICE_NAME = 'PAYMENT-SERVICE'
$env:SERVICE_PORT = '8102'
$env:INSTANCE_IP = '127.0.0.1'
$env:INSTANCE_HOST = 'localhost'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8102
```

Po pojawieniu się obu wpisów `UP` w panelu Eureki (do ok. 30 s, bo serwer odświeża swoją listę z opóźnieniem):

```powershell
'{"id":1,"name":"Hulajnoga 1","model":"Xiaomi Mi 4 Pro"}' | Out-File -Encoding ascii scooter.json
curl.exe -i -X POST http://127.0.0.1:8101/scooters -H "Content-Type: application/json" --data-binary "@scooter.json"
'{"id":1,"scooter_id":1,"amount":12.5}' | Out-File -Encoding ascii payment.json
curl.exe -i -X POST http://127.0.0.1:8102/payments -H "Content-Type: application/json" --data-binary "@payment.json"
curl.exe -i http://127.0.0.1:8102/payments/1/details
```

**Testy** (nie wymagają Eureki, Redisa ani sieci):

```powershell
cd scooter-service; .\.venv\Scripts\python.exe -m pytest -q    # 23 passed
cd ..\payment-service; .\.venv\Scripts\python.exe -m pytest -q # 14 passed
```

**Zatrzymanie i reset:** `Ctrl+C` w obu terminalach (poprawne wyrejestrowanie), `docker compose down` (rejestr), `docker stop lab2-redis`. Reset danych: usunięcie `scooter-service/app.db` i własnego klucza `docker exec lab2-redis redis-cli DEL lab3:131409:scooter-service:scooter:1`. Płatności znikają po zatrzymaniu Payment Service. Nie należy używać `FLUSHALL`. Pliki `*.db`, `.venv/` i `.env` są w `.gitignore`. W repozytorium nie ma haseł ani sekretów.

## 15. Kontrakt komunikacji między usługami

- **Usługa wywołująca:** Payment Service (`PAYMENT-SERVICE`).
- **Nazwa logiczna odnajdywanej usługi:** `SCOOTER-SERVICE`. Adres i port wybiera klient Eureki z lokalnej kopii rejestru. W kodzie płatności nie ma adresu `localhost:8101`.
- **Metoda i ścieżka:** `GET /scooters/{scooter_id}`. Ścieżka jest budowana z `scooter_id` z żądania, czyli z ciała `POST /payments` albo z zapisanej płatności w `GET /payments/{id}/details`.
- **Wywołanie:** `await eureka_client.do_service("SCOOTER-SERVICE", f"/scooters/{scooter_id}", return_type="json", timeout=3)`.
- **Dane wejściowe i odpowiedź:** brak ciała żądania. Sukces to `200` z obiektem `{"id": 1, "name": "Hulajnoga 1", "model": "Xiaomi Mi 4 Pro", "status": "available"}` (kontrakt z LAB1, sekcja 3). Payment Service dodatkowo sprawdza, czy odpowiedź jest obiektem JSON z `id` równym żądanemu.
- **Obsługa błędów zależności** (kolejność: najpierw `HTTPError`, bo jest podklasą `URLError`):

  | Sytuacja w zależności | Odpowiedź Payment Service | Czy płatność zapisana? |
  |---|---|---|
  | `200` z poprawnym obiektem | `201` (`POST /payments`) / `200` (`/details`) | tak (`pending`) |
  | `404` (brak hulajnogi) | `404 {"detail": "Scooter not found"}` | nie |
  | inny błąd HTTP (np. `500`, `400`, `409`) | `502 {"detail": "Scooter Service returned an HTTP error"}` | nie |
  | odpowiedź niezgodna z kontraktem (np. inne `id`) | `502 {"detail": "Scooter Service returned an invalid response"}` | nie |
  | brak połączenia, brak instancji, timeout (`URLError`, `TimeoutError`) | `503 {"detail": "Scooter Service is unavailable"}` | nie |

  Własne kody kontraktu Payment Service, niezależne od zależności: `409` dla duplikatu `id` płatności (sprawdzany **przed** wywołaniem zależności) i dla ponownego opłacenia, `422` dla błędnych danych. Odpowiedzi nie zawierają tracebacków ani adresów wewnętrznych. Nie ma ponowień ani circuit breakera. Po awarii zależności nie zwracamy „udawanego” `200` z pustymi danymi.
- **Timeout:** 3 s na pojedyncze wywołanie HTTP (`DEPENDENCY_TIMEOUT_SECONDS`). Nie jest to limit całego żądania: przy kilku instancjach klient może próbować kolejnych adresów.
- **Diagram rejestracji i żądania biznesowego:**

```
  (1) rejestracja + heartbeat co 30 s           (1) rejestracja + heartbeat
SCOOTER-SERVICE :8101 ───────────►  EUREKA :8761  ◄─────────── PAYMENT-SERVICE :8102
                                       │
                                       │ (2) pobranie rejestru do lokalnej kopii
                                       │     (co 30 s, tylko adresy, bez danych domenowych)
                                       ▼
Klient ── (3) POST /payments {"scooter_id":1} ──────────────────► PAYMENT-SERVICE
                                                                       │
          (4) GET /scooters/1 bezpośrednio na adres z lokalnej kopii   │
SCOOTER-SERVICE ◄──────────────────────────────────────────────────────┘
      │  (5) 200 {"id":1,...} / 404 / błąd
      └──────────────────────────────────────────────────────────────► PAYMENT-SERVICE
Klient ◄── (6) 201 płatność / 404 / 502 / 503 ──────────────────────── PAYMENT-SERVICE
```

Żądanie domenowe (4–5) **nie przechodzi przez Eurekę**. Rejestr podaje tylko adres, a Payment Service łączy się z usługą floty bezpośrednio. Adres Eureki znają obie usługi (`EUREKA_SERVER_URL`). Adresu usługi floty nie zna nikt poza rejestrem i lokalną kopią rejestru w kliencie Payment Service.

## 16. Wyniki weryfikacji (LAB3)

Próby ręczne wykonano 2026-11-09: Windows 11, Python 3.14, Eureka w Dockerze (`docker compose up --build -d eureka`), Redis 7 w Dockerze, obie usługi przez Uvicorn. Stan rejestru sprawdzano w panelu i przez `GET http://127.0.0.1:8761/eureka/apps` z nagłówkiem `Accept: application/json`.

| Scenariusz | Stan początkowy i żądanie | Oczekiwany wynik | Wynik rzeczywisty | Przywrócenie stanu |
|---|---|---|---|---|
| Rejestracja | Uruchomienie Eureki i obu usług (8101, 8102) | Obie instancje `UP` | Po ok. 8 s w `/eureka/apps`: `SCOOTER-SERVICE` → `127.0.0.1:scooter-service:8101` `UP` (ip `127.0.0.1`, port `8101`); `PAYMENT-SERVICE` → `127.0.0.1:payment-service:8102` `UP` (port `8102`) | — |
| Odnajdywanie | W usłudze floty `POST /scooters` (`id=1`) → `201`. `POST /payments {"id":1,"scooter_id":1,"amount":12.5}`, potem `GET /payments/1/details` | `201`, a potem `200` z danymi hulajnogi z usługi floty | `POST /payments` → `201 {"id":1,"scooter_id":1,"amount":12.5,"status":"pending"}`. `/details` → `200 {"payment":{...},"scooter":{"id":1,"name":"Hulajnoga 1","model":"Xiaomi Mi 4 Pro","status":"available"}}`. Po `rent` w usłudze floty `/details` pokazuje `"status":"rented"`: dane są aktualne, a nie kopią. | usunięcie `app.db`, restart Payment Service |
| Brak zasobu | `POST /payments {"id":2,"scooter_id":999,...}` | `404`, procesy działają dalej | `404 {"detail":"Scooter not found"}`; `GET /payments` → tylko płatność `1`; obie usługi odpowiadają | — |
| Reguły własne | `pay` dwa razy; duplikat `POST /payments` z `id=1` | `200`, potem `409`; duplikat `409` | `pay` → `200 "status":"paid"`, drugi `pay` → `409 {"detail":"Payment is already paid"}`, duplikat → `409 {"detail":"Payment with this ID already exists"}` | restart Payment Service |
| Awaria zależności | Zabicie procesu usługi floty (`Stop-Process`, czyli crash bez wyrejestrowania). `GET /payments/1/details`, `POST /payments` (`id=3`), `GET /health` płatności | `503`; health wywołującej nadal `200` | `/details` → `503 {"detail":"Scooter Service is unavailable"}` (ok. 2,5 s, odmowa połączenia); `POST` → `503`, płatność `3` **nie** powstała (`GET /payments` → tylko `1`); `/health` → `200 {"status":"ok","service":"Payment Service"}`. Wpis `127.0.0.1:scooter-service:8101` nadal `UP` w Eurece. | restart usługi floty |
| Ponowne uruchomienie usługi wywoływanej | Start usługi floty z tym samym `SERVICE_PORT=8101` i tą samą bazą | ponownie `200` z danymi | Po ok. 5 s `/details` → `200`, hulajnoga ze statusem `rented`, który przetrwał restart dzięki SQLite. Adres się nie zmienił, więc lokalna kopia rejestru była od razu poprawna. | — |
| Zmiana portu (opcjonalne) | Zabicie usługi na 8101, start z `SERVICE_PORT=8111` i `--port 8111`, **bez zmian w kodzie** | Payment Service znajduje nowy adres | Przez ok. 55 s `503` (lokalna kopia rejestru Payment Service jeszcze bez 8111). Po ok. 59 s pierwsze `200`. Rejestr miał wtedy **dwa** wpisy `UP`: martwy `8101` (po crashu) i `8111`, więc kolejne wywołania dawały losowo `200` albo `503`. Po wygaśnięciu dzierżawy martwego wpisu (domyślnie 90 s bez heartbeatu) Eureka go usunęła i 6/6 wywołań → `200` (ok. 0,42 s). | zatrzymanie instancji 8111 |
| Poprawne zatrzymanie | Start instancji `SCOOTER-SERVICE` na 8121, zatrzymanie sygnałem `CTRL_BREAK` (jak `Ctrl+C`: Uvicorn wykonuje lifespan → `stop()`) | wpis znika z rejestru | Log: `Waiting for application shutdown. … Application shutdown complete.` Po ok. 40 s w rejestrze nie było już `…:8121`. Po crashu wpis zostawał, po poprawnym zatrzymaniu zniknął. | — |
| Awaria rejestru | `docker compose stop eureka`, potem 3× `GET /payments/1/details` | wywołania działają z lokalnej kopii rejestru | 3× `200` (ok. 0,41 s), `/health` → `200`. W logach klientów: `Cannot send heartbeat to server, try to register` i `All eureka servers ... are down`. Po `docker compose start eureka` obie usługi **same zarejestrowały się ponownie** przy kolejnym heartbeacie (`/eureka/apps` → oba wpisy `UP`). | `docker compose start eureka` |
| Testy automatyczne | `pytest -q` w obu usługach, bez Eureka Server | testy z atrapą, w tym mapowanie `502` | `scooter-service`: **`23 passed`** (8 LAB1 + 11 LAB2 + 4 LAB3). `payment-service`: **`14 passed`**. Jedyne ostrzeżenie (`DeprecationWarning` o `anyio.abc.BlockingPortal`) pochodzi z biblioteki Starlette. | — |

**Testy LAB3, Payment Service** (`payment-service/tests/test_lab3_payments.py`, atrapa `FakeEurekaClient` z asynchronicznymi `start()`, `stop()`, `do_service()`):

| Test | Co wykazuje |
|---|---|
| `test_create_payment_discovers_scooter_service_by_name` | **(1) odczyt po nazwie logicznej:** `201`. Wywołanie `("SCOOTER-SERVICE", "/scooters/1", "json", 3)`, czyli nazwa, ścieżka, typ i timeout. `start` i `stop` po jednym razie. |
| `test_create_payment_for_missing_scooter_returns_404_and_stores_nothing` | **(2) `404`** z zależności daje `404 Scooter not found`. Płatność nie powstaje. |
| `test_create_payment_returns_503_when_scooter_service_is_down` (×2: `URLError`, `TimeoutError`) | **(3) `503`**, a `/health` nadal `200`. Płatność nie powstaje. |
| `test_other_dependency_http_error_maps_to_502` (×3: `500`, `400`, `409`) | **(4) `502`** dla innego błędu HTTP zależności |
| `test_invalid_dependency_response_maps_to_502` | odpowiedź z innym `id` daje `502` |
| `test_invalid_body_returns_422_without_calling_dependency` | `422`, zero wywołań zależności |
| `test_duplicate_payment_returns_409_and_keeps_original` | `409` przed wywołaniem zależności, oryginał bez zmian |
| `test_pay_rule_pending_to_paid_only_once` | reguła `pending → paid`, drugi `pay` daje `409` |
| `test_missing_payment_returns_404` | `404` dla nieistniejącej płatności, bez wywołań zależności |
| `test_payment_details_reads_current_scooter_from_dependency` | `/details` zwraca aktualny stan hulajnogi z zależności |
| `test_payment_details_returns_503_but_payment_still_readable` | przy awarii zależności własne dane (`GET /payments/1`) są nadal dostępne |

**Testy LAB3, Scooter Rental Service** (`scooter-service/tests/test_lab3_registry.py`):

| Test | Co wykazuje |
|---|---|
| `test_eureka_client_started_and_stopped_with_storage` | kolejność cyklu życia: `start()` dopiero po utworzeniu repozytorium, `stop()` przed zamknięciem Redisa |
| `test_lab2_api_still_works_with_fake_registry` | API LAB2 działa z atrapą rejestru, usługa floty nie wywołuje innych usług |
| `test_eureka_client_configuration_from_environment` | `EurekaClient` dostaje `EUREKA_SERVER_URL`, `eureka_context="/eureka"`, `SERVICE_NAME`, `SERVICE_PORT`, `INSTANCE_IP`, `INSTANCE_HOST` i `strict_service_error_policy=False` |
| `test_eureka_client_defaults_use_logical_name_and_port` | domyślnie `SCOOTER-SERVICE`, port `8101`, nigdy `0.0.0.0` |

Testy LAB1 i LAB2 usługi floty dostają atrapę klienta Eureki przez `conftest.py` (`create_app(..., eureka_client=FakeEurekaClient())`), więc nie łączą się z siecią.

## 17. Ograniczenia i dokumentacja (LAB3)

- **Niedostępność usługi floty:** Payment Service nie może utworzyć płatności ani pokazać `/details` (`503`). Własne dane (`GET /payments`, `pay`) działają dalej. Nie ponawiamy wywołań, a klient musi spróbować ponownie.
- **Niedostępność rejestru:** usługi już działające nadal się komunikują dzięki lokalnej kopii rejestru (sprawdzone). Nowa instancja nie może się wtedy zarejestrować i nie zostanie odnaleziona. Zmiany adresów nie docierają do klientów. Po powrocie Eureki klienci rejestrują się ponownie sami.
- **Wpis po zatrzymaniu usługi i lokalna kopia rejestru:** `Ctrl+C` (poprawne zamknięcie) wyrejestrowuje instancję. Crash zostawia wpis `UP` do czasu wygaśnięcia dzierżawy (90 s bez heartbeatu) i eksmisji, a tryb self-preservation może to opóźnić (nie wyłączaliśmy go). Payment Service odświeża swoją kopię co 30 s, a serwer dodatkowo serwuje listę z własnego cache odpowiedzi. Przez to nowy adres był widoczny dopiero po ok. 60 s, a martwy wpis dawał losowe `503`. **Status `UP` w rejestrze, `200` z `/health` i poprawna odpowiedź domenowa to trzy różne dowody:** `UP` znaczy tylko, że instancja się zarejestrowała i wysyłała heartbeat. `/health` znaczy, że proces odpowiada. Dopiero `200` z `/payments/1/details` potwierdza, że odnajdywanie i wywołanie działają.
- **Różnica między awariami:** awaria rejestru → istniejące wywołania działają z kopii. Awaria usługi floty → `503`. Brak zasobu → `404` przy działających obu usługach.
- **Spójność:** sprawdzenie hulajnogi przy `POST /payments` to odczyt, a nie rezerwacja. Hulajnogę można usunąć albo zmienić jej stan zaraz po utworzeniu płatności. Nie ma wspólnej transakcji między usługami.
- **Trwałość płatności:** płatności są tylko w pamięci procesu Payment Service. Po restarcie znikają, a kilka instancji miałoby osobne magazyny.
- **Brak bezpieczeństwa:** brak uwierzytelniania między usługami i do Eureki. Rejestr słucha tylko na `127.0.0.1`.

**Dokumentacja wykorzystana w LAB3:**

| Źródło (sprawdzona wersja) | Problem | Zastosowany fragment | Weryfikacja |
|---|---|---|---|
| [py-eureka-client — README na GitHubie](https://github.com/keijack/python-eureka-client) i kod biblioteki `0.13.3` (`inspect.signature(EurekaClient.do_service)`). To biblioteka zewnętrzna, nie oficjalny klient Netflix. | Jak wywołać inną usługę po nazwie i dostać błąd HTTP do własnego mapowania; czy metody są asynchroniczne | `EurekaClient(..., eureka_context="/eureka", strict_service_error_policy=False)`, `await client.start()/stop()`, `await do_service(app_name, service, return_type="json", timeout=3)`. Sprawdziliśmy, że w 0.13.3 `start` i `do_service` to korutyny, a domyślny timeout to 5 s, więc ustawiamy 3. | Próby ręczne: `200` przez nazwę `SCOOTER-SERVICE`, `404` i `503` z rzeczywistej usługi. Testy z atrapą sprawdzają argumenty `do_service`. |
| [Spring Cloud Netflix — Service Discovery: Eureka Server](https://docs.spring.io/spring-cloud-netflix/reference/spring-cloud-netflix.html#spring-cloud-eureka-server) (Spring Cloud 2025.1.3) i [Netflix Eureka REST operations](https://github.com/Netflix/eureka/wiki/Eureka-REST-operations) | Pod jaką ścieżką serwer przyjmuje rejestrację i jak sprawdzić rejestr poza panelem; dlaczego wpisy znikają z opóźnieniem | Spring Cloud udostępnia API pod `/eureka/*` (Netflix opisuje `/eureka/v2`), stąd `eureka_context="/eureka"` i `EUREKA_SERVER_URL` bez prefiksu. `GET /eureka/apps` i `/eureka/apps/SCOOTER-SERVICE` z `Accept: application/json`. Dzierżawa (heartbeat 30 s, wygaśnięcie 90 s) i self-preservation. | `GET /eureka/apps` pokazał oba wpisy `UP` z poprawnym ip i portem. Zaobserwowaliśmy wpis po crashu i jego późniejsze usunięcie oraz wyrejestrowanie po `CTRL_BREAK`. |
| [FastAPI: Lifespan Events](https://fastapi.tiangolo.com/advanced/events/) | Jak połączyć `start()`/`stop()` klienta Eureki z istniejącym lifespanem LAB2 | `storage_lifespan` opakowany przez `lifespan` (`async with storage_lifespan(app): await start(); try: yield finally: await stop()`) | `test_eureka_client_started_and_stopped_with_storage` sprawdza kolejność. Log Uvicorna przy `CTRL_BREAK`: `Application shutdown complete`, a potem wpis zniknął z rejestru. |

**Weryfikacja sugestii AI:** każdą sugestię sprawdziliśmy uruchomieniem. Po pierwsze testy w obu usługach. Po drugie scenariusze ręczne z prawdziwą Eureką, Redisem i Uvicornem (tabela w sekcji 16). Po trzecie porównanie sygnatur `py-eureka-client` w zainstalowanej wersji. Przykład: pierwsza wersja testu konfiguracji odczytywała atrybut `client.app_name`, który w 0.13.3 nie istnieje. Test podstawia więc konstruktor i sprawdza przekazane argumenty.

## 18. Wkład autorów (LAB3)

Role autora i recenzenta zostały zamienione względem usług: Bartłomiej napisał Payment Service, a Oscar ją recenzował. Oscar zintegrował usługę floty z Eureką, a Bartłomiej recenzował te zmiany.

- **Oscar Borowiec (nr albumu 131409):** integracja Scooter Rental Service z Eureką: `app/eureka.py`, `create_app(..., eureka_client=None)`, podział na `storage_lifespan` i `lifespan` z poprawną kolejnością start/stop, atrapa `FakeEurekaClient` w `conftest.py`, żeby testy LAB1 i LAB2 nie łączyły się z siecią, testy `test_lab3_registry.py`. W Payment Service: wywołanie `do_service` po nazwie i mapowanie błędów `404/502/503` (`_fetch_scooter`). Próby ręczne: rejestracja, awaria i restart zależności, zmiana portu, poprawne zatrzymanie. README: sekcje 14 i 16.
- **Bartłomiej Bogdan (nr albumu 131407):** Payment Service: modele `PaymentCreate`, `Payment` i `PaymentDetails`, endpointy `/payments`, `/payments/{id}`, `/pay`, `/details`, reguła `pending → paid`, walidacja i `409`, magazyn w pamięci, `requirements.txt`. Testy `test_lab3_payments.py` (wymagane 1–4 i testy dodatkowe). Przygotowanie rejestru (`compose.yaml`, `eureka-server/` z pakietu) i próba awarii rejestru. README: sekcje 13, 15 i 17.
- **Wspólnie:** kontrakt komunikacji (sekcja 15), wzajemny przegląd kodu, końcowe uruchomienie testów i scenariuszy w czystym środowisku.

**AI:**
- Narzędzie: Claude (Anthropic), Claude Code.
- Zakres: szkic Payment Service i integracji z Eureką, testy z atrapą klienta, przeprowadzenie i opis prób ręcznych, szkic README LAB3.
- Weryfikacja: `pytest -q` w obu usługach (23 + 14), scenariusze ręczne z prawdziwą Eureką i Redisem (sekcja 16), przeczytanie i zrozumienie kodu przez obu autorów. Każdy z nas potrafi wyjaśnić rejestrację, odnajdywanie i granice obu usług oraz zmienić port albo dodać test.

**Kolejny etap (LAB4):** Spring Cloud Gateway na porcie 8080 z trasami `lb://SCOOTER-SERVICE` i `lb://PAYMENT-SERVICE`, jako jedno wejście dla klienta.
