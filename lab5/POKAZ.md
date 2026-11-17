# Pokaz LAB5 — instrukcja krok po kroku

Wszystkie polecenia są sprawdzone na tym komputerze (Windows 11, PowerShell, Docker Desktop). Wykonuj je **z katalogu głównego repozytorium**: `C:\Users\oscar\Desktop\PAWOoM-Project`.

**Cały pokaz potrzebuje jednej konsoli** (plus przeglądarki na dwa panele). Usługi działają w tle, a logi lądują w `%TEMP%\lab5-logs`.

---

## 0. Co pokazujemy (jedno zdanie)

> Klient wchodzi przez **jedną bramkę** (:8080), cztery usługi znajdują się nawzajem przez **Eurekę**, a po opłaceniu płatności **RabbitMQ** rozsyła zdarzenie do dwóch usług naraz (flota i ubezpieczenia), które odbierają je, kiedy mają czas.

```
Klient ─► Bramka :8080 ─┬─► Scooter   :8101 (flota, SQLite + Redis)
                        ├─► Payment   :8102 (płatności)         ─ publish payment.completed ─► RabbitMQ ─┬─► kolejka scooter.payment-events
                        ├─► Insurance :8103 (ubezpieczenia)  ◄───────────── odbiera ──────────────────────┤
                        └─► Maintenance :8104 (serwis)                                                      └─► kolejka insurance.payment-events
        (wszystkie usługi rejestrują się w Eurece :8761 i znajdują się po nazwach)
```

---

## 1. Przed pokazem (2 minuty, najlepiej dzień wcześniej)

- [ ] **Docker Desktop jest włączony** (ikona wieloryba, status „running"). Bez tego nic nie ruszy.
- [ ] Otwarta konsola PowerShell w `C:\Users\oscar\Desktop\PAWOoM-Project`.
- [ ] (opcjonalnie) `git pull` — jeśli kolega coś jeszcze dopisał. Po zmianie w `lab5\gateway` przebuduj bramkę: `cd lab5\gateway; mvn package -DskipTests` (Java i Maven: patrz sekcja 11).
- [ ] Zamknięte inne laby i procesy na portach 8080, 8101–8104, 8761 (skrypt sam sprawdzi i powie, który port jest zajęty).
- [ ] Dwie karty w przeglądarce, na razie puste: http://localhost:8761 oraz http://localhost:15672 (login `guest`, hasło `guest`).

---

## 2. Uruchomienie całego systemu (jedno polecenie)

```powershell
.\lab5\scripts\stop-lab5.ps1 -ResetData     # czysty start: kasuje starą bazę floty
.\lab5\scripts\start-lab5.ps1
```

Skrypt po kolei: włącza Redisa (kontener `lab5`), Eurekę i RabbitMQ (Docker), uruchamia usługi w kolejności **Scooter → Insurance → Payment → Maintenance**, potem bramkę i **czeka, aż bramka zobaczy wszystkie usługi**. Na końcu wypisuje:

```
GOTOWE: wszystkie 4 trasy odpowiadaja 200.
```

Trwa to **ok. minuty** (u mnie 54 s od czystego stanu). Pierwszy raz na nowym komputerze dłużej, bo Docker buduje obraz Eureki i pobiera biblioteki. Najdłużej czeka się na rejestr Eureki, bo bramka odświeża listę usług co ok. 30 s. W tym czasie możesz opowiadać (sekcja 10).

> Chcesz to samo bez skryptu, żeby zrozumieć, co się dzieje, albo gdy skrypt zawiedzie? Pełna instrukcja ręczna (6 konsol, wyjaśnienie zmiennych i kolejności) jest w **`URUCHOMIENIE_RECZNE.txt`**.

**Dlaczego kolejność ma znaczenie:** Scooter i Insurance przy starcie tworzą swoje kolejki w RabbitMQ. Gdyby Payment opublikował zdarzenie wcześniej, żadna kolejka by go nie dostała.

Po starcie odśwież karty z panelami:
- **Eureka** (http://localhost:8761) — w tabeli „Instances currently registered" cztery wpisy `UP`: `SCOOTER-SERVICE`, `PAYMENT-SERVICE`, `INSURANCE-SERVICE`, `MAINTENANCE-SERVICE`. Bramki tu nie ma (tylko pobiera rejestr).
- **RabbitMQ** (http://localhost:15672) → zakładka **Queues**: `scooter.payment-events` i `insurance.payment-events`, obie z `Ready: 0`.

---

### Opcjonalnie: podgląd w przeglądarce zamiast konsoli

Prosta strona z tabelami, przyciskami i logiem zapytań (status, `X-Cache`, `X-Gateway`). Pokazuje też stan usług z Eureki i liczbę wiadomości w obu kolejkach RabbitMQ. Uruchom **po** `start-lab5.ps1`, w osobnej konsoli:

```powershell
py lab5\frontend\server.py
```

Otwórz **http://127.0.0.1:8090**. Przycisk **„Uruchom scenariusz"** sam przechodzi cały Akt 3 (hulajnoga, płatność, opłacenie, odbiór zdarzeń przez obie usługi). Pojedyncze zakładki otwierają adresy `#payments`, `#insurances`, `#jobs`, `#events`. Kończysz przez `Ctrl+C`. Szczegóły i zasada działania są w nagłówku `lab5\frontend\server.py`.

---

## 3. Przygotowanie konsoli do pokazu

Wklej raz. Funkcja `api` wysyła żądanie przez bramkę i pokazuje **nagłówki** (to ważne: `X-Gateway`, `x-cache`) oraz treść.

```powershell
function api($method, $path, $json) {
  if ($json) { $f = "$env:TEMP\body.json"; $json | Out-File -Encoding ascii $f
               curl.exe -s -i -X $method "http://127.0.0.1:8080$path" -H "Content-Type: application/json" --data-binary "@$f" }
  else       { curl.exe -s -i -X $method "http://127.0.0.1:8080$path" }
}
function queues { docker exec lab5-rabbitmq rabbitmqctl list_queues name messages_ready messages_unacknowledged 2>$null | Select-String 'payment-events|name' }
function coverage($paymentId) { curl.exe -s http://127.0.0.1:8080/api/coverage | ConvertFrom-Json | Where-Object { $_.payment_id -eq $paymentId } }
```

> Jeśli powtarzasz pokaz bez `-ResetData`, dostaniesz `409` (te ID już istnieją). Zmień wtedy numery (9001 → 9002 itd.) albo zrób reset z sekcji 2.

---

## 4. Akt 1 — jedno wejście, cache i reguła biznesowa (LAB1, LAB2, LAB4)

**Co mówisz:** „Klient zna tylko adres 8080 i ścieżkę `/api/...`. Bramka sama wybiera usługę po ścieżce i pyta Eurekę o jej adres."

```powershell
api POST /api/scooters '{"id":9001,"name":"Hulajnoga 9001","model":"Xiaomi Mi 4 Pro"}'
api GET /api/scooters/9001
api GET /api/scooters/9001
```
Spodziewane: `201`, potem `200` z nagłówkiem **`x-cache: MISS`**, a za drugim razem **`x-cache: HIT`** (odczyt z Redisa). W każdej odpowiedzi **`X-Gateway: lab4`** — dowód, że przeszło przez bramkę.

```powershell
api POST /api/scooters/9001/rent
api POST /api/scooters/9001/rent
api POST /api/scooters/9001/return
```
Spodziewane: `200 rented`, potem **`409 {"detail":"Scooter is not available for rental"}`** (reguła: nie wypożyczysz zajętej hulajnogi), potem `200 available`.

**Dwa różne 404** (dobre pytanie na obronę):
```powershell
api GET /api/scooters/999999
api GET /api/nie-ma-takiej-trasy
```
Pierwsze: `{"detail":"Scooter not found"}` **z** `X-Gateway` — trasa pasowała, usługa nie znalazła rekordu. Drugie: inny JSON (`timestamp`, `path`, `requestId`) **bez** `X-Gateway` — żądanie w ogóle nie opuściło bramki.

---

## 5. Akt 2 — usługi rozmawiają ze sobą przez Eurekę (LAB3)

**Co mówisz:** „Payment, Insurance i Maintenance nie mają zapisanego adresu floty. Pytają Eurekę o nazwę `SCOOTER-SERVICE` i dzwonią pod adres, który dostały. Sprawdzają w ten sposób, czy hulajnoga istnieje."

```powershell
api POST /api/payments '{"id":9101,"scooter_id":9001,"amount":200}'
api GET /api/payments/9101/details
```
`201 pending`, a `/details` zwraca **płatność razem z aktualnymi danymi hulajnogi** (pobranymi z floty w tym momencie, nie kopią).

```powershell
api POST /api/insurances '{"id":9201,"scooter_id":9001,"premium":49.99}'
api GET /api/insurances/9201/details

api POST /api/jobs '{"id":9301,"scooter_id":9001,"description":"Wymiana hamulca"}'
api POST /api/jobs/9301/complete
api POST /api/jobs/9301/start
api POST /api/jobs/9301/complete
```
Serwis: `201 pending`, potem **`409`** (`Job cannot be completed from status 'pending'`), po `start` `200 in_progress`, po `complete` `200 completed`. To maszyna stanów `pending → in_progress → completed`.

**Hulajnoga, której nie ma:**
```powershell
api POST /api/payments '{"id":9102,"scooter_id":88888888,"amount":5}'
```
`404 {"detail":"Scooter not found"}` — flota odpowiedziała, że jej nie zna, więc płatność nie powstaje.

---

## 6. Akt 3 — komunikacja asynchroniczna: sedno LAB5

**Co mówisz:** „Opłacenie płatności to fakt, który interesuje inne usługi, ale klient nie ma czekać na ich reakcję. Payment wrzuca zdarzenie do RabbitMQ i od razu odpowiada klientowi."

**Krok 0 — opróżnij kolejki** (na wypadek zaległości z wcześniejszych prób):
```powershell
api POST /api/scooters/payment-events/consume | Select-Object -Last 1
api POST /api/insurances/payment-events/consume | Select-Object -Last 1
```

**Krok 1 — stan przed:**
```powershell
api GET /api/scooters/9001/payment-summary
```
`paid_payments_count: 0` (i `x-cache: MISS`).

**Krok 2 — opłać płatność:**
```powershell
api POST /api/payments/9101/pay
queues
```
Płatność od razu ma `"status":"paid"`. W kolejkach: **`scooter.payment-events 1`** i **`insurance.payment-events 1`**. *Jedna publikacja, dwie kopie* — każda usługa ma własną kolejkę związaną tym samym kluczem `payment.completed`. Pokaż to też w panelu RabbitMQ (Queues, `Ready: 1` w obu; panel odświeża się co kilka sekund).

**Krok 3 — nikt jeszcze nie odebrał, więc nic się nie zmieniło:**
```powershell
coverage 9101
api GET /api/scooters/9001/payment-summary | Select-String 'paid_payments'
```
Brak pokrycia ubezpieczeniowego, statystyki dalej `0`. To **spójność ostateczna**: stan floty jest chwilowo nieaktualny.

**Krok 4 — flota odbiera swoją wiadomość** (u nas konsument uruchamiany ręcznie, tak wymagało ćwiczenie):
```powershell
api POST /api/scooters/payment-events/consume | Select-Object -Last 1
queues
```
`consumed_messages: 1`, `applied_events: 1`. Kolejka floty `0`, ale **kolejka ubezpieczeń nadal `1`** — odbiór przez jedną usługę nie zabiera wiadomości drugiej.

**Krok 5 — ubezpieczenia odbierają swoją:**
```powershell
api POST /api/insurances/payment-events/consume | Select-Object -Last 1
queues
coverage 9101
```
`applied_events: 1`, obie kolejki `0`, a `coverage` zwraca rekord ze **składką 10.0** (5% z 200).

**Krok 6 — efekt widoczny przez bramkę:**
```powershell
api GET /api/scooters/9001/payment-summary
api GET /api/scooters/9001/payment-summary | Select-String 'x-cache'
```
`paid_payments_count: 1`, `total_paid_amount: 200.0`. Pierwszy odczyt **`MISS`** (konsument po zapisie usunął starą kopię z Redisa, więc nie ma starej wartości), drugi **`HIT`**.

**Krok 7 — ochrona przed duplikatem i błędami:**
```powershell
api POST /api/payments/9101/pay
```
`409 {"detail":"Payment is already paid"}`. Odrzucona operacja **niczego nie publikuje** (sprawdź `queues`: obie `0`).

**Co powiedzieć o niezawodności:**
- Wiadomość jest **trwała** (kolejka `durable`, `delivery_mode=2`), więc przeżyje restart RabbitMQ.
- Konsument potwierdza (ACK) **dopiero po zapisie** w bazie, więc awaria w trakcie nie gubi wiadomości.
- Skoro wiadomość może przyjść dwa razy, każde zdarzenie ma unikalny `event_id`, a konsument pamięta przetworzone — drugi egzemplarz nie zmienia stanu (*at-least-once* + idempotencja).

---

## 7. Akt 4 (opcjonalny, najefektowniejszy) — wyłączona usługa nie gubi zdarzeń

**Co mówisz:** „Ubezpieczenia przestają działać, a płatności dalej przechodzą. Zdarzenie czeka w kolejce."

```powershell
# 1) wyłącz Insurance (port 8103)
Get-NetTCPConnection -State Listen -LocalPort 8103 | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }

# 2) opłać kolejną płatność
api POST /api/payments '{"id":9103,"scooter_id":9001,"amount":100}'
api POST /api/payments/9103/pay
queues
```
`pay` → **`200 paid`** mimo wyłączonych ubezpieczeń. W `queues`: `insurance.payment-events 1` — wiadomość **czeka** (kolejka floty też ma `1`, bo nikt jeszcze jej nie odebrał).

```powershell
# 3) uruchom Insurance ponownie
Set-Location lab5\insurance-service
$env:EUREKA_SERVER_URL='http://127.0.0.1:8761'; $env:INSTANCE_IP='127.0.0.1'; $env:INSTANCE_HOST='localhost'
$env:RABBITMQ_URL='amqp://guest:guest@127.0.0.1:5672/%2F'; $env:SERVICE_NAME='INSURANCE-SERVICE'; $env:SERVICE_PORT='8103'
Start-Process .\.venv\Scripts\python.exe -ArgumentList '-m','uvicorn','app.main:app','--port','8103' -WindowStyle Hidden
Set-Location ..\..

# 4) odbierz zaległość BEZPOŚREDNIO z usługi (bramka widzi ją dopiero po ok. minucie)
Start-Sleep 8
curl.exe -s -X POST http://127.0.0.1:8103/insurances/payment-events/consume
```
`consumed_messages: 1`, `applied_events: 1` — zdarzenie z czasu awarii zostało odebrane.

> **Uwaga (powiedz to sam, zanim zapyta profesor):** Insurance trzyma dane **w pamięci**, więc po restarcie lista pokrycia zawiera tylko to nowe zdarzenie, a wcześniejsze rekordy zniknęły. Broker pamięta tylko wiadomości jeszcze nieodebrane.
>
> Po zabiciu usługi Eureka przez ok. 90 s nadal uważa ją za `UP`, więc `/api/insurances` przez bramkę może w tym czasie dać `500`/`503`. To znane opóźnienie rejestru opisane w README (sekcja 22).

---

## 8. Testy (pokaż na koniec)

Testy jednostkowe nie potrzebują żadnej infrastruktury:

```powershell
foreach ($s in 'scooter-service','payment-service','insurance-service','maintenance-service') {
  Push-Location lab5\$s; "$s : " + (.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider 2>&1 | Select-Object -Last 1); Pop-Location }
```
Spodziewane: **33**, **18**, **24**, **17** `passed`.

Testy integracyjne wymagają działającego systemu (sekcja 2) i uderzają w prawdziwą bramkę, Eurekę i RabbitMQ:

```powershell
Set-Location lab5
.\tests\.venv\Scripts\python.exe -m pytest tests\integration -v -p no:cacheprovider
Set-Location ..
```
Spodziewane: **`19 passed`** w ok. 20 s (11 z LAB4/LAB5 + 8 dla ubezpieczeń i serwisu). Można je powtarzać — każdy test tworzy rekordy z unikalnym ID.

---

## 9. Zatrzymanie

```powershell
.\lab5\scripts\stop-lab5.ps1                 # zatrzymuje usługi, bramkę, Eurekę i RabbitMQ (Redis zostaje włączony)
.\lab5\scripts\stop-lab5.ps1 -ResetData      # to samo + kasuje bazę floty
.\lab5\scripts\stop-lab5.ps1 -StopRedis      # to samo + zatrzymuje kontener Redis (lab5)
```
Skrypt zwalnia porty 8080 i 8101–8104, więc można od razu uruchamiać inny lab.

---

## 10. Ściąga: co powiedzieć o każdym labie

| Lab | Jedno zdanie |
|---|---|
| **1** | Jedna usługa REST (FastAPI) z regułą biznesową: hulajnogę wypożyczysz tylko gdy jest `available`, zwrócisz tylko gdy `rented`. Dane w pamięci. |
| **2** | Dane w SQLite (przeżywają restart) i cache Redis (cache-aside, `x-cache: MISS/HIT`, unieważnianie po zapisie, usługa działa też gdy Redis padnie). |
| **3** | Druga usługa (płatności) i **Eureka**: usługi znajdują się po nazwie logicznej zamiast zaszytych adresów. |
| **4** | **Bramka** jako jedno wejście dla klienta: wybiera usługę po ścieżce `/api/...`, a adres bierze z Eureki. |
| **5** | **RabbitMQ**: usługa publikuje zdarzenie i nie czeka, konsumenci odbierają je kiedy mogą (spójność ostateczna, ACK po zapisie, idempotencja). |

**Pytania, które mogą paść:**

- *Czym różni się Eureka od bramki?* Eureka mówi **gdzie** jest usługa (nie przekazuje żądań). Bramka jest wejściem dla klienta i korzysta z Eureki, żeby znaleźć adresy.
- *Po co kolejka, skoro można wywołać HTTP?* Usługi nie są związane czasowo: Payment działa, gdy flota lub ubezpieczenia są wyłączone, a wiadomość czeka w kolejce.
- *Co jeśli ta sama wiadomość przyjdzie dwa razy?* `event_id` zapisany u konsumenta — drugi egzemplarz jest rozpoznany i pominięty.
- *Dlaczego ACK dopiero po zapisie?* Gdyby ACK szedł wcześniej, a proces padłby w trakcie zapisu, zmiana zginęłaby bezpowrotnie. Teraz najgorszy przypadek to ponowne dostarczenie, które idempotencja neutralizuje.
- *Dlaczego konsument jest wywoływany endpointem?* Tak wymagało ćwiczenie. Produkcyjnie działałby stale w tle (`basic_consume`).
- *Co jest słabe w tym rozwiązaniu?* Insurance, Payment i Maintenance trzymają dane w pamięci. Producent publikuje przed zapisem `paid` (gdyby proces padł między tymi krokami, ponowne `pay` wyśle drugie zdarzenie — rozwiązaniem byłby Transactional Outbox). Nie ma kolejki martwych listów, a status `maintenance` hulajnogi nie jest powiązany ze zleceniami serwisowymi.

---

## 11. Gdy coś nie działa

| Objaw | Przyczyna i rozwiązanie |
|---|---|
| `503` z bramki tuż po starcie | Rejestr Eureki jeszcze się odświeża (30–70 s). Poczekaj i powtórz. Skrypt startowy czeka na to sam. |
| `500` z bramki po zabiciu usługi | Bramka ma w kopii rejestru stary adres (do ok. 90 s). Poczekaj albo ominą to wywołaniem bezpośrednim na porcie usługi. |
| `409` przy tworzeniu hulajnogi/płatności | Takie ID już istnieje. Zmień numer albo zrób `stop-lab5.ps1 -ResetData` i start od nowa. |
| Skrypt: „Port 80xx jest zajęty" | Został stary proces. Uruchom `.\lab5\scripts\stop-lab5.ps1`. |
| Skrypt: „Docker nie dziala" | Włącz Docker Desktop, poczekaj aż się załaduje, uruchom skrypt ponownie. |
| Skrypt: „Brak ...\.venv\..." | Brakuje środowiska Pythona w tej usłudze: `cd lab5\<usługa>; py -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt`. |
| Skrypt: „Nie znaleziono Javy" | Java i Maven są w `C:\Users\oscar\tools\` (`jdk-21.0.13+9`, `apache-maven-3.9.11`). Inną ścieżkę podasz parametrem `-JavaHome`. |
| Bramka nie zna nowych tras | Stary jar. `cd lab5\gateway`, ustaw `JAVA_HOME` i `Path` jak w sekcji 29 README, potem `mvn package -DskipTests`. |
| Chcę zobaczyć logi usługi | `%TEMP%\lab5-logs\<usługa>.err` (np. `Get-Content $env:TEMP\lab5-logs\payment-service.err -Tail 30`). |
| Testy integracyjne padają zaraz po starcie | Za wcześnie — bramka jeszcze nie widzi wszystkich usług. Odczekaj minutę i powtórz. |
