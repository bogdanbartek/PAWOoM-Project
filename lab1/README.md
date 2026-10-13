# Własna usługa — LAB1

To szablon do uzupełnienia. Zastąp wskazówki własnymi decyzjami i wynikami. Obowiązuje zakres z instrukcji `lab1.md` otrzymanej wraz z materiałami. Starter zawiera wyłącznie `/health`, pusty magazyn w pamięci i test startowy.

## Uruchomienie i testy

Wymagania: Python 3.12 lub nowszy, PowerShell. Otwórz terminal w katalogu z tym README i `requirements.txt`.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8101
```

W drugim terminalu: `Invoke-RestMethod http://localhost:8101/health`. Dokumentacja: [Swagger UI](http://localhost:8101/docs). Zatrzymanie serwera: `Ctrl+C`. Nie trzeba aktywować środowiska. Zmień `replace-me` w aplikacji i teście na nazwę usługi.

## 1. Problem i granice

Opisz problem, użytkownika oraz zakres odpowiedzialności usługi. Wypisz także to, za co usługa nie odpowiada. Zdefiniuj 3–5 pojęć domenowych.

| Planowana usługa | Odpowiedzialność | Własne dane | Operacje | Potrzebne informacje od innej usługi |
|---|---|---|---|---|
| Pierwsza — implementowana teraz | ... | ... | ... | ... |
| Druga — implementowana później | ... | ... | ... | ... |

Wyjaśnij granice biznesowe i właściciela zapisu danych. Opisz jedno przyszłe wywołanie HTTP między usługami: nadawca, odbiorca, metoda, ścieżka, żądanie, odpowiedź i zachowanie przy niedostępności odbiorcy. Na LAB1 nie implementujesz tego połączenia.

## 2. Model i reguła biznesowa

Opisz pola, typy, wymagane wartości, statusy i sposób nadawania identyfikatorów. Zapisz jedną regułę wykraczającą poza typy, wymagane pola i unikalność identyfikatora. Podaj operację dozwoloną, niedozwoloną oraz kod błędu. Wszystkie warunki odrzucenia sprawdzaj przed zmianą stanu.

## 3. Kontrakt API

Minimum: **trzy endpointy domenowe i osobny `/health`**. Zastąp ścieżki własnymi nazwami; wybierz co najmniej jedną operację zapisu.

| Metoda | Ścieżka | Znaczenie | Sukces | Błędy |
|---|---|---|---|---|
| GET | `/health` | Status i nazwa usługi | 200 | ... |
| GET | `/...` | Lista | 200 | ... |
| GET | `/.../{id}` | Szczegóły | 200 | 404 |
| POST albo PATCH | `/...` albo `/.../{id}` | Utworzenie albo modyfikacja | 201 albo 200 | ... |

Dołącz przykładowe żądania i odpowiedzi JSON, także błędy `404`, `409` i `422`. Opisz format `detail`; standardowe błędy walidacji FastAPI mają inną treść niż `HTTPException`. Wyjaśnij dobór kodów i regułę biznesową. Przy samym `PATCH` podaj dane początkowe.

## 4. Testy i stan danych

Napisz minimum **trzy własne testy automatyczne**: zapis → odczyt, błędne dane bez zmiany stanu, konflikt bez zmiany stanu. Co najmniej jeden sprawdza regułę biznesową; jeśli żaden jej nie obejmuje, dodaj następny. Dostarczony test `/health` nie wlicza się do trzech.

Każdy test ma własną aplikację z `create_app()` i znany stan początkowy. Sprawdzaj kod odpowiedzi, istotne pola JSON i wynik ponownego odczytu. Do wspólnych fixture dla wielu plików możesz użyć `tests/conftest.py`.

| Scenariusz | Stan początkowy i dokładne żądanie | Oczekiwany status, treść i stan | Wynik rzeczywisty | Reset danych |
|---|---|---|---|---|
| Health | ... | ... | ... | ... |
| Lista i szczegóły | ... | ... | ... | ... |
| Zapis → odczyt | ... | ... | ... | ... |
| Brak zasobu | ... | ... | ... | ... |
| Błędne dane | ... | ... | ... | ... |
| Konflikt | ... | ... | ... | ... |
| Reguła biznesowa: dozwolona i niedozwolona operacja | ... | ... | ... | ... |
| Restart | ... | ... | ... | ... |

Scenariusze mogą współdzielić test, jeśli sprawdza wszystkie wskazane wymagania. Podaj wynik testów uruchomionych poleceniem ze wstępu.

Osobno uruchom Uvicorna, wykonaj zapis i odczyt przez HTTP, zatrzymaj go i uruchom ponownie. Zapisz rezultat. Wyjaśnij, dlaczego dane przetrwały między żądaniami, ale nie restart procesu. Nie zmieniaj kodu podczas eksperymentu (`--reload` restartuje aplikację).

## 5. Porównanie architektur

Narysuj małe schematy tego samego systemu: monolit, modularny monolit i mikrousługi. Zaznacz procesy, granice, dane i sposób komunikacji. Wyjaśnij:

1. Dlaczego twoja usługa może być mikrousługą i czym różni się od klasy/modułu?
2. Jak wyglądałby system jako monolit?
3. Co zmieni podział na usługi, w tym koszty sieci i wpływ awarii zależności?
4. Którą architekturę wybrałbyś dla obecnej skali problemu i dlaczego?

## 6. Dokumentacja wykorzystana podczas pracy

Wykorzystaj co najmniej dwa konkretne fragmenty oficjalnej dokumentacji. Przykładowe punkty startowe: [modele żądań](https://fastapi.tiangolo.com/tutorial/body/), [błędy](https://fastapi.tiangolo.com/tutorial/handling-errors/), [testowanie](https://fastapi.tiangolo.com/tutorial/testing/).

| Odnośnik do fragmentu | Rozwiązywany problem | Co zastosowano w kodzie | Jak sprawdzono działanie |
|---|---|---|---|
| ... | ... | ... | ... |
| ... | ... | ... | ... |

## 7. Ograniczenia, autorzy i AI

Opisz dane w pamięci, ich reset przy restarcie i brak wspólnego stanu między instancjami. Wskaż inne ograniczenia własnej implementacji.

- Autorzy i wkład każdej osoby: ...
- AI: narzędzie, zakres pomocy i sposób weryfikacji albo „nie korzystano”.

Przed oddaniem sprawdź instalację w nowym środowisku oraz kompletność README. Nie dołączaj `.venv`, cache Pythona ani sekretów. Każda osoba w parze samodzielnie wyjaśnia kod i wykonuje małą zmianę podczas odbioru. LAB1 to pierwsza usługa; wymaganie co najmniej dwóch różnych usług na osobę dotyczy całego projektu semestralnego.
