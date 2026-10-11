# Metodologia 1.0.0

RegionComparison porównuje pełne gminy województwa dolnośląskiego. Wynik porównawczy do dalszej analizy wskazuje jednostki do pogłębionego badania, a nie popyt, ryzyko ani rekomendację inwestycyjną.

## Zakres i definicje

Przyjęto lata 2023–2025 po zmianie źródła danych opieki z OD-1 na administracyjne MRPiPS/RKZ 4G. Kategorie wieku 0–2 wykluczają trzylatków. Ludność i opieka przedstawiają stan końca roku. Liczba dzieci w placówkach zachowuje źródłowe znaczenie, może obejmować dzieci starsze niż 2 lata i nie jest liczbą mieszkańców gminy korzystających z opieki. Placówki znajdują się w gminie, a użytkownicy mogą mieszkać poza nią.

Dokładne ID, oryginalne nazwy, ścieżki tematyczne, jednostki i źródła zapisano w `config/indicators.yml` oraz definicjach snapshotu. Nie łączymy starszych serii obejmujących oddziały żłobkowe z obecnymi seriami.

## Miary pochodne

- Udział dzieci 0–2 [%] = 100 × dzieci 0–2 (453372) / ludność ogółem (453371).
- Miejsca na 1000 dzieci 0–2 = 1000 × miejsca ogółem w żłobkach i klubach (1649554) / dzieci 0–2 (453372).
- Placówki [obiekt] = żłobki (377234) + kluby dziecięce (377225), wyłącznie gdy oba składniki są dopuszczalne.

Brak dowolnego wymaganego wejścia oznacza brak miary; nie interpolujemy. Mianownik równy zero daje brak ilorazu z przyczyną `zero_denominator`. Zero miejsc przy dodatniej populacji daje poprawne zero. Wartości ponad 1000 pozostają widoczne: nie oznaczają odsetka konkretnych dzieci z zapewnioną opieką. Gotowy wskaźnik GUS 1649860 służy kontroli zgodności; rzeczywiste odpowiedzi pokazują liczby całkowite. Tolerancja wynosi 0,500000001 miejsca/1000, odpowiadająca zaokrągleniu do jednostki z minimalnym marginesem numerycznym.

## Stały zbiór odniesienia

Dla snapshotu, roku i wersji metodologii zamrażamy listę gmin z kompletem: miejsca na 1000 oraz udział dzieci 0–2. Lista obejmuje cały region i nie zależy od wybranych 2–4 gmin ani wag. Brak dodatkowej cechy profilu nie blokuje oceny. Waga zero nie przywraca gminy z brakującą wymaganą miarą. Wynik i rangi pozostają puste przy mniej niż dwóch kwalifikowanych jednostkach.

## Normalizacja i wagi

Dla N > 1: p = (średnia ranga − 1) / (N − 1). Remisy mają średnią rangę. Niższa podaż względna i wyższy udział małych dzieci oznaczają większy percentyl sygnału do badania. Stała składowa otrzymuje 0,5 i informację, że nie różnicuje regionu.

Wynik = 100 × Σ(w × p). Bazowo obie wagi wynoszą 0,5. Dowolne nieujemne skończone wagi o dodatniej sumie są normalizowane do sumy 1. Wagi są decyzją demonstracyjną; wynik nie jest procentem niezaspokojonych potrzeb ani prawdopodobieństwem. Surowe miary, percentyle i wkłady są jawne.

## Remisy i wrażliwość

Wynik zaokrąglamy deterministycznie do 6 miejsc dziesiętnych (`pandas.round`, zaokrąglenie połówek do parzystej). Remis zachowuje przedział zajętych miejsc [rank_min, rank_max]. Nazwa i kod służą prezentacji, nie rozstrzygają remisu analitycznie.

Wrażliwość zmienia wyłącznie wagi. Dane, kwalifikacja i percentyle pozostają stałe. Siatka wag co 0,1 o sumie 1 zawiera 11 wariantów dla dwóch składowych, łącznie z presetami 0,8/0,2, 0,2/0,8 i bazą 0,5/0,5. Dokładny scenariusz użytkownika jest dodawany, jeśli nie należy do siatki. Duplikaty są usuwane. Zakres pozycji obejmuje minimalne rank_min i maksymalne rank_max, również przy remisach. Porównania parami liczą warianty wyżej/niżej/remis; ich udziały nie są prawdopodobieństwami. Nie nadajemy arbitralnej etykiety stabilności.

## Jakość i ograniczenia

Eksport JSON ma schemat 1.1 i kontrakt wykonywanej metodologii 1.0.0. Replay sprawdza
definicje źródłowe i pochodne, atrybuty, kierunki, normalizację, precyzję, remisy, wagi,
zakres, rok oraz odciski danych i kohorty. Zmiana nieobsługiwanej reguły albo wersji kończy
się błędem. Formuły YAML są sprawdzane względem kodu Python, nigdy wykonywane przez eval.
Nieznany lub zmodyfikowany kontrakt nie może po cichu zmienić interpretacji wyniku.

Raporty rozróżniają brak i rzeczywiste zero. Procentowa zmiana przy zerowym roku bazowym
jest niewyznaczalna; brak lub atrybut nieporównywalności w środku szeregu oznacza niepełny
trend także wtedy, gdy oba końce mają wartości. Liczby wykluczonych gmin wynikają z danych
konkretnego roku. Przekroczenia tolerancji wskaźnika GUS są zgłaszane do wyjaśnienia,
bez uznawania jednej serii za automatycznie poprawną i bez imputacji.

Zachowujemy raw_value, raw_attr_id, semantic_value, status i powód. Atrybuty braku/ochrony, progu prezentacji, metodologii i zakresu blokują ocenę zgodnie ze słownikiem. Nieznany atrybut nie jest poprawną wartością. Nie przypisujemy komórce dokładniejszej przyczyny niż ujawnia GUS. Zmiana percentyla pomiędzy latami nie jest bezpośrednią zmianą sytuacji, bo normalizację wykonujemy dla każdego roku osobno. Trendy przedstawiają rzeczywiste miary; braków nie łączymy linią.

Brakuje danych o cenach, kolejkach, dojazdach, preferencjach rodziców i przepływach między gminami. Sama liczba miejsc nie dowodzi dostępności dla konkretnej rodziny. Kolejne badanie powinno sprawdzić te czynniki oraz dopasowanie godzin działania placówek do pracy rodziców.
