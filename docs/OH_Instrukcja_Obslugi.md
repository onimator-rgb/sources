# OH — Operational Hub
# Instrukcja obslugi dla zespolu

> Wersja: Kwiecien 2026 | Dotyczy: OH.exe (najnowsza wersja)

---

## Spis tresci

1. [Co to jest OH?](#1-co-to-jest-oh)
2. [Pierwsze uruchomienie](#2-pierwsze-uruchomienie)
3. [Codzienny przeglad — jak zaczac zmiane](#3-codzienny-przeglad)
4. [Zakladka Accounts — lista kont](#4-zakladka-accounts)
5. [Panel szczegolowy konta (drawer)](#5-panel-szczegolowy-konta)
6. [Cockpit — podglad operacyjny](#6-cockpit)
7. [Session Report — raport sesji](#7-session-report)
8. [Rekomendacje](#8-rekomendacje)
9. [Zarzadzanie sources](#9-zarzadzanie-sources)
10. [Znajdowanie nowych sources](#10-znajdowanie-nowych-sources)
11. [Operator actions — tagi, review, limity](#11-operator-actions)
12. [Skroty klawiaturowe](#12-skroty-klawiaturowe)
13. [Ustawienia](#13-ustawienia)
14. [Bezpieczenstwo i backup](#14-bezpieczenstwo-i-backup)
15. [FAQ — czeste pytania](#15-faq)
16. [Ankieta dla zespolu](#16-ankieta-dla-zespolu)

---

## 1. Co to jest OH?

OH (Operational Hub) to narzedzie desktopowe do zarzadzania kampaniami Onimator. Laczy sie z folderem bota i daje operatorom jedno miejsce do:

- **Podgladu wszystkich kont** — status, aktywnosc, tagi, FBR, sources
- **Analizy FBR** (Follow-Back Rate) — ktore sources dzialaja, ktore nie
- **Monitorowania sesji** — ile follow/like/DM zrobilo konto dzisiaj
- **Zarzadzania sources** — usuwanie slabych, dodawanie nowych, przywracanie usunietych
- **Review kont** — flagowanie problemow, tagi TB/limits, notatki
- **Rekomendacji** — system sam podpowiada co wymaga uwagi
- **Codziennego przegladu** — Cockpit pokazuje co trzeba zrobic na poczatku zmiany

OH **nigdy nie modyfikuje** plików bota poza `sources.txt` (i zawsze robi backup).

---

## 2. Pierwsze uruchomienie

1. Uruchom `OH.exe`
2. Na gorze wpisz sciezke do folderu Onimator (np. `C:\Users\Admin\Desktop\full_igbot_13.9.0`)
3. Kliknij **Save**
4. Kliknij **Scan & Sync** — OH przeskanuje wszystkie urzadzenia i konta
5. Kliknij **Cockpit** zeby zobaczyc podsumowanie operacyjne

**Opcjonalnie (w Settings):**
- Wpisz **HikerAPI Key** jesli chcesz uzywac funkcji "Find Sources"
- Wpisz **Gemini API Key** jesli chcesz AI scoring przy szukaniu sources
- Ustaw progi FBR (domyslnie: min 100 follows, min 10% FBR)

---

## 3. Codzienny przeglad

Zalecana kolejnosc na poczatku zmiany:

### Krok 1: Scan & Sync
Kliknij **Scan & Sync** aby pobrac najnowsze dane z bota (sesje, tagi, konfiguracje).

### Krok 2: Cockpit
Kliknij **Cockpit**. Zobaczysz 5 sekcji:

| Sekcja | Co pokazuje |
|--------|-------------|
| **Do zrobienia teraz** | Najpilniejsze problemy (CRITICAL/HIGH) |
| **Konta do review** | Oflagowane konta czekajace na przeglad |
| **Top rekomendacje** | Kolejne najwazniejsze zalecenia |
| **Ostatnie source actions** | Ostatnie usuniecia/przywrocenia sources |
| **Dzisiaj wykonano** | Co juz zrobil zespol dzisiaj |

Kliknij dwukrotnie na wiersz zeby przejsc do konkretnego konta lub source.

### Krok 3: Session Report (jesli potrzeba)
Kliknij **Session** aby zobaczyc pelny raport z 8 sekcjami:
- Konta z 0 akcjami dzisiaj
- Urzadzenia nie dzialajace
- Konta z review
- Niski follow / like
- Konta TB / limits

### Krok 4: Przegladaj konta
Klikaj na konta w tabeli — otworzy sie **panel szczegolowy** po prawej stronie z pelnym profilem konta.

---

## 4. Zakladka Accounts

To glowny widok. Tabela z 21 kolumnami pokazuje wszystkie konta.

### Filtry (gorna belka)

| Filtr | Opcje | Kiedy uzywac |
|-------|-------|-------------|
| **Status** | Active / Removed / All | Domyslnie "Active only" |
| **FBR** | All / Needs attention / Never analyzed / Errors / No quality / Has quality | Szukanie kont wymagajacych analizy |
| **Device** | Lista urzadzen | Filtrowanie po telefonie |
| **Search** | Wpisz username | Szybkie znalezienie konta |
| **Tags** | All / TB / limits / SLAVE / START / PK / Custom | Filtrowanie po tagach |
| **Activity** | All / 0 actions / Has actions | Konta bez aktywnosci dzisiaj |
| **Review only** | Checkbox | Tylko oflagowane konta |
| **Clear** | Przycisk | Resetuje wszystkie filtry |

### Przyciski na pasku

| Przycisk | Co robi |
|----------|---------|
| **Cockpit** | Otwiera podglad operacyjny |
| **Scan & Sync** | Skanuje folder bota i synchronizuje |
| **Analyze FBR** | Uruchamia analize FBR dla wszystkich kont |
| **Refresh** | Odswieza tabele z bazy (bez skanowania) |
| **Session** | Otwiera raport sesji |
| **Recs** | Otwiera rekomendacje |
| **History** | Otwiera historie akcji operatora |

### Menu akcji (przycisk "Actions" w kazdym wierszu)

Kliknij "Actions" przy koncie aby zobaczyc opcje:
- **Open Folder** — otwiera folder konta w Explorerze
- **View Sources** — podglad sources z FBR
- **Find Sources** — szukanie nowych sources (wymaga HikerAPI)
- **Set Review** / **Clear Review** — flagowanie konta
- **TB +1** — zwiekszenie poziomu TB
- **Limits +1** — zwiekszenie poziomu limits

---

## 5. Panel szczegolowy konta

**Jak otworzyc:** Kliknij na dowolne konto w tabeli — panel pojawi sie po prawej stronie.

### Zakladka "Summary"

Pokazuje pelny profil operacyjny konta:

**Karty wydajnosci (4 kolorowe kafelki):**

| Karta | Co pokazuje | Kiedy czerwona |
|-------|-------------|----------------|
| **Today's Activity** | Follow/Like/DM dzisiaj vs limity | 0 akcji w aktywnym slocie |
| **FBR Status** | Quality sources, best FBR% | Brak quality sources |
| **Source Health** | Liczba aktywnych sources | 0 sources lub < 5 |
| **Account Health** | Poziom TB i Limits | TB >= 4 lub Limits >= 4 |

**Konfiguracja:**
- Follow/Unfollow wlaczone (Yes/No)
- Limity follow/like
- Slot czasowy (start-end)
- Daty: odkryto, ostatnio widziane
- Pliki: data.db, sources.txt (istnieja/nie)

**FBR Snapshot:**
- Quality/Total, Best FBR%, najwyzszy wolumen
- Anomalie, bledy schematu
- Data ostatniej analizy

### Zakladka "Alerts"

**Alerty** — automatycznie wygenerowane problemy posortowane wg waznosci:
- CRITICAL (czerwone) — np. 0 akcji w aktywnym slocie, TB5
- HIGH (pomaranczowe) — np. TB4, brak sources
- MEDIUM (niebieskie) — np. niski follow, limits 4
- LOW (szare) — np. nigdy nie analizowano FBR

Kazdy alert ma:
- Tytul problemu
- Szczegoly
- Zalecana akcja
- Przycisk akcji (np. "TB +1", "Clear Review")

**Karty kontekstowe:**
- "Follow is pending" — sugestia wylaczenia na 48h
- "Try again later" — sugestia zwiekszenia TB
- "No sources" — brak sources do dzialania

**Historia review:**
- Aktualne review (flag + notatka + data)
- Poprzednie review (kto, kiedy, co zmienil)

### Przyciski na dole panelu

| Przycisk | Co robi |
|----------|---------|
| **Set Review** / **Clear Review** | Flaguje lub czyści review |
| **TB +1** | Zwieksza poziom TB |
| **Limits +1** | Zwieksza poziom Limits |
| **Open Folder** | Otwiera folder konta |
| **Copy Diagnostic** | Kopiuje pelny raport konta do schowka |

---

## 6. Cockpit

**Jak otworzyc:** Kliknij **Cockpit** na pasku narzedzi.

5 sekcji:

1. **Do zrobienia teraz** — top 10 najpilniejszych problemow (CRITICAL/HIGH)
2. **Konta do review** — lista oflagowanych kont z notatkami
3. **Top rekomendacje** — kolejne 10 zaleceń
4. **Ostatnie source actions** — ostatnie usuniecia/przywrocenia
5. **Dzisiaj wykonano** — akcje zespolu dzisiaj

**Akcje:** Kliknij dwukrotnie wiersz aby przejsc do konta/source. Mozesz ustawic review bezposrednio z Cockpitu.

---

## 7. Session Report

**Jak otworzyc:** Kliknij **Session** na pasku narzedzi.

8 zakladek analizy:

| Zakladka | Co pokazuje | Typowa akcja |
|----------|-------------|-------------|
| **Actions (checklist)** | Zbiorczy checklist wg priorytetu | Przejdz po kolei od CRITICAL |
| **0 Actions Today** | Konta bez aktywnosci | Sprawdz urzadzenie, oflaguj |
| **Devices** | Urzadzenia nie dzialajace | Sprawdz telefon |
| **Review** | Konta z review | Przejrzyj, wyczysc lub eskaluj |
| **Low Follow** | Niski follow vs limit | Sprawdz warmup, sources |
| **Low Like** | Niski like vs limit | Sprawdz konfiguracje |
| **TB** | Konta z trust-boost | TB+1, restart warmupu |
| **Limits** | Konta z limits | Limits+1, wymiana sources |

**Warmup TB (zalecenia):**
- TB1: Follow 5-10/dzien, Like 10-20/dzien
- TB2: Follow 15-25/dzien, Like 30-50/dzien
- TB3: Follow 30-45/dzien, Like 50-80/dzien
- TB4: Follow 50-70/dzien, Like 80-120/dzien
- TB5: Konto wymaga przeniesienia na inne urzadzenie

**Przycisk "Copy Report"** kopiuje caly raport do schowka (np. na Slacka).

---

## 8. Rekomendacje

**Jak otworzyc:** Kliknij **Recs** na pasku narzedzi.

### 6 typow rekomendacji

| Typ | Problem | Co robic |
|-----|---------|----------|
| **Weak Source** | Source z niskim FBR | Usun lub wymien |
| **Source Exhaustion** | Za malo sources na koncie | Dodaj nowe sources |
| **Low Like** | 0 like mimo aktywnosci | Sprawdz konfiguracje like |
| **Limits Max** | Limits level 5 | Wymien sources |
| **TB Max** | TB level 5 | Przenies konto |
| **Zero Actions** | 0 akcji w aktywnym slocie | Sprawdz urzadzenie |

### Filtry
- **All** — wszystkie rekomendacje
- **Critical + High** — tylko pilne
- **Accounts only** — tylko na poziomie konta
- **Sources only** — tylko na poziomie source

### Akcje
- **Open Target** — przejdz do konta/source
- **Delete Source** — usun slaby source
- **Clean Sources** — usun non-quality z konta
- **Apply Selected** — oflaguj wybrane konta do review
- **Copy** — kopiuj do schowka

---

## 9. Zarzadzanie sources

### Podglad globalny (zakladka Sources)

Pokazuje wszystkie sources ze wszystkich kont z zagregowanymi metrykami:
- Ile kont uzywa danego source
- Laczna liczba follows i followbacks
- Sredni i wazony FBR%
- Ile kont ma "quality" dla tego source

**Kliknij source** aby zobaczyc rozklad per konto (dolny panel).

### Usuwanie sources

**Pojedynczo:** Zakladka Sources → zaznacz source → "Delete Source"
**Hurtowo:** "Bulk Delete Weak Sources" → ustaw prog FBR → podglad → potwierdz
**Per konto:** Actions → View Sources → "Delete Selected" lub "Remove Non-Quality"

Kazde usuniecie:
- Tworzy backup (`sources.txt.bak`)
- Pokazuje podglad przed usunieciem
- Zapisuje historie (kto, kiedy, ile)

### Przywracanie sources

Zakladka Sources → **History** → zaznacz operacje → **Revert Selected** (zielony przycisk)

---

## 10. Znajdowanie nowych sources

**Wymaga:** HikerAPI Key (wpisz w Settings)

1. W tabeli kont kliknij **Actions** → **Find Sources**
2. System automatycznie:
   - Pobiera profil klienta z Instagrama
   - Szuka podobnych profili (sugerowane + wyszukiwanie)
   - Filtruje (min 1000 followers, nie prywatne)
   - Oblicza engagement rate
   - AI scoruje trafnosc (opcjonalnie, wymaga Gemini Key)
3. Wyswietla top 10 profili z: username, followers, ER%, kategoria, AI score
4. Zaznacz ktore chcesz → **Add Selected to sources.txt**

**Wskazowka:** Jesli AI Score jest >= 7.0 (zielony), profil jest dobrze dopasowany.

---

## 11. Operator actions

### Review (flagowanie kont)

- **Set Review** — flaguje konto z opcjonalna notatka (np. "follow pending", "try again later")
- **Clear Review** — czysci flage po rozwiazaniu problemu
- Widoczne w kolumnie "Review" i w panelu szczegolowym

### Tagi TB (Trust-Boost)

Poziomy TB1-TB5. Kazdy poziom oznacza etap warmupu po action blocku.
- **TB +1** — zwieksza poziom (np. TB2 → TB3)
- TB5 = konto wymaga przeniesienia na inne urzadzenie
- System ostrzega przy probie zwiekszenia ponad TB5

### Tagi Limits

Poziomy 1-5. Kazdy poziom oznacza stopien wyczerpania sources.
- **Limits +1** — zwieksza poziom
- Limits 5 = rozważ wymiane sources
- System ostrzega przy probie zwiekszenia ponad 5

### Historia akcji

Kliknij **History** na pasku aby zobaczyc pelna historie operatorska:
- Kto, kiedy, co zmienil
- Stare i nowe wartosci
- Nazwa komputera operatora

---

## 12. Skroty klawiaturowe

| Skrot | Gdzie | Co robi |
|-------|-------|---------|
| **Space** | Tabela kont | Otwiera/zamyka panel szczegolowy |
| **Escape** | Panel / dialog | Zamyka panel lub dialog |
| **Left / Right** | Panel otwarty | Przelacza zakladki Summary/Alerts |
| **Up / Down** | Tabela kont | Przechodzi miedzy kontami (panel aktualizuje sie automatycznie) |
| **Ctrl+R** | Cockpit / Recs | Odswieza dane |
| **Double-click** | Cockpit / Recs / Session | Przechodzi do konta/source |

---

## 13. Ustawienia

Zakladka **Settings** w glownym oknie:

| Ustawienie | Domyslna wartosc | Opis |
|-----------|-------------------|------|
| Min follows for quality | 100 | Minimalna liczba followow aby source byl "quality" |
| Min FBR% for quality | 10% | Minimalny FBR aby source byl "quality" |
| Weak source threshold | 5% | Prog FBR dla hurtowego usuwania |
| Min sources warning | 5 | Ostrzezenie jesli konto ma mniej sources |
| Theme | dark | Ciemny lub jasny motyw |
| HikerAPI Key | (puste) | Klucz do Find Sources |
| Gemini API Key | (puste) | Klucz do AI scoringu (opcjonalny) |

---

## 14. Bezpieczenstwo i backup

- OH **nigdy nie modyfikuje** data.db, settings.db ani plików runtime bota
- Przed kazda zmiana sources.txt tworzony jest **backup** (`sources.txt.bak`)
- Kazde usuniecie mozna **cofnac** z historii (przycisk "Revert")
- Wszystkie akcje operatora sa **logowane** z timestampem i nazwa komputera
- Tagi operatora (OP:) sa **oddzielone** od tagow bota — nigdy sie nie koliduja

---

## 15. FAQ

**P: Czy OH moze zepsuc bota?**
O: Nie. OH modyfikuje tylko `sources.txt` (z backupem). Nigdy nie rusza data.db, settings.db ani konfiguracji runtime.

**P: Jak cofnac usuniecie source?**
O: Zakladka Sources → History → zaznacz operacje → Revert Selected.

**P: Co oznacza "Needs attention" w filtrze FBR?**
O: Konto nigdy nie bylo analizowane LUB ma zero quality sources.

**P: Co robic jak konto ma TB5?**
O: Konto wymaga przeniesienia na inne urzadzenie. TB5 oznacza maksymalny poziom trust-boost.

**P: Jak dodac nowe sources?**
O: Actions → Find Sources (wymaga HikerAPI Key w Settings). Lub recznie edytuj sources.txt.

**P: Gdzie sa logi OH?**
O: `%APPDATA%\OH\logs\oh.log` — rotacja co 2 MB, max 5 plikow.

**P: Czy moge uzywac OH jednoczesnie z botem?**
O: Tak. OH otwiera pliki bota w trybie read-only. Jedyna modyfikacja to sources.txt (z backupem).

**P: Jak zmienic motyw na jasny?**
O: Settings → Theme → "light" → Save.

---

## 16. Ankieta dla zespolu

Prosimy o odpowiedzi na ponizsze pytania. Pomoga nam rozwijac OH w kierunku, ktory najbardziej pomaga w codziennej pracy.

### Ogolne

1. Jak czesto korzystasz z OH? (codziennie / kilka razy w tygodniu / rzadko)
2. Ktore funkcje uzywasz najczesciej? (Cockpit / Session Report / Rekomendacje / Sources / Panel szczegolowy / inne)
3. Czy cos jest niejasne lub trudne do znalezienia w interfejsie?
4. Ile czasu zajmuje Ci codzienny przeglad kont? Czy OH go przyspieszyl?

### Przydatnosc funkcji

5. Czy Cockpit na poczatku zmiany daje Ci wystarczajacy obraz sytuacji? Czego brakuje?
6. Czy rekomendacje sa trafne? Czy zdarzaja sie falszywe alarmy?
7. Czy panel szczegolowy konta (drawer) daje Ci wszystkie informacje potrzebne do review? Czego brakuje?
8. Czy alerty w panelu konta pomagaja w podejmowaniu decyzji? Jakie dodatkowe alerty bylyby przydatne?
9. Czy Session Report jest czytelny? Ktore sekcje sa najbardziej / najmniej uzyteczne?

### Zarzadzanie sources

10. Jak czesto usuwasz / dodajesz sources? Czy proces jest wygodny?
11. Czy uzywasz "Find Sources"? Czy wyniki sa trafne?
12. Czy brakuje Ci jakiejs informacji o sources (np. wiek, historia zmian, trend FBR)?
13. Czy "Bulk Delete Weak Sources" jest przydatne? Czy prog FBR jest odpowiedni?

### Brakujace funkcje

14. Jakie informacje chcialbyś widziec w OH, ktorych teraz nie ma?
15. Jakie akcje chcialbyś wykonywac z OH, ktore teraz wymagaja recznej pracy?
16. Czy potrzebujesz eksportu danych (PDF, Excel, CSV)? Jakich danych?
17. Czy chcialbyś widziec trendy / wykresy (np. FBR w czasie, follow/like dziennie)?
18. Czy chcialbyś porownywac konta miedzy soba (np. konto A vs konto B)?
19. Czy brakuje Ci powiadomien / alertow push (np. "konto X zablokowane")?

### Workflow

20. Opisz swoj typowy workflow przegladu kont krok po kroku. Co robisz najpierw, potem, na koncu?
21. Ktore czynnosci sa najbardziej czasochlonne lub frustrujace?
22. Czy jest cos, co robisz recznie, a mogloby byc zautomatyzowane?
23. Czy pracujesz z innymi operatorami jednoczesnie? Czy potrzebujesz wspoldzielenia danych lub notatek?

### Priorytetyzacja

24. Gdybyś mogl dodac JEDNA nowa funkcje do OH, co by to bylo?
25. Oceń waznosc (1-5) nastepujacych potencjalnych funkcji:
    - [ ] Trendy FBR w czasie (wykresy)
    - [ ] Porownywanie kont
    - [ ] Eksport raportow (PDF/Excel)
    - [ ] Automatyczny skan co X minut
    - [ ] Historia sources per konto (timeline)
    - [ ] Powiadomienia push o problemach
    - [ ] Widok urzadzen (ile kont, status, obciazenie)
    - [ ] Bulk akcje (zaznacz wiele kont → TB+1 dla wszystkich)
    - [ ] Notatki operatorskie per konto (poza review)
    - [ ] Integracja z komunikatorem (Slack/Teams)

### Uwagi koncowe

26. Co Ci sie najbardziej podoba w OH?
27. Co Ci sie najmniej podoba lub przeszkadza?
28. Inne uwagi, pomysly, sugestie:

---

*Dziekujemy za wypelnienie ankiety! Twoja opinia bezposrednio wplywa na rozwoj OH.*
