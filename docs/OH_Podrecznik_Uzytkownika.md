# OH — Operational Hub
# Podrecznik uzytkownika v1.3.0

> Wersja: Kwiecien 2026 | Dotyczy: OH.exe (najnowsza wersja)

---

## Spis tresci

1. [Co to jest OH?](#1-co-to-jest-oh)
2. [Instalacja i pierwsze uruchomienie](#2-instalacja-i-pierwsze-uruchomienie)
3. [Przeglad interfejsu](#3-przeglad-interfejsu)
4. [Zakladka Accounts (Konta)](#4-zakladka-accounts)
5. [Panel szczegolowy konta](#5-panel-szczegolowy-konta)
6. [Zakladka Sources (Zrodla)](#6-zakladka-sources)
7. [Zakladka Source Profiles](#7-zakladka-source-profiles)
8. [Zakladka Fleet (Flota)](#8-zakladka-fleet)
9. [Cockpit — podglad operacyjny](#9-cockpit--podglad-operacyjny)
10. [Session Report — raport sesji](#10-session-report)
11. [Rekomendacje](#11-rekomendacje)
12. [Zarzadzanie sources](#12-zarzadzanie-sources)
13. [Target Splitter — dystrybucja sources](#13-target-splitter--dystrybucja-sources)
14. [Settings Copier — kopiowanie ustawien miedzy kontami](#14-settings-copier--kopiowanie-ustawien-miedzy-kontami)
15. [Auto-Fix — propozycje napraw](#15-auto-fix--propozycje-napraw)
16. [Akcje operatora](#16-akcje-operatora)
17. [Ustawienia](#17-ustawienia)
18. [System auto-aktualizacji](#18-system-auto-aktualizacji)
19. [Skroty klawiaturowe](#19-skroty-klawiaturowe)
20. [Dane i bezpieczenstwo](#20-dane-i-bezpieczenstwo)
21. [FAQ](#21-faq)

---

## 1. Co to jest OH?

OH (Operational Hub) to desktopowy panel operacyjny do zarzadzania kampaniami Onimator. Laczy sie z folderem bota i daje operatorom jedno centrum kontroli:

- **Monitoring kont** — status, aktywnosc, health score, analiza FBR
- **Zarzadzanie sources** — sledzenie jakosci, operacje masowe, inteligentne wyszukiwanie
- **Monitoring sesji** — dzienne follow/like/DM/unfollow per konto
- **Akcje operatora** — flagi review, tagi TB/limits, audit trail
- **Rekomendacje** — automatyczne sugestie posortowane wg priorytetu
- **Zarzadzanie flota** — metryki per urzadzenie
- **Operacje dzienne** — Cockpit i Session Report na poczatek zmiany

OH **nigdy nie modyfikuje** plikow runtime bota poza `sources.txt` (zawsze z backupem) i `settings.db` (tylko przez Settings Copier, zawsze z backupem).

---

## 2. Instalacja i pierwsze uruchomienie

### Wymagania systemowe
- Windows 10 lub 11 (64-bit)
- Brak dodatkowego oprogramowania — OH to samodzielny plik .exe

### Instalacja

1. Skopiuj **folder OH** na pulpit (lub dowolna lokalizacje)
2. Kliknij dwukrotnie **START.bat** aby uruchomic
   - START.bat automatycznie sprawdza aktualizacje przed uruchomieniem
   - Jesli jest nowa wersja, pobiera i instaluje ja automatycznie
3. Przy pierwszym uruchomieniu OH tworzy baze danych w `%APPDATA%\OH\oh.db`

### Pierwsze uruchomienie

1. **Wpisz sciezke do Onimatora** — w gornym pasku wpisz pelna sciezke do folderu bota
2. Kliknij **Save**
3. Kliknij **Scan & Sync** — OH wykryje wszystkie urzadzenia i konta
4. Kliknij **Analyze FBR** — obliczy metryki jakosci sources
5. Otworz **Cockpit** aby zobaczyc podglad operacyjny

### Opcjonalna konfiguracja (zakladka Settings)

- **HikerAPI Key** — wymagany do funkcji Find Sources
- **Gemini API Key** — opcjonalny, wlacza AI scoring
- **Progi FBR** — dostosuj progi jakosci (domyslnie: min 100 follows, min 10% FBR)
- **Auto-Scan** — wlacz automatyczne Scan & Sync co X godzin

---

## 3. Przeglad interfejsu

![Glowny interfejs OH — zakladka Accounts](screenshots/01_accounts_tab.png)

Interfejs OH sklada sie z:

1. **Pasek marki** (gora) — branding Wizzysocial, przycisk "Check for Updates", wersja buildu
2. **Pasek Onimator Path** — sciezka do folderu bota
3. **Zakladki** — Accounts, Sources, Source Profiles, Fleet, Settings
4. **Pasek narzedzi** — przyciski akcji (Cockpit, Scan & Sync, Analyze FBR, itd.)
5. **Pasek filtrow** — status, FBR, urzadzenie, szukaj, tagi, aktywnosc
6. **Tabela danych** — glowna zawartosc z sortowalnymi kolumnami
7. **Pasek statusu** — biezace komunikaty

---

## 4. Zakladka Accounts

Zakladka Accounts to glowny widok. Pokazuje wszystkie konta bota w tabeli.

### Kolumny tabeli

| Kolumna | Opis |
|---------|------|
| **Username** | Nazwa konta Instagram |
| **Device** | Telefon/urzadzenie (z wskaznikiem online) |
| **Hours** | Slot godzinowy (np. 0-6, 6-12, 12-18, 18-24) |
| **Status** | Active lub Removed |
| **Tags** | Tagi bota i operatora (TB, limits, SLAVE, itd.) |
| **Follow/Unfollow** | Czy follow/unfollow wlaczony (Yes/No) |
| **Follow Today / Like Today** | Dzisiejsze follow i like |
| **Follow Limit / Like Limit** | Skonfigurowane limity dzienne |
| **Review** | Wskaznik flagi review |
| **Data DB / Sources.txt** | Czy kluczowe pliki istnieja |
| **Active Sources** | Liczba aktywnych sources |

### Filtry

| Filtr | Opcje | Zastosowanie |
|-------|-------|-------------|
| **Status** | Active / Removed / All | Domyslnie "Active only" |
| **FBR** | All / Needs attention / Never analyzed / Errors / No quality / Has quality | Szukanie kont do pracy |
| **Device** | Lista urzadzen | Filtrowanie po telefonie |
| **Search** | Wpisz username | Szybkie znalezienie konta |
| **Tags** | All / TB / limits / SLAVE / START / PK | Filtrowanie po tagach |
| **Activity** | All / 0 actions / Has actions | Konta bez aktywnosci |
| **Group** | Wszystkie / konkretna grupa | Filtrowanie po grupie |
| **Review only** | Checkbox | Tylko oflagowane konta |
| **Clear** | Przycisk | Resetuje wszystkie filtry |

### Przyciski na pasku narzedzi

| Przycisk | Funkcja |
|----------|---------|
| **Cockpit** | Podglad operacyjny |
| **Scan & Sync** | Skanuj folder bota i synchronizuj |
| **Analyze FBR** | Analizuj FBR dla wszystkich kont |
| **Refresh** | Odswiez tabele z bazy |
| **Session** | Raport sesji |
| **Recs** | Rekomendacje |
| **History** | Historia akcji operatora |
| **Export CSV** | Eksport do CSV |
| **Groups** | Zarzadzanie grupami kont |

### Operacje masowe

Zaznacz wiele kont (Ctrl+Klik lub Shift+Klik), nastepnie uzyj paska akcji masowych:
- **Set/Clear Review** dla wszystkich zaznaczonych
- **TB +1 / Limits +1** dla wszystkich
- **Add to Group / Remove from Group**
- **Bulk Find Sources**

### Menu Actions

Kliknij **Actions** w wierszu konta:
- **Open Folder** — otworz folder konta w Explorerze
- **View Sources** — podglad sources z FBR
- **Find Sources** — szukanie nowych sources (wymaga HikerAPI)
- **Copy Settings From This Account** — otworz kreator Settings Copier z tym kontem jako zrodlem (patrz [Sekcja 14](#14-settings-copier--kopiowanie-ustawien-miedzy-kontami))
- **Set/Clear Review** — oflaguj konto
- **TB +1 / Limits +1** — zwieksz poziom
- **Trends** — trendy historyczne konta

---

## 5. Panel szczegolowy konta

Kliknij konto w tabeli, nastepnie nacisnij **Spacje** aby otworzyc panel po prawej stronie.

### Zakladka Summary

**Karty wydajnosci (4 kolorowe kafelki):**

| Karta | Pokazuje | Kiedy czerwona |
|-------|----------|----------------|
| **Today's Activity** | Follow/Like/DM dzisiaj vs limity | 0 akcji w aktywnym slocie |
| **FBR Status** | Quality sources, best FBR% | Brak quality sources |
| **Source Health** | Liczba aktywnych sources | 0 sources lub < 5 |
| **Account Health** | TB i Limits | TB >= 4 lub Limits >= 4 |

### Zakladka Alerts

Automatycznie generowane problemy:
- **CRITICAL** (czerwone) — np. 0 akcji, TB5
- **HIGH** (pomaranczowe) — np. TB4, brak sources
- **MEDIUM** (niebieskie) — np. niski follow
- **LOW** (szare) — np. nigdy nie analizowano FBR

Kazdy alert: tytul, szczegoly, zalecana akcja, przycisk akcji.

---

## 6. Zakladka Sources

![Zakladka Sources — 10,273 sources z metrykami FBR](screenshots/04_sources_tab.png)

Globalny podglad wszystkich sources ze wszystkich kont:

| Kolumna | Opis |
|---------|------|
| **Source** | Nazwa profilu Instagram |
| **Active Accs** | Ile kont aktualnie uzywa tego source |
| **Total Follows** | Laczna liczba follows |
| **Followbacks** | Laczna liczba followbackow |
| **Avg FBR %** | Sredni Follow-Back Rate |
| **Wtd FBR %** | Wazony FBR (konta z wiekszymi danymi maja wieksza wage) |
| **Quality** | Ile kont ma "quality" dla tego source |

**Kliknij source** aby zobaczyc rozklad per konto w dolnym panelu.

### Akcje

- **Refresh Sources** — przeladuj dane
- **Delete Source** — usun wybrany source
- **Bulk Delete Weak Sources** — usun sources ponizej progu FBR
- **Distribute Sources** — otworz kreator Target Splitter do dystrybucji sources na konta (patrz [Sekcja 13](#13-target-splitter--dystrybucja-sources))
- **History** — historia usuniec/przywrocen
- **Bulk Find Sources** — wyszukaj nowe sources masowo

---

## 7. Zakladka Source Profiles

![Source Profiles — 36 zindeksowanych profili w 8 niszach](screenshots/05_source_profiles_tab.png)

Zindeksowane profile sources z klasyfikacja niszy:
- **Nisza** — kategoria (fitness, fashion, photography, business, itd.)
- **Pewnosc %** — pewnosc klasyfikacji
- **Jezyk** — wykryty jezyk profilu
- **Lokalizacja** — lokalizacja profilu
- **Followers** — liczba obserwujacych
- **Metryki FBR** — Avg FBR%, Wtd FBR%, Quality

### Indeksowanie sources

Settings > Source Indexing > **Scan & Index Sources** (wymaga HikerAPI Key)

---

## 8. Zakladka Fleet

![Fleet Dashboard — 44 urzadzen, 132 aktywne konta](screenshots/06_fleet_tab.png)

Podglad calej floty urzadzen:

| Kolumna | Opis |
|---------|------|
| **Device** | Nazwa urzadzenia |
| **Status** | Online/Offline |
| **Accounts** | Laczna liczba kont |
| **Active %** | Procent aktywnych |
| **Avg Health** | Sredni health score |
| **Avg FBR%** | Sredni FBR |
| **Avg Sources** | Srednia liczba sources |
| **Review** | Konta oflagowane |

Kliknij urzadzenie aby zobaczyc jego konta w dolnym panelu.

---

## 9. Cockpit — podglad operacyjny

Punkt startowy na poczatek kazdej zmiany.

**Jak otworzyc:** Kliknij **Cockpit** na pasku narzedzi.

![Cockpit — 132 konta, 9 CRITICAL, 57 HIGH](screenshots/08_cockpit.png)

### 5 sekcji

| Sekcja | Co pokazuje |
|--------|-------------|
| **Do zrobienia teraz** | Najpilniejsze problemy (CRITICAL/HIGH) |
| **Konta do review** | Oflagowane konta czekajace na przeglad |
| **Top rekomendacje** | Najwazniejsze zalecenia |
| **Ostatnie source actions** | Ostatnie operacje na sources |
| **Dzisiaj wykonano** | Akcje zespolu dzisiaj |

### Zalecany workflow dzienny

1. Kliknij **Scan & Sync** aby pobrac swieze dane
2. Otworz **Cockpit** — zobacz przeglad
3. Przejdz po kolei **"Do zrobienia teraz"** od gory
4. Sprawdz oflagowane konta w **"Konta do review"**
5. Jesli potrzeba — otworz **Session Report**

---

## 10. Session Report

Szczegolowa analiza dzisiejszej aktywnosci bota.

**Jak otworzyc:** Kliknij **Session** na pasku narzedzi.

![Session Report — 132 aktywne konta, 68 z aktywnoscia](screenshots/09_session_report.png)

### 8 zakladek analizy

| Zakladka | Pokazuje | Typowa akcja |
|----------|---------|-------------|
| **Actions** | Zbiorczy checklist wg priorytetu | Przejdz od CRITICAL |
| **0 Actions** | Konta bez aktywnosci | Sprawdz urzadzenie |
| **Devices** | Urzadzenia offline | Sprawdz telefon |
| **Review** | Konta z review | Przejrzyj, wyczysc lub eskaluj |
| **Low Follow** | Niski follow | Sprawdz warmup, sources |
| **Low Like** | Niski like | Sprawdz konfiguracje |
| **TB** | Konta z trust-boost | TB+1, warmup |
| **Limits** | Konta z limits | Limits+1, wymiana sources |

### Zalecenia warmupu TB

| Poziom | Follow/dzien | Like/dzien | Akcja |
|--------|-------------|-----------|-------|
| TB1 | 5-10 | 10-20 | Lekki warmup |
| TB2 | 15-25 | 30-50 | Umiarkowany warmup |
| TB3 | 30-45 | 50-80 | Normalna praca |
| TB4 | 50-70 | 80-120 | Pelna praca, monitoruj |
| TB5 | — | — | Przenies konto na inne urzadzenie |

Przycisk **"Copy Report to Clipboard"** kopiuje raport do schowka.

---

## 11. Rekomendacje

Automatyczna analiza kont i sources z priorytetyzowanymi sugestiami.

**Jak otworzyc:** Kliknij **Recs** na pasku narzedzi.

![Rekomendacje — 358 pozycji, posortowane wg priorytetu](screenshots/10_recommendations.png)

### 6 typow rekomendacji

| Typ | Problem | Akcja |
|-----|---------|-------|
| **Weak Source** | Source z niskim FBR | Usun lub wymien |
| **Source Exhaustion** | Za malo sources | Dodaj nowe |
| **Low Like** | Zero like mimo aktywnosci | Sprawdz konfiguracje |
| **Limits Max** | Limits level 5 | Wymien sources |
| **TB Max** | TB level 5 | Przenies konto |
| **Zero Actions** | Brak aktywnosci | Sprawdz urzadzenie |

### Priorytety

- **CRITICAL** (czerwone) — natychmiastowa akcja
- **HIGH** (pomaranczowe) — do zrobienia dzisiaj
- **MEDIUM** (niebieskie) — gdy bedzie czas
- **LOW** (szare) — informacyjne

---

## 12. Zarzadzanie sources

### Usuwanie sources

**Pojedynczo:** Sources > zaznacz > "Delete Source"
**Masowo:** "Bulk Delete Weak Sources" > ustaw prog > podglad > potwierdz
**Per konto:** Actions > View Sources > "Delete Selected"

Kazde usuniecie tworzy **backup** i jest zapisywane w **historii**.

### Przywracanie

Sources > **History** > zaznacz operacje > **Revert Selected**

### Szukanie nowych sources

Wymaga HikerAPI Key. Actions > **Find Sources** > OH wyszukuje podobne profile > zaznacz > **Add Selected**

---

## 13. Target Splitter — dystrybucja sources

Target Splitter umozliwia dystrybucje zestawu sources na wiele kont w jednej operacji. Zamiast recznej edycji kazdego pliku sources.txt, wybierasz sources, wskazujesz konta docelowe, wybierasz strategie dystrybucji, podgladasz plan i zatwierdzasz.

### Jak uzyskac dostep

**Zakladka Sources** > kliknij **"Distribute Sources"** na pasku narzedzi.

Jesli zaznaczysz sources w tabeli przed kliknieciem, zostana one automatycznie wpisane do kreatora.

### Kreator 3-krokowy

#### Krok 1: Wybierz sources

Wklej lub wpisz nazwy sources w pole tekstowe, po jednym w linii. Duplikaty i puste linie sa automatycznie usuwane. Etykieta pod polem pokazuje ile prawidlowych sources zostalo wykrytych.

Kliknij **"Next >"** aby kontynuowac (nieaktywny do momentu wpisania co najmniej jednego source).

#### Krok 2: Wybierz konta docelowe

Tabela pokazuje wszystkie aktywne konta z ich username, urzadzeniem, grupa i liczba aktywnych sources. Uzyj filtrow u gory aby zawezic po urzadzeniu, grupie lub wyszukaj po nazwie.

- **Select All / Deselect All** — zaznacz/odznacz wszystkie widoczne konta
- Etykieta pokazuje ile kont jest zaznaczonych
- Kliknij **"Next >"** aby kontynuowac (nieaktywny do momentu zaznaczenia co najmniej jednego konta)

#### Krok 3: Podglad i zastosowanie

Wybierz strategie dystrybucji i przejrzyj plan przed zastosowaniem.

**Dwie strategie:**

| Strategia | Jak dziala |
|-----------|-----------|
| **Even split** (rowny podzial) | Rozdziela sources metoda round-robin. Kazde konto dostaje w przyblizeniu taka sama liczbe nowych sources. |
| **Fill up** (wypelnianie) | Przypisuje kazdy source do konta z najmniejsza liczba aktywnych sources. Priorytetowo traktuje konta najbardziej potrzebujace sources. |

Zmiana strategii natychmiast przelicza podglad.

Tabela podgladu pokazuje kazde przypisanie source-konto ze statusem:
- **"Will add"** (zielony) — source zostanie dopisany do sources.txt tego konta
- **"Already present"** (szary) — source juz istnieje w tym koncie, zostanie pominiety

Podsumowanie pokazuje: laczna liczba sources, kont, ile zostanie dodanych, ile juz istnieje i srednia sources na konto.

Kliknij **"Apply"** aby wykonac. Przed modyfikacja plikow pojawia sie dialog potwierdzenia. Po wykonaniu dialog pokazuje wynik: ile dodano, pominieto i ile sie nie powiodlo.

### Bezpieczenstwo

- **Podglad przed wykonaniem** — widzisz dokladny plan zanim cokolwiek zostanie zapisane
- **Backup** — sources.txt.bak jest tworzony przed kazda modyfikacja
- **Duplikaty pomijane** — sources juz obecne w koncie nie sa ponownie dodawane
- **Izolacja bledow** — blad w jednym koncie nie przerywa calej operacji
- **Audit trail** — kazda zmiana jest logowana w Historii Akcji Operatora

---

## 14. Settings Copier — kopiowanie ustawien miedzy kontami

Settings Copier umozliwia kopiowanie konfiguracji bota (limity follow/like, godziny pracy, ustawienia DM) z jednego konta na jedno lub wiele kont docelowych. Zastepuje koniecznosc otwierania konfiguracji Onimatora osobno dla kazdego konta.

### Jak uzyskac dostep

**Zakladka Accounts** > kliknij przycisk **Actions** przy wybranym koncie > **"Copy Settings From This Account"**.

Kreator otwiera sie z wybranym kontem jako zrodlem.

### Jakie ustawienia mozna skopiowac

| Ustawienie | Opis |
|------------|------|
| Follow limit / day | Dzienny limit follow |
| Like limit / day | Dzienny limit like |
| Unfollow limit / day | Dzienny limit unfollow |
| Working hours — start | Poczatek slotu godzinowego |
| Working hours — end | Koniec slotu godzinowego |
| Follow enabled | Czy follow jest wlaczony |
| Unfollow enabled | Czy unfollow jest wlaczony |
| Like enabled | Czy like jest wlaczony |
| DM enabled | Czy DM jest wlaczony |
| DM limit / day | Dzienny limit DM |

### Kreator 3-krokowy

#### Krok 1: Wybierz konto zrodlowe i ustawienia

Wybierz konto zrodlowe z listy rozwijanej. OH odczytuje jego settings.db i wyswietla wszystkie mozliwe do skopiowania ustawienia z aktualnymi wartosciami. Kazde ustawienie ma checkbox — odznacz te, ktorych nie chcesz kopiowac.

Kliknij **"Next >>"** aby kontynuowac (nieaktywny do momentu wybrania konta i zaznaczenia co najmniej jednego ustawienia).

#### Krok 2: Wybierz konta docelowe + podglad roznic

Wszystkie aktywne konta (oprocz zrodlowego) sa wyswietlone z checkboxami. Kazdy wiersz pokazuje ile ustawien ulegloby zmianie.

- **Select All / Select None** — zaznacz/odznacz wszystkie
- **Select Same Device** — zaznacz tylko konta na tym samym urzadzeniu co zrodlo
- Konta z 0 roznicami sa wyszarzone (identyczna konfiguracja)

Kliknij dowolne konto docelowe aby zobaczyc porownanie w tabeli podgladu ponizej. Zmienione wartosci sa pogrubione. Niezmienione wartosci sa wyszarzone.

Kliknij **"Apply to N account(s)"** aby kontynuowac. Pojawia sie dialog potwierdzenia: "Apply N setting(s) to M account(s)? A backup of each settings.db will be created before writing."

#### Krok 3: Wyniki

Po wykonaniu dialog pokazuje podsumowanie: ile kont zostalo zaktualizowanych pomyslnie i ile sie nie powiodlo. Tabela wynikow wymienia kazde konto docelowe ze statusem (OK lub FAILED) i liczba zmienionych kluczy.

### Bezpieczenstwo backupu

Przed zapisem do settings.db kazdego konta, OH tworzy pelny backup pliku (`settings.db.bak`). OH stosuje metode read-modify-write: odczytuje istniejaca konfiguracje, aktualizuje tylko wybrane klucze i zapisuje calosc z powrotem. Inne ustawienia nienalezace do operacji kopiowania nie sa nigdy modyfikowane.

Jesli bot jest uruchomiony i plik settings.db jest zablokowany, OH raportuje blad dla tego konkretnego konta i kontynuuje z pozostalymi.

### Wazne informacje

- OH zapisuje **tylko** do pola `settings` JSON w tabeli `accountsettings` — zadne inne tabele ani pola nie sa modyfikowane
- To jedyna funkcja w OH ktora zapisuje do plikow settings.db
- Kazda zmiana jest logowana w Historii Akcji Operatora ze starymi i nowymi wartosciami

---

## 15. Auto-Fix — propozycje napraw

OH moze automatycznie wykrywac typowe problemy po kazdym Scan & Sync i prezentowac je jako propozycje do przejrzenia. Nic nie jest wykonywane bez Twojej wyraznej zgody.

### Jak dziala

1. Po zakonczeniu **Scan & Sync** OH uruchamia detekcje na wszystkich kontach
2. Jesli wykryto problemy, pojawia sie dialog **Auto-Fix Proposals**
3. Kazda propozycja jest wyswietlona w tabeli z priorytetem, typem, celem i opisem
4. Przegladasz propozycje, zaznaczasz te ktore chcesz zastosowac i klikasz **"Apply Selected"**
5. Jesli klikniesz **"Skip All"**, zadne zmiany nie zostana wprowadzone

### Typy propozycji

| Typ | Priorytet | Co wykrywa | Co robi po zatwierdzeniu |
|-----|-----------|------------|--------------------------|
| **Remove Weak Source** | HIGH | Sources z bardzo niskim wFBR (ponizej progu) | Usuwa source z plikow sources.txt dotkietych kont |
| **Escalate TB** | MEDIUM | Konta z zerowa aktywnoscia przez 2+ dni | Zwieksza poziom TB o 1 |
| **Dead Device Alert** | INFO | Urzadzenia z zerowa aktywnoscia dzisiaj | Tylko informacja — brak akcji, tylko alert |
| **Remove Duplicates** | LOW | Zduplikowane wpisy w sources.txt konta | Usuwa zduplikowane linie |

### Kontrolki dialogu

- **Checkboxy** — kazda propozycja z mozliwoscia akcji ma checkbox. Propozycje HIGH sa domyslnie zaznaczone, LOW odznaczone.
- **Select All / Deselect All** — szybkie zaznaczanie/odznaczanie
- **Apply Selected** — wykonuje tylko zaznaczone propozycje (wymaga potwierdzenia)
- **Skip All** — zamyka dialog bez wykonywania czegokolwiek
- Propozycje informacyjne (Dead Device Alert) sa wyswietlane z ikona info zamiast checkboxa

### Konfiguracja detekcji

W **Ustawieniach**, sekcja Auto-Fix kontroluje ktore typy propozycji sa wykrywane:
- "Detect weak sources after Scan"
- "Detect TB escalation candidates"
- "Detect offline devices"
- "Detect duplicate sources"

Jesli wszystkie przelaczniki sa wylaczone, detekcja nie jest uruchamiana i dialog nie pojawia sie. Jesli detekcja sie uruchomi ale nie znajdzie problemow, dialog rowniez sie nie pojawia.

### Wyniki

Zatwierdzone propozycje sa logowane w tabeli `auto_fix_actions` i wyswietlane w Cockpicie w sekcji "Auto-Fix Results (operator-approved)".

---

## 16. Akcje operatora

### Review
- **Set Review** — oflaguj konto z notatka
- **Clear Review** — wyczysc flage po rozwiazaniu

### TB (Trust-Boost)
Poziomy TB1-TB5. **TB +1** zwieksza poziom. TB5 = przenies konto.

### Limits
Poziomy 1-5. **Limits +1** zwieksza poziom. Limits 5 = wymien sources.

### Grupy
Organizuj konta w grupy. **Groups** > tworzenie/zarzadzanie. Filtruj po grupie.

### Historia
**History** — pelny audit trail: kto, kiedy, co zmienil, stare/nowe wartosci, nazwa PC.

---

## 17. Ustawienia

![Zakladka Settings](screenshots/07_settings_tab.png)

| Grupa | Ustawienia |
|-------|-----------|
| **FBR Analysis** | Min follows (100), Min FBR% (10%) |
| **Source Cleanup** | Prog usuwania (5%), Min sources warning (5) |
| **Source Discovery** | Min sources do bulk discovery (10), Auto-add top N (5) |
| **Auto-Scan** | Wlacz/wylacz, interwal w godzinach |
| **Appearance** | Dark / Light theme |
| **API Keys** | HikerAPI Key, Gemini API Key |
| **Source Indexing** | Skanowanie i indeksowanie |
| **Source Blacklist** | Zarzadzanie czarna lista |
| **Campaign Templates** | Szablony kampanii |
| **Error Reporting** | Endpoint raportow, auto crash reports |

---

## 18. System auto-aktualizacji

OH automatycznie aktualizuje sie do najnowszej wersji.

### Jak dziala

**Przy uruchomieniu przez START.bat:**
1. START.bat sprawdza aktualizacje przed uruchomieniem OH
2. Jesli jest nowa wersja — pobiera i podmienia OH.exe automatycznie
3. Pobrany plik jest weryfikowany za pomoca sumy kontrolnej **SHA256** aby zapewnic integralnosc
4. Uruchamia zaktualizowana wersje

**W aplikacji:**
1. OH sprawdza aktualizacje automatycznie 3 sekundy po starcie
2. Jesli jest update — dialog z nowa wersja i changelogiem
3. "Download & Install" — pobierz i zainstaluj
4. Pobrany plik jest weryfikowany za pomoca **hasza SHA256** przed podmienieniem pliku wykonywalnego
5. OH zamyka sie, aplikuje update i restartuje

### Reczne sprawdzenie

Kliknij przycisk **"Check for Updates"** w prawym gornym rogu (widoczny z kazdej zakladki).

---

## 19. Skroty klawiaturowe

| Skrot | Kontekst | Akcja |
|-------|----------|-------|
| **Spacja** | Tabela kont | Otworz/zamknij panel szczegolowy |
| **Escape** | Panel / Dialog | Zamknij |
| **Lewo / Prawo** | Panel otwarty | Przelacz zakladki Summary/Alerts |
| **Gora / Dol** | Tabela kont | Nawiguj miedzy kontami |
| **Ctrl+R** | Dowolny widok | Odswiez |
| **Dwuklik** | Cockpit / Recs / Session | Przejdz do konta/source |

---

## 20. Dane i bezpieczenstwo

### Przechowywanie

- **Baza danych:** `%APPDATA%\OH\oh.db` (SQLite, WAL)
- **Logi:** `%APPDATA%\OH\logs\oh.log` (rotacja 2 MB x 5 plikow)
- Wszystkie dane sa przechowywane lokalnie

### Gwarancje bezpieczenstwa

- OH **nigdy nie modyfikuje** data.db ani plikow runtime bota
- OH zapisuje tylko do `sources.txt` (zarzadzanie sources) i `settings.db` (Settings Copier)
- Przed kazda zmiana sources.txt lub settings.db tworzony jest **backup** (`.bak`)
- Kazde usuniecie mozna **cofnac** z historii
- Wszystkie akcje operatora sa **logowane**
- Tagi operatora (OP:) sa **oddzielone** od tagow bota

### Dostep do sieci

OH laczy sie z internetem tylko w celu:
- **Sprawdzenia aktualizacji** — GitHub
- **HikerAPI** — tylko przy "Find Sources"
- **Gemini API** — tylko przy AI scoring (opcjonalnie)
- **Raporty bledow** — jesli skonfigurowane

Zadne dane kont nie sa nigdy wysylane na zewnatrz.

---

## 21. FAQ

**P: Czy OH moze zepsuc bota?**
O: Nie. OH modyfikuje tylko `sources.txt` (z backupem) i `settings.db` (tylko przez Settings Copier, z backupem).

**P: Jak cofnac usuniecie source?**
O: Sources > History > zaznacz > Revert Selected.

**P: Co robic z kontem TB5?**
O: Przenies na inne urzadzenie.

**P: Jak dodac nowe sources?**
O: Actions > Find Sources (wymaga HikerAPI Key).

**P: Gdzie sa logi?**
O: `%APPDATA%\OH\logs\oh.log`

**P: Jak zaktualizowac OH?**
O: Automatycznie przez START.bat lub przycisk "Check for Updates".

**P: Czy moge uzywac OH jednoczesnie z botem?**
O: Tak. OH otwiera pliki bota w trybie read-only. Jedyne zapisy to sources.txt i settings.db (z backupem).

**P: Jak zmienic motyw?**
O: Settings > Appearance > Theme > "light" > Save. Restart OH.

**P: Jak skopiowac ustawienia z jednego konta na wiele innych?**
O: Zakladka Accounts > Actions > "Copy Settings From This Account". Kreator pozwala wybrac ktore ustawienia skopiowac, wskazac konta docelowe, podejrzec roznice i zastosowac.

**P: Jak rozdzielic sources na wiele kont naraz?**
O: Zakladka Sources > "Distribute Sources". Wklej nazwy sources, wybierz konta docelowe, wybierz strategie (Even split lub Fill up), podejrzyj i zastosuj.

**P: Co sie stanie jesli pominie dialog Auto-Fix?**
O: Nic nie zostanie zmienione. Propozycje Auto-Fix to tylko sugestie. Klikniecie "Skip All" zamyka dialog bez zadnych modyfikacji.

**P: Czy Settings Copier modyfikuje pliki runtime bota?**
O: Tak, zapisuje do plikow settings.db. Backup (settings.db.bak) jest tworzony przed kazdym zapisem. To jedyna funkcja oprocz zarzadzania sources ktora modyfikuje pliki bota.

---

*OH — Operational Hub v1.3.0 | Wizzysocial*
