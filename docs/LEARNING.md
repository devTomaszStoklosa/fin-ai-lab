# Nauka

## Jak pracować

1. **Przed slice'em** zapisz hipotezę: co ma się poprawić i jak to zmierzysz.
2. **Najpierw baseline**, potem ulepszenia — każde osobno, z przebiegiem evala.
3. **Po slice'ie** dopisz wpis do dziennika poniżej: liczby, koszt, wnioski, następne pytanie.
4. Gdy technika nie pomaga, to też wynik. Zapisz go.

## Materiały

| Obszar | Materiał |
|---|---|
| Przekrój całości | Chip Huyen, „AI Engineering" (O'Reilly, 2025) |
| Prompty, API, tool use | dokumentacja Google Gemini API (ai.google.dev — prompt engineering, function calling, structured outputs); dokumentacja Anthropic (prompt engineering, tool use) jako materiał koncepcyjny, niezależny od providera; repo `anthropics/courses` na GitHubie |
| Evale | teksty Hamela Husaina o ewaluacji produktów LLM |
| RAG | Anthropic, „Contextual Retrieval" (2024); publikacja FinanceBench (Patronus AI) |
| Agenci | Anthropic, „Building effective agents" (2024); specyfikacja MCP (modelcontextprotocol.io) |
| Fine-tuning | LoRA (Hu i in., 2021); QLoRA (Dettmers i in., 2023); dokumentacja Hugging Face TRL i PEFT; dokumentacja Unsloth |
| Domena | dokumentacja SEC EDGAR i API XBRL; taksonomia US GAAP |

## Słownik

| Termin | Znaczenie |
|---|---|
| RAG | generowanie odpowiedzi na podstawie fragmentów wyszukanych w korpusie |
| Chunk | fragment dokumentu indeksowany osobno |
| Embedding | wektor reprezentujący znaczenie tekstu |
| BM25 | klasyczne wyszukiwanie po słowach kluczowych |
| Hybrid search | połączenie BM25 i wyszukiwania wektorowego |
| Reranker | model porządkujący kandydatów po trafności względem pytania |
| Contextual retrieval | doklejenie do chunka krótkiego kontekstu dokumentu przed indeksowaniem |
| recall@k, MRR | czy właściwy fragment jest w top-k; jak wysoko się pojawia |
| Faithfulness | czy odpowiedź wynika z dostarczonego kontekstu |
| Structured outputs | odpowiedź modelu wymuszona zgodnie ze schematem JSON |
| Tool use | model prosi aplikację o wywołanie funkcji i dostaje wynik |
| MCP | protokół udostępniania narzędzi i danych modelom |
| Workflow vs agent | ścieżka ustalona w kodzie vs ścieżka wybierana przez model |
| Orchestrator-workers | model dzieli zadanie i rozdaje je podwykonawcom |
| Evaluator-optimizer | jeden model ocenia, drugi poprawia, w pętli |
| Prompt caching | ponowne użycie przetworzonego prefiksu promptu — taniej i szybciej |
| Batch API | asynchroniczne przetwarzanie wielu żądań taniej |
| Effort | parametr sterujący głębią rozumowania i zużyciem tokenów |
| LLM-as-judge | model oceniający wyniki według rubryki |
| Golden set | zbiór przypadków z oczekiwanymi wynikami |
| LoRA / QLoRA | dostrajanie małych macierzy adapterów; QLoRA na skwantyzowanym modelu bazowym |
| Destylacja | uczenie małego modelu (student) na wynikach dużego (teacher) |
| DPO | dostrajanie na parach odpowiedzi lepsza / gorsza |
| Kwantyzacja (GGUF) | zapis wag w mniejszej precyzji do szybszej inferencji |
| Kappa Cohena | zgodność dwóch oceniających skorygowana o przypadek |
| Macro-F1 | średnia F1 po klasach, niezależna od liczebności klas |
| Look-ahead bias | test na danych, które model „zna" z przyszłości — tu: z danych treningowych |
| HHI | indeks koncentracji: suma kwadratów wag pozycji |
| VaR historyczny | strata nieprzekroczona z danym prawdopodobieństwem, liczona z historii |
| Max drawdown | największy spadek od szczytu do dołka |
| EARS | szablon zapisu wymagań („When…, the system shall…") |
| Zwrot ważony czasem (TWR) | zwrot liczony dzień po dniu z samego ruchu cen (i dywidend), bez wpływu wpłat, wypłat, zakupów i sprzedaży — porównywalny z indeksem |
| Total return | indeks albo kurs, który zawiera reinwestowane dywidendy (np. S&P 500 TR), w odróżnieniu od indeksu cenowego |

## Dziennik nauki

Wpis per ukończony slice. Najnowsze na górze.

```markdown
### RRRR-MM-DD — <ticket> / <slice>
- Hipoteza:
- Pomiar (metryka: baseline → wynik, n przypadków):
- Koszt (USD, tokeny, trafienia cache):
- Co zadziałało:
- Co nie zadziałało i dlaczego:
- Następne pytanie:
```

<!-- wpisy poniżej -->

### 2026-10-18 — #160 Bielik przerabia prompt zamiast odpowiadać
- Hipoteza: skoro model po kwantyzacji „echuje” instrukcję, a przez `transformers` odpowiada JSON-em, to winna jest llama.cpp (tokenizacja albo precyzja obliczeń). Okazało się, że nie — winny był trening.
- Pomiar: tokenizacja llama.cpp i `transformers` identyczna na 15/15 promptów; pamięć KV w f32 zamiast f16 nie zmienia zachowania. Za to tekst treningowy ma 659-705 tokenów, odpowiedź zaczyna się na tokenie 627-673, a `SFTConfig(max_length=512)` ucinał wszystko dalej — odpowiedź przetrwała w 0/13 policzonych przykładów. Eval po ponownym treningu jeszcze nie zrobiony (wymaga Colab).
- Koszt: 0 USD, bez wywołań LLM (lokalne przebiegi llama.cpp na CPU, ok. 1 min na prompt).
- Co zadziałało: zamiast dalej szukać w kodzie C++, sprawdzić, czego model w ogóle się uczył. Objaw (parafraza własnej instrukcji) był dokładnie tym, czego uczy trening na samym prompcie bez odpowiedzi.
- Co nie zadziałało i dlaczego: ucięcie w `SFTTrainer` jest ciche — żadnego ostrzeżenia, a odpowiedź siedzi na samym końcu tekstu, więc ginie pierwsza. Wynik z Colab (0/13 błędów schematu) zamaskował problem, bo model bazowy sam z siebie umiał wypisać JSON. Teraz notebook liczy tokeny przed treningiem i przerywa się, gdy coś by ucięło.
- Następne pytanie: czy po ponownym treningu skwantyzowany model odpowiada JSON-em bez pomocy gramatyki i czy macro-F1 wychodzi ponad 0?

### 2026-10-18 — #288 aktywo nienotowane: data zakupu i wyceny właściciela
- Hipoteza: złota moneta nie potrzebuje nowego typu aktywa. Ręczna pozycja już dziś nigdy nie bierze kursu z giełdy, brakuje jej tylko dnia zakupu i kilku znanych wartości w czasie. Kotwica wyceny (jedna znana wartość w jednym dniu) uogólnia się na listę takich wartości, a reszta aplikacji czyta zapisaną wartość pozycji, więc wystarczy ją trzymać równą ostatniej wycenie.
- Pomiar: 23 nowe testy (reguły dat, wartość schodkami, adresy API z odmowami, przeniesienie starych wartości przy starcie); 856 zielonych. Podgląd w przeglądarce na osobnej, pustej bazie: moneta 2 × 9000 zł z 10 mar, wyceny 10 000 (1 cze), 11 200 (1 wrz) i 11 500,50 (dziś) dają wykres 18 000 → 20 000 → 22 400 → 23 001 zł i wynik +5 001 zł (+27,8%). Bez LLM — ewal nie dotyczy.
- Koszt: 0 USD, bez nowych zapytań do Yahoo ani NBP (pozycje ręczne są w PLN i nie mają notowań).
- Co zadziałało: wartość „schodkami” — od dnia wyceny do następnej — pokazuje tylko to, co było wiadomo danego dnia; linia między wycenami wyglądałaby płynniej, ale wymyślałaby ceny. Jedno miejsce na bieżącą wartość (wyceny), a nie dwa (wyceny i pole „Wartość” w edycji), więc nie mogą się rozjechać.
- Co nie zadziałało i dlaczego: dotychczasowe pozycje, którym właściciel ręcznie zmienił wartość, straciłyby ją, bo wykres liczy teraz od ceny zakupu. Pomogło przeniesienie danych przy starcie aplikacji: taka wartość staje się jedną wyceną z dnia dodania, a warunek (wartość różna od kosztu, brak wycen) sprawia, że drugi start nic już nie zmienia.
- Następne pytanie: czy aktywo nienotowane w innej walucie (moneta kupiona w EUR) liczyć kursem NBP z dnia wyceny, czy prosić o wycenę od razu w PLN?

### 2026-10-14 — #277 dzienne notowania każdego instrumentu Bossy, także sprzedanego
- Hipoteza: brakujące notowania w IKE/IKZE to nie brak danych, tylko brak tickera. Sprzedany instrument nie ma pozycji, więc nikt nie pyta o niego OpenFIGI. Posiadany zagraniczny dostaje kilkadziesiąt notowań i status „niejednoznaczny”. Waluta transakcji (jedyne, co Bossa mówi o miejscu zakupu) wystarczy, żeby wybrać jedno notowanie: PLN to GPW, USD to Londyn dla funduszu i USA dla akcji.
- Pomiar: 16 nowych testów (wysyłka po 10 ISIN-ów, reguła na kształtach prawdziwych odpowiedzi OpenFIGI, zapis, import, wycena przez API); 819 zielonych. Na prawdziwych eksportach w świeżej bazie: ostrzeżeń „brak notowań” 116 → 4; wartość pozycji bez notowań spadła o 90–95% na obu kontach emerytalnych, a zysk widoczny na wykresie wzrósł kilka- do kilkunastokrotnie i doszedł do wyniku inwestycji. Bez LLM — ewal nie dotyczy.
- Koszt: 0 USD. OpenFIGI: kilkanaście zapytań na 128 ISIN-ów zamiast ~140; Yahoo: ~120 tickerów więcej przy pierwszym otwarciu wykresu (z dziennym cache).
- Co zadziałało: sprawdzenie reguły na żywo przed kodem — „najpierw USA” wyglądało rozsądnie, ale dla ETF-ów UCITS wybierało linię pozagiełdową z nieaktualnymi kursami. Jedna tabela na ISIN dla wszystkich portfeli: IKE i IKZE mają wspólne instrumenty.
- Co nie zadziałało i dlaczego: teraz zysk na wykresie przekracza wynik (w IKE o kilkanaście procent). Wykres liczy z cen zamknięcia i bez prowizji, a wynik z cen transakcji po prowizji. Część różnicy to osobny błąd: Bossa zapisuje bieżącą wartość jednej spółki z USA w USD jako PLN. Moja pierwsza diagnoza była błędna, bo skrypt pobrał kursy NBP złym klientem i po cichu pominął USD/PLN.
- Następne pytanie: czy różnicę między ceną transakcji a zamknięciem (i prowizje) pokazywać przy wykresie osobno, żeby „pokrycie wyniku” nie wyglądało na błąd, gdy przekracza 100%?

### 2026-10-13 — #273 / S14 porównanie z benchmarkiem
- Hipoteza: żeby uczciwie porównać portfel z indeksem, trzeba oddzielić wynik inwestowania od wpłat. Wystarczy codziennie zapytać: ile dziś jest wart wczorajszy skład (plus dywidendy, które dziś wpłynęły) wobec wczorajszej wartości, a potem pomnożyć dni przez siebie. Tak liczą fundusze („time-weighted return”), a potrzebne dane (ilości i ceny dzień po dniu) już były w wycenie S10.
- Pomiar: 30 nowych testów (zakup i sprzedaż nie zmieniają zwrotu, dywidenda podnosi go w dniu wpłaty, przeliczenie benchmarku na PLN, błędy tickera, API); 800/800 zielone. Na prawdziwych danych (5 kont): zwrot liczony w przeglądarce dla ukrytych portfeli zgadza się z backendem co do 0,003 pp. Bez LLM — ewal nie dotyczy.
- Koszt: 0 USD. Yahoo: 2 zapytania na benchmark dziennie (kursy, waluta), z cache, tylko po wejściu w tryb „Porównanie”.
- Co zadziałało: ten sam szereg zasila oba pytania — wartość wczorajszego składu po dzisiejszych cenach razem z wartością z wczoraj daje zwrot dowolnego zestawu portfeli przez zwykłe sumowanie, więc ukrycie portfela w legendzie nie wymaga nowego zapytania. Benchmark przeliczany tą samą regułą co pozycja (stosunek kursów razy stosunek kursów NBP), więc pensy i dolary nie potrzebowały nowego kodu.
- Co nie zadziałało i dlaczego: Yahoo nie ma historii indeksów GPW ani Nasdaq-100 TR — tylko dzisiejszy kurs; zastępstwem są fundusze, które te indeksy naśladują (z opłatą funduszu). Dla nieznanego tickera yfinance nie zwraca „brak waluty”, tylko rzuca wyjątek — bez osobnego sprawdzenia wyglądało to jak awaria Yahoo.
- Następne pytanie: czy dywidendy liczyć w dniu ustalenia prawa (jak indeksy), a nie w dniu wpłaty — przesunięcie o 1–4 tygodnie widać na krótkich zakresach?
- Poprawka po review właściciela (2026-10-14): wykres pokazywał szybki wzrost na początku i płasko potem, choć wynik był inny. Dwie przyczyny. (1) Dane: 118 instrumentów bez dziennych notowań ma w historii stałą wartość, więc ich zysk znika — zwrot widział ok. jednej czwartej wyniku (w IKE większość wartości była bez notowań, #269). (2) Metoda: zwrot ważony czasem traktuje małą wpłatę sprzed lat tak samo jak dzisiejszą, wielokrotnie większą. Odpowiedź: pierwszą liczbą jest porównanie ważone kwotą — „te same wpłaty w benchmarku” (WIG20, S&P 500 TR, Nasdaq-100; zgodne co do złotówki z liczeniem w Pythonie), a przy wykresie ostrzeżenie, ile zysku pomija. Odrzucony wariant „zysk z przepływów” sumował się dokładnie do wyniku, ale bez notowań przenosił cały zysk na dzień zakupu: −84%, potem +101% w rok. Wniosek: najpierw sprawdzić, czy dane wejściowe zgadzają się z liczbą, którą właściciel zna, dopiero potem ufać wzorowi.

### 2026-10-13 — #267 / S13 podatek od dywidend w szacunku
- Hipoteza: podatek od dywidendy da się opisać dwiema liczbami na pozycję — ile pobiera się przed wypłatą i ile zostaje do dopłaty w zeznaniu — wyliczanymi z typu konta i kraju spółki, a stawkę u źródła najlepiej brać z własnych wyciągów, nie z tabeli.
- Pomiar: 17 nowych testów (reguły, odczyt stawek z obu wyciągów, szacunek, API); 770/770 zielone. Na prawdziwych danych szacunek (brutto, na konto, do dopłaty w PIT) liczy się dla wszystkich kont; w XTB USD stawki z wyciągów 15%, 26,4% i 27%, w IKE/IKZE polskie spółki 0%. Bez LLM — ewal nie dotyczy.
- Koszt: 0 USD, żadnych nowych zapytań sieciowych.
- Co zadziałało: stawka z wyciągu przed regułą kraju — przy symbolach „.US” XTB pobiera też 26,375% (Niemcy) i 27% (Dania), bo podatek zależy od kraju spółki, nie giełdy; sama tabela by się myliła. Tabela tylko ze stawek widzianych w wyciągach i „nieznana" dla reszty zamiast zgadywania. Dopłata w PIT osobno, nie odejmowana — „na konto" znaczy to samo co w historii.
- Co nie zadziałało i dlaczego: XTB nie ma ISIN-u, więc kraj spółki dla spółki bez historii wypłat wynika z giełdy — dla ADR-ów to przybliżenie, oznaczone jako „reguła".
- Następne pytanie: czy po #269 (tickery akcji z USA w Bossie) stawki „netto 85%" z tytułów Bossy pokryją IKE tak dobrze jak wyciągi XTB?

### 2026-10-13 — #266 / S13 szacunek dywidend na następny rok
- Hipoteza: uczciwy szacunek dywidend nie potrzebuje modelu — wystarczy „ostatnie 12 miesięcy jeszcze raz": kwoty na akcję z Yahoo przeniesione na te same miesiące następnego roku, razy dzisiejsza liczba sztuk i dzisiejszy kurs NBP. Każdą liczbę da się wtedy sprawdzić ręcznie.
- Pomiar: 19 nowych testów (czysta logika, pobieranie z Yahoo, odczyt komentarza XTB, API); 753/753 zielone. Na prawdziwych danych (5 kont): szacunek na 2027 dla 27 z 78 instrumentów z wypłatą; XTB: 43 z 46 instrumentów z danymi z Yahoo; Bossa IKE: 15 z 23 bez danych (akcje z USA bez tickera, #269). Bez LLM — ewal nie dotyczy.
- Koszt: 0 USD. Yahoo: 3 zapytania na ticker dziennie (dywidendy, waluta, kurs), z cache; pierwszy przebieg ~13 s dla 36 tickerów.
- Co zadziałało: kontrola krzyżowa dwóch niezależnych źródeł (Yahoo i komentarz „0.91/ SHR" z wyciągu XTB) na średniej wypłacie, nie na sumie — suma myliłaby się, bo Yahoo datuje wypłatę dniem ustalenia prawa, a XTB dniem przelewu; stopa dywidendy jako stosunek dwóch liczb z Yahoo w tej samej jednostce (pensy przez pensy), więc bez kursu walut — ta sama lekcja co #188.
- Co nie zadziałało i dlaczego: Yahoo nie odróżnia „spółka nie płaci" od „nie znam tickera" (w obu przypadkach pusta lista dywidend) — rozstrzyga dopiero to, czy ticker ma kursy. Dywidenda w ratach (Atrem) wychodzi jako rozbieżność: Yahoo sumuje raty w jedną kwotę.
- Następne pytanie: czy podatek według typu konta (#267) da się oprzeć na kraju emitenta z ISIN bez osobnej tabeli stawek dla każdego kraju?

### 2026-10-13 — #265 / S13 historia dywidend
- Hipoteza: historię dywidend da się złożyć z tego, co importy już zapisują (Cash Operations XTB, historia finansowa Bossy) — brakuje tylko informacji, z jakiej spółki była wypłata: w XTB to kolumna `Ticker`, której parser nie czytał, w Bossie kod spółki w tytule operacji.
- Pomiar: 34 nowe testy (parser, łączenie wierszy, przypisanie, przeliczenie, API); 734/734 zielone. Na prawdziwych eksportach (5 kont, świeża baza w podglądzie): suma historii = „dywidendy" w wyniku inwestycji co do grosza na każdym koncie; XTB 191/191 wypłat przypisanych, Bossa IKZE 15/16, Bossa IKE 22/112. Bez LLM — ewal nie dotyczy.
- Koszt: 0 USD. NBP: jedna seria na walutę od pierwszej wypłaty.
- Co zadziałało: test zgodności z istniejącą liczbą (wynik inwestycji) jako strażnik — dwa niezależne miejsca w kodzie muszą dać tę samą sumę, więc błąd w łączeniu wierszy albo w kursie wyszedłby od razu; dwie małe strategie przypisania (XTB, Bossa) zamiast jednego `if` po brokerze; kod spółki z Bossy czytany z zapisanego tytułu, więc stare importy działają bez ponownego wgrania.
- Co nie zadziałało i dlaczego: akcje z USA w Bossie — tytuł podaje ticker („HCA"), ale OpenFIGI dla notowań w USD zwraca wynik niejednoznaczny (bez tickera), a sprzedanych spółek nie ma już w pozycjach, więc większość wypłat z IKE zostaje nieprzypisana (liczy się do sum pod tickerem z tytułu).
- Następne pytanie: skąd wziąć ticker dla ISIN z USA przy wyniku niejednoznacznym — filtr giełdy US w zapytaniu OpenFIGI czy ticker z transakcji?

### 2026-10-13 — #253 + #225 / zapisany indeks raportów i zakładka „Zapytaj raport"
- Hipoteza: pytanie do raportu da się zadać z aplikacji webowej za 1 wywołanie embeddingu i 1 wywołanie Gemini, jeśli indeks buduje się osobno (komenda `filings-rag build-index`, przyrostowo przez kilka dni), a aplikacja go tylko czyta. Odpada reranker LLM z pipeline'u evali, czyli drugie wywołanie Gemini na każde pytanie.
- Pomiar: nowa suita `p2-web-answer-accuracy` (te same 7 pytań co `p2-answer-accuracy`) puszczona na żywo 2026-10-13: 1/7. Wynik nieporównywalny z baseline (4/5 z rerankerem): w indeksie jest dziś tylko Microsoft, więc pytania o Amazon, Oracle, NextEra i Atrem kończą się uczciwą odmową „spółki nie ma w indeksie", a oba pytania o Microsoft padły na dziennym limicie Gemini. Przechodzi „nvidia-not-in-corpus". Baseline suity zapisuję dopiero na pełnym indeksie.
- Koszt: 0 USD (klucz bez billingu). Build: 7 wywołań `contextual` (Microsoft był już w cache), wszystkie zakończone błędem (503 „high demand", 429 na limicie 5 zapytań i 250 tys. tokenów na minutę).
- Co zadziałało: pomijanie spółki, która się nie udała, zamiast przerywania całego builda — Microsoft trafił do indeksu z cache bez żadnego wywołania, reszta dojdzie przy kolejnym uruchomieniu; zapis do pliku tymczasowego i podmiana — aplikacja nigdy nie czyta połowy pliku; ponowne wczytanie indeksu po zmianie pliku, bez restartu aplikacji.
- Co nie zadziałało i dlaczego: automatyczne ponawianie przez SDK zapytań z błędem 503 (do 4 prób) zjada minutowy i dzienny limit Gemini, a licznik w aplikacji widzi jedno wywołanie zamiast czterech prób — pigułka pokazywała 10/20, gdy Google mówił już 20/20 (#254). Bez rerankera odmowa „brak pasującego fragmentu" działa tylko wtedy, gdy pytanie nie ma żadnego wspólnego słowa z fragmentami: najlepszy wynik wyszukiwania jest względny (skalowany do 0–1 w obrębie zbioru), więc prawie zawsze przekracza próg 0,5.
- Następne pytanie: ile jakości kosztuje brak rerankera na pełnym indeksie (rerun `p2-web-answer-accuracy --no-cache` po dobudowaniu indeksu i porównanie z `p2-answer-accuracy`)?

### 2026-09-29 — portfolio-webapp / S12 jedno aktywo u wielu brokerów
- Hipoteza: tę samą spółkę u dwóch brokerów da się uznać za jedno aktywo bez zgadywania — pewne przypadki rozstrzyga FIGI z OpenFIGI (ten sam FIGI = to samo notowanie), a niepewne rozstrzyga właściciel na podstawie wskazanych dowodów (ticker, nazwa, cena za sztukę).
- Pomiar: 19 nowych testów (13 na regułach łączenia i propozycjach, 6 przez API na imporcie XTB + Bossa z tą samą spółką); 165/165 zielone w `tests/portfolio_webapp`. Bez LLM.
- Koszt: 0 USD. Tożsamość liczy się z bazy (FIGI i decyzje), ceny do propozycji z tej samej wyceny co wykres.
- Co zadziałało: union-find na krawędziach „ten sam FIGI” i „decyzja właściciela”, minus pary oznaczone „to różne” — łączenie przechodnie w kilkunastu liniach; klucz aktywa = ISIN, jeśli ma go którykolwiek instrument, więc XTB zyskuje ISIN od Bossy, a Bossa klasę aktywów od XTB; historia wartości dalej liczy się na kluczach brokera w obrębie portfela, a klucz aktywa podmienia się dopiero na wyjściu, więc S10 nie wymagał zmian.
- Co nie zadziałało i dlaczego: sama nazwa to słaby dowód („iShares Core MSCI World” i „… EM” mają 60% wspólnych słów) — dopiero warunek podobnej ceny za sztukę odsiewa takie pary; wspólny ticker na dwóch giełdach też bywa dwiema spółkami (ING), stąd limit różnicy ceny 25%. Propozycja nigdy nie łączy sama — decyzja zostaje u właściciela.
- Następne pytanie: czy przy prawdziwych danych przyda się też `shareClassFIGI` (ten sam fundusz na dwóch giełdach ma różne FIGI notowań, ale ten sam FIGI klasy)?

### 2026-09-29 — portfolio-webapp / S11 udziały i podziały
- Hipoteza: wykres kołowy z drążeniem w zagnieżdżone grupy wymaga podziału rozłącznego (suma 100%), więc zamiast rozbudowywać Agregaty (S9, grupy mogą się nakładać) lepiej dodać osobne pojęcie „podział" — jak taksonomie w Portfolio Performance.
- Pomiar: 23 nowe testy (logika drzewa na liczbach z głowy + API: rozłączność, cykle, usuwanie grupy, duplikowanie, domyślny, wbudowane, zakres portfela); 146/146 zielone w `tests/portfolio_webapp`. Bez LLM.
- Koszt: 0 USD. Udziały liczą się z tej samej wyceny co wykres (S10), kursy z cache dnia.
- Co zadziałało: rozłączność jako klucz główny w bazie `(podział, aktywo)`, a nie reguła w UI — niemożliwe do obejścia żadnym endpointem; walidacja cyklu przez wędrówkę po rodzicach (grupa ma jednego rodzica, więc wystarczy sprawdzić, czy nowy rodzic nie leży pod przenoszoną grupą); kolor wycinka z kolejności definicji, nie z rozmiaru — wycinek nie zmienia koloru, gdy wartości się przesuwają; nazwa `breakdown` w kodzie, bo `split` w finansach to split akcji.
- Co nie zadziałało i dlaczego: nic istotnego; dwa ostrzeżenia linta (mutowana zmienna w renderze, zależność efektu) wymusiły czystsze wersje. Ta sama spółka z XTB (bez ISIN) i z Bossy (ISIN) to wciąż dwa aktywa — pytanie #7 w 02-spec.md.
- Następne pytanie: czy fundusz rozbity wagami między grupy (VWCE 60% USA / 40% reszta) jest wart komplikacji modelu (pytanie #6)?

### 2026-09-29 — portfolio-webapp / S10 widok zbiorczy i dzienna historia wartości
- Hipoteza: dokładną dzienną wartość portfela da się złożyć z dwóch niezależnych pytań — ile sztuk było danego dnia (importy, loty XTB, ledger Bossy) i ile była warta jedna sztuka (kotwica z importu × stosunek kursów zamknięcia × stosunek kursów NBP) — bez ufania absolutnej cenie z Yahoo.
- Pomiar: 38 nowych testów na ręcznie policzonych liczbach (silnik, loty, API, serie kursów i NBP); 123/123 zielone w `tests/portfolio_webapp`. Bez LLM — ewal nie dotyczy (żaden prompt ani model się nie zmienił).
- Koszt: 0 USD. yfinance: 1 zapytanie na ticker dziennie (cache), NBP: 1 zapytanie na ~kwartał na walutę (okna ≤ 90 dni, API przyjmuje maks. 93).
- Co zadziałało: stosunek kursów zamiast ceny absolutnej (ta sama lekcja co #188) — pensy vs funty i USD na rachunku PLN przestają być pułapką; czysty silnik na `Decimal` oddzielony od pobierania danych, więc każda reguła ma test na liczbach z głowy; `auto_adjust=False` w yfinance, bo cena skorygowana o dywidendy zaniża każdy dzień sprzed wypłaty.
- Co nie zadziałało i dlaczego: eksport stanu (XTB) nie mówi, kiedy sprzedano coś między importami — pierwsza wersja reguły dodawała nowy lot do starej ilości i „wymyślała" szczyt; ograniczenie do większej z ilości w obu importach to uczciwy kompromis, dokładny jest tylko ledger. Format daty lotu w prawdziwym eksporcie XTB niezweryfikowany (pytanie #4 w 02-spec.md).
- Następne pytanie: czy arkusz „Closed Positions" XTB wystarczy, żeby historia XTB była tak dokładna jak ledger Bossy?
