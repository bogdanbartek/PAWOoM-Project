# Uzupełnienie README — LAB2

Dopisz poniższe sekcje do README projektu z LAB1. Nie usuwaj opisu domeny, reguły, API ani planu drugiej usługi.

## Zmiany i decyzje

- Co zachowano z LAB1: ...
- Co zmieniono i dlaczego: ...
- Właściciel danych oraz granice drugiej usługi: ...
- Model tabel, klucze, powiązania i ograniczenia: ...
- Zachowana reguła biznesowa, operacja dozwolona i odrzucona: ...
- Odczyt objęty cache, uzasadnienie, dopuszczalna nieaktualność: ...
- Prefiks, klucz, TTL, unieważnianie po zapisie: ...

## Uruchomienie

Podaj wymagania, instalację, DATABASE_URL, REDIS_URL, prefiks i TTL, port oraz polecenia uruchomienia API i testów. Wskaż lokalizację bazy i sposób inicjalizacji schematu. Nie wpisuj sekretów.

## Dowody

| Scenariusz | Stan początkowy i żądanie | Oczekiwany wynik | Wynik rzeczywisty | Reset |
|---|---|---|---|---|
| Zapis i odczyt po restarcie bez cache | ... | ... | ... | ... |
| Reguła: sukces i odrzucenie bez zmiany | ... | ... | ... | ... |
| MISS → HIT, liczba odczytów bazy | ... | ... | ... | ... |
| Wygaśnięcie TTL | ... | ... | ... | ... |
| Zmiana i unieważnienie | ... | ... | ... | ... |
| Awaria GET, SET, DELETE cache | ... | ... | ... | ... |
| Przywrócenie Redis, możliwa stara wartość | ... | ... | ... | ... |

Wskaż cztery własne testy LAB2 i zachowane testy LAB1. Oddziel testy z zamiennikiem od ręcznych prób z rzeczywistym Redis.

## Porównanie i ograniczenia

Odpowiedz na pytania z sekcji 6 instrukcji LAB2. Opisz nieudane unieważnianie, współbieżność i zmiany schematu. Wyjaśnij, czy użycie cache jest właściwe dla odbiorcy Twoich danych.

## Dokumentacja i autorzy

| Źródło | Problem | Zastosowanie | Weryfikacja |
|---|---|---|---|
| ... | ... | ... | ... |
| ... | ... | ... | ... |

- Wkład każdej osoby: ...
- AI: narzędzie, zakres i weryfikacja albo „nie korzystano”.
- Kolejny etap pierwszej i planowanej drugiej usługi: ...
