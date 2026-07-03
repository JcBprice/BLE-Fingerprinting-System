# Zadanie

Utwórz (lub zaktualizuj, jeśli już istnieje) plik `architectural.md`.

Ten plik ma być **jedynym źródłem wiedzy o architekturze projektu**. Ma być napisany w sposób zrozumiały zarówno dla człowieka, jak i dla modeli AI.

## Główne cele

1. Umożliwić programiście bardzo szybkie zrozumienie całego projektu.
2. Zmniejszyć liczbę tokenów potrzebnych podczas kolejnych rozmów z AI poprzez przechowywanie pełnego opisu architektury.
3. Ułatwić rozwijanie projektu bez konieczności ponownej analizy całego kodu.
4. Dokumentować wszystkie zmiany architektury w czasie.

---

# Zasady

* Nigdy nie usuwaj ważnych informacji.
* Aktualizuj dokument po każdej zmianie kodu.
* Jeżeli zmienia się zachowanie funkcji lub modułu, zaktualizuj odpowiedni opis.
* Jeżeli dodawany jest nowy plik, klasa, moduł lub funkcja — automatycznie dopisz ją do dokumentacji.
* Jeżeli coś zostanie usunięte z projektu, oznacz to w historii zmian.
* Dokument ma zawsze odzwierciedlać aktualny stan kodu.

---

# Struktura dokumentu

## 1. Informacje o projekcie

Opisz:

* nazwę projektu
* cel projektu
* główne funkcjonalności
* technologie
* języki programowania
* frameworki
* biblioteki
* wymagania

---

## 2. Struktura katalogów

Opisz całe drzewo projektu.

Przykład:

```
src/
    api/
    auth/
    database/
    frontend/
    utils/

tests/

docs/

config/

...
```

Przy każdym folderze napisz:

* do czego służy
* co zawiera
* od czego zależy

---

## 3. Architektura

Opisz:

* zastosowany wzorzec architektoniczny
* przepływ danych
* zależności pomiędzy modułami
* odpowiedzialność każdego modułu
* komunikację pomiędzy modułami
* miejsca inicjalizacji aplikacji

Dodaj diagram tekstowy.

Przykład:

```
Frontend
    ↓
API
    ↓
Service
    ↓
Repository
    ↓
Database
```

---

## 4. Opis wszystkich plików

Dla KAŻDEGO pliku utwórz sekcję.

Przykład:

# src/api/user.py

Cel pliku

Importy

Eksportowane elementy

Zależności

Które moduły z niego korzystają

Jakie problemy rozwiązuje

---

## 5. Dokumentacja każdej klasy

Dla każdej klasy opisz:

* przeznaczenie
* odpowiedzialność
* pola
* metody
* zależności
* wykorzystywane interfejsy
* kto tworzy obiekty tej klasy
* gdzie jest używana

---

## 6. Dokumentacja każdej funkcji

Dla każdej funkcji opisz bardzo dokładnie:

### Nazwa

### Lokalizacja

### Cel

### Argumenty

* nazwa
* typ
* znaczenie

### Zwracana wartość

### Opis działania krok po kroku

### Algorytm

### Warunki

### Możliwe błędy

### Efekty uboczne

### Złożoność obliczeniowa

### Kto wywołuje tę funkcję

### Jakie funkcje ona wywołuje

### Jak wpływa na resztę systemu

### Przykład użycia

---

## 7. Przepływ wykonywania programu

Opisz krok po kroku:

Co dzieje się od uruchomienia programu.

Jak wykonywany jest kod.

Jak dane przechodzą pomiędzy modułami.

---

## 8. Przepływ danych

Dla każdego ważnego procesu opisz:

Skąd pochodzą dane.

Jak są przetwarzane.

Jak są walidowane.

Gdzie są zapisywane.

Kto z nich korzysta.

---

## 9. Diagram zależności

Dla każdego modułu pokaż:

```
Module A
 ├── korzysta z Module B
 ├── korzysta z Module C
 └── korzysta z Module D
```

---

## 10. Diagram wywołań funkcji

Pokaż ścieżki wykonywania.

Przykład:

```
main()

↓

initialize()

↓

loadConfig()

↓

connectDatabase()

↓

startServer()
```

---

## 11. Globalne zmienne

Opisz:

* wszystkie zmienne globalne
* konfiguracje
* stałe

---

## 12. Konfiguracja

Opisz:

* pliki konfiguracyjne
* zmienne środowiskowe
* ich znaczenie
* wartości domyślne

---

## 13. API

Jeżeli istnieje:

Opisz każdy endpoint.

Metoda

Adres

Parametry

Odpowiedzi

Kody błędów

Przykłady

---

## 14. Baza danych

Jeżeli występuje:

Opisz:

* wszystkie tabele
* relacje
* indeksy
* modele
* migracje

---

## 15. Historia zmian architektury

Każda zmiana ma zostać dopisana.

Przykład:

```
## 2026-07-03

Dodano moduł logowania.

Zmodyfikowano cache.

Usunięto stary parser.
```

Nigdy nie kasuj historii.

---

## 16. Lista TODO

Automatycznie wykrywaj:

* miejsca wymagające refaktoryzacji
* duplikację kodu
* potencjalne błędy
* martwy kod
* funkcje zbyt długie
* nieużywane klasy
* nieużywane importy

---

## 17. Najważniejsze zależności

Opisz wszystkie zależności projektu.

Dla każdej biblioteki:

* po co jest
* gdzie jest używana
* od czego zależy

---

## 18. Słownik projektu

Wyjaśnij wszystkie nazwy:

* klas
* modułów
* skrótów
* pojęć

---

## 19. Podsumowanie architektury

Na końcu utwórz krótkie podsumowanie zawierające:

* najważniejsze moduły
* główne zależności
* przepływ danych
* sposób działania projektu
* najważniejsze elementy do zrozumienia

---

# Ważne wymagania

Dokument ma być:

* kompletny,
* bardzo szczegółowy,
* stale aktualizowany,
* zgodny z aktualnym kodem,
* napisany w Markdown,
* czytelny dla człowieka,
* zoptymalizowany pod modele AI.

Nie kopiuj całego kodu źródłowego do dokumentu. Zamiast tego twórz precyzyjne opisy, pseudokod, diagramy tekstowe oraz relacje pomiędzy elementami projektu. Dzięki temu `architectural.md` ma pełnić rolę skondensowanej bazy wiedzy, pozwalającej AI zrozumieć projekt bez konieczności ponownego analizowania wszystkich plików.
