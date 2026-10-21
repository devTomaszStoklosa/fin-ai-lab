# P4-S6 — kwantyzacja i lokalna inferencja

`quantized.py` jest częścią pakietu pip (`fin_ai_lab`), w przeciwieństwie do notebooków w `training/` — ale wymaga pliku `.gguf`, którego repo nie zawiera (gitignored `*.gguf`, `data/private/`).

## Jednorazowa konwersja (`scripts/news_classifier_quantize_bielik.py`)

1. Skopiuj adapter LoRA z Drive (`CHECKPOINT_DIR` z `bielik_lora_finetune.ipynb`) do `data/private/bielik_lora_adapter/` — ten sam wzorzec co `data/private/herbert_checkpoints/`.
2. Sklonuj llama.cpp (tylko skrypt konwersji, bez budowania C++) do **osobnego** venv — jego wymagania przypinają `transformers==4.57.6`/`torch==2.11.0`, starsze niż w tym repo (`transformers>=5.0`), więc nie mogą trafić do `.venv` tego projektu:
   ```bash
   git clone https://github.com/ggml-org/llama.cpp tools/llama.cpp
   uv venv tools/convert-venv --python 3.12
   uv pip install --python tools/convert-venv -r tools/llama.cpp/requirements/requirements-convert_hf_to_gguf.txt
   uv pip install --python tools/convert-venv "transformers==4.46.3"
   ```
   `tools/` jest gitignored — to lokalne narzędzie budowy, nie kod tego repo.
2b. Nałóż `scripts/patches/llama_cpp_hf_vocab_score.patch` na świeży klon (issue #142 — naprawia pustą odpowiedź modelu, patrz sekcja "Znane ograniczenia" poniżej):
   ```bash
   cd tools/llama.cpp && git apply ../../scripts/patches/llama_cpp_hf_vocab_score.patch
   ```
3. `uv sync --extra quantized` (`llama-cpp-python`, `peft`, `transformers`).
4. Zaakceptuj warunki `speakleash/Bielik-1.5B-v3.0-Instruct` i zaloguj się (`huggingface_hub.login()`), jak w `bielik_lora_finetune.ipynb`.
5. `uv run python scripts/news_classifier_quantize_bielik.py` — scala adapter z bazowym modelem, konwertuje do GGUF (f16), kwantyzuje (Q4_K_M) do `data/private/bielik_quantized/model.gguf`. Na końcu sprawdza, czy llama.cpp zamienia prompt klasyfikacyjny na dokładnie te same tokeny co `transformers`, i przerywa z błędem, jeśli nie (issue #7, sekcja poniżej).

## Uruchomienie ewaluacji

Po konwersji: `fin-ai-lab eval p4-classifier-quantized --split test`, potem `fin-ai-lab news-classifier compare-report` (P4-S7) obejmie już piąty model.

## Znane ograniczenia

### Naprawione (2026-09-20): pusta odpowiedź modelu po konwersji — issue 142 w prywatnym archiwum

Główna przyczyna znaleziona w samym llama.cpp: `gguf-py/gguf/vocab.py`'s `LlamaHfVocab.get_token_score()` to niedokończony stub, który dla **każdego** tokenu zawsze zwraca `-1000.0` (`# Placeholder for actual logic ... This needs to be implemented`). Bez realnej różnicy w wynikach llama.cpp's tokenizer w stylu SPM (Viterbi) przy inferencji nie ma żadnego sygnału, żeby preferować prawdziwe scalenia BPE nad rozbiciem na bajty — tokenizuje tekst zupełnie inaczej niż podczas treningu modelu, co dawało puste/śmieciowe odpowiedzi.

Naprawa: `scripts/patches/llama_cpp_hf_vocab_score.patch` — liczy realny wynik per token z rankingu scaleń BPE (`tokenizer.json`'s `model.merges`), zamiast stałej `-1000.0`. Nałożyć na świeży klon `tools/llama.cpp` przed konwersją (krok 2b powyżej). Zweryfikowane bezpośrednią inferencją po ponownej konwersji: model odpowiada sensownym, poprawnym polskim tekstem (`f16` i `Q4_K_M`), zarówno przez `create_chat_completion` jak i surowe ChatML.

To lokalna łatka w gitignored `tools/` (nie nasz kod, nie upstreamowany do llama.cpp w tym repo).

### Przyczyna znaleziona (2026-10-18): model ignoruje instrukcję i przerabia prompt — [issue #1](https://github.com/devTomaszStoklosa/fin-ai-lab/issues/1) (w archiwum #160)

Objaw: po naprawie #142 krótkie pytania działają, ale na **pełnym prompcie klasyfikacyjnym** (`bielik_sft.v1`) model nie odpowiada, tylko parafrazuje własną instrukcję (np. "You are given a Polish financial news headline and ticker catalog above...") aż do limitu tokenów (`finish_reason: length`).

Przyczyna leży w treningu (P4-S5), nie w llama.cpp. `bielik_lora_finetune.ipynb` miał `SFTConfig(max_length=512)`, a jeden przykład treningowy (prompt + odpowiedź w szablonie czatu) ma 659-705 tokenów, przy czym sama odpowiedź JSON zaczyna się dopiero na tokenie 627-673. `SFTTrainer` bez ostrzeżenia ucina tekst dłuższy niż `max_length`, więc **w żadnym przykładzie odpowiedź nie przetrwała** — model przez 3 epoki uczył się tylko pisać dalej tekst instrukcji. Dokładnie to potem robi przy inferencji. Poprawny JSON przez `transformers` brał się najpewniej z umiejętności modelu bazowego sprzed dotrenowania; dotrenowanie ciągnęło w drugą stronę, a drobne różnice obliczeniowe decydowały, co wygra.

Wykluczone pomiarem (2026-10-18): precyzja pamięci KV (cache w f32 zamiast f16 nie zmienia zachowania). Wcześniej wykluczone (2026-09-21): kwantyzacja, szablon czatu, rozmiar batcha prefill. Ówczesny pomiar „tokenizacja identyczna na 15/15 promptów” okazał się błędny dla promptu w formacie czatu: llama.cpp cięła `<|im_start|>` na kawałki i dodawała spacje (sekcja o issue #7 poniżej).

Naprawa: notebook ma teraz `MAX_LENGTH = 1024` i przed treningiem liczy tokeny każdego przykładu — przerywa się z błędem, zamiast pozwolić na ciche ucięcie. Do tego czasu bezpiecznikiem jest gramatyka JSON w `classify_quantized` (PR 213 w prywatnym archiwum): model nie może wypisać nic poza poprawnym JSON-em, ale treść etykiety nadal może być zła.

Ponowny przebieg po naprawie:

1. Uruchom `bielik_lora_finetune.ipynb` w Colab od nowa (notebook klonuje gałąź `main`, więc poprawka musi być zmergowana) i skopiuj nowy adapter z Drive do `data/private/bielik_lora_adapter/`. Ten sam trening obejmuje poprawkę [issue #7](https://github.com/devTomaszStoklosa/fin-ai-lab/issues/7): wcześniej trening i ewaluacja w notebooku dawały modelowi dwa tokeny początku tekstu (BOS), a llama.cpp daje jeden.
2. `uv run python scripts/news_classifier_quantize_bielik.py`, potem `fin-ai-lab eval p4-classifier-quantized --split test` i porównanie z dotychczasowym wynikiem (macro-F1 = 0). Starych wyników nie trzeba usuwać ręcznie: przy każdym z nich skrypt zapisuje odcisk adaptera (plik `<wynik>.adapter-sha256`) i sam przebudowuje te, które powstały z innego adaptera ([issue #6](https://github.com/devTomaszStoklosa/fin-ai-lab/issues/6)).

### Naprawione (2026-10-21): llama.cpp dawała modelowi inne tokeny niż trening — [issue #7](https://github.com/devTomaszStoklosa/fin-ai-lab/issues/7)

Pomiar na wszystkich 1347 nagłówkach z korpusu (prompt i pełny tekst treningowy, razem 2694 teksty): llama.cpp zamieniała na tokeny dokładnie tak jak `transformers` **0 z 2694** tekstów. Dwie osobne przyczyny, każda wystarczała sama:

1. **`<|im_start|>` jako zwykły tekst.** Krok scalania zapisuje tokenizer przez `transformers` 5, który trzyma `<|im_start|>` pod kluczem `extra_special_tokens`. Konwerter llama.cpp działa w osobnym venv na `transformers` 4.x, który czyta tylko `additional_special_tokens` — więc GGUF dostał `<|im_start|>` jako zwykły token, a llama.cpp cięła go na 7 kawałków (`<`, `|`, `im`, `_`, `start`, `|`, `>`). Naprawa: skrypt tuż przed konwersją dopisuje te tokeny pod `additional_special_tokens` (`conversion_tokenizer.py`).
2. **Spacja po tokenach specjalnych.** llama.cpp wstawia spację po każdym tokenie specjalnym, tak jak `transformers` 4.x; `transformers` 5 tego nie robi. Naprawa: `load_llm` wyłącza to przy wczytaniu modelu (`TOKENIZER_KV_OVERRIDES`). W samym pliku GGUF tego ustawić się nie da: konwerter bierze je z `add_prefix_space` w `tokenizer_config.json`, a ten klucz każe `transformers` 4.x szukać pliku `tokenizer.model`, którego Bielik nie ma. Skutek: GGUF otwarty poza naszym kodem (np. w `llama-cli`) nadal wstawiałby spacje.

Po obu naprawach: **2694/2694** identycznych, a przez `create_chat_completion` 1347/1347. Notebook przypina `transformers>=5`, bo na 4.x trening dostałby spacje, których inferencja już nie wstawia. Skrypt na końcu każdego przebiegu porównuje tokeny llama.cpp i `transformers` i przerywa się przy różnicy — także dla GGUF zbudowanego wcześniej.

Eval po przebudowie GGUF ze **starym** adapterem (2026-10-21, `p4-classifier-quantized --split test`, 13 przypadków): nadal 13/13 błędów schematu, jak 2026-09-20. Zmienił się jednak sposób, w jaki model się myli. Wcześniej przerabiał instrukcję aż do limitu tokenów (issue #1); teraz każda z 13 odpowiedzi kończy się sama, a 12 z nich to poprawny JSON etykiety owinięty w blok kodu Markdown (```` ```json ... ``` ````), którego `classify_quantized` nie przyjmuje (trzynasta to niepełny JSON). Po ręcznym zdjęciu bloku: sentiment trafiony 5/13, event_type 3/13 — model prawie zawsze mówi `neutral`. Czyli niezgodna tokenizacja też przyczyniała się do przerabiania instrukcji, nie tylko ucięty trening. Jakość etykiet oceni dopiero eval po ponownym treningu.
