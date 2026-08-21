# Epistemic Synthesis Report — epires upgrade (branch `exp`)

> Сохранённый синтез 14 субагентов (80+ веб-поисков, авг 2026). Цель — превратить леджер из CRUD в проверяемую эпистемическую машину.
> Читать как карту: диагноз → принципы → конкретные механизмы → дорожная карта.

## 0. TL;DR

- Текущая эпистемика: `store.py:503-644` — ручной `falsification_triggered: bool`, один гейт `E4:510`, `retract_evidence DELETE:668` против "append-only". Остальное — промпт.
- Нужен второй порядок: наблюдатель, нормы и наблюдатель наблюдателя — иначе система не видит себя.
- Решение — 7 слоёв по 1-2 файла каждый: observer-block, VSM разделение ролей, Dung-grounded статусы вместо bool, ATMS-lite каскад, GRADE→гейты, debate+калибровка, EIG-выбор.

---

## 1. Диагноз (из аудита `exp` @ main)

| Заявлено | Реально | Цена |
|---|---|---|
| VSA 10k hypergraph | `vsa.py` корректен, но `TAG:{t}` точное совпадение `hypergraph.py:62`, FTS доминирует `store.py:965` | поиск бесполезен |
| Popperian falsification | `models.py:70` ручной флаг, критерии — свободный текст | reward hacking не ловится |
| Cascading invalidation | `store.py:593` реальный и лучший кусок | спасает проект |
| E0-E5 `[V]/[P]/[D]` | только E4 CI95 enforced, `[V]` с пустой цитатой валиден | уровни — фикция |
| Immutable ledger | `DELETE FROM evidence` | доверие подорвано |
| Vector `vector_blob` | не перекодируется при `BLOCKED` `store.py:620` | VSA врёт |
| REST `app.py:69` | `CORS * + credentials`, без auth меняет леджер | governance без защиты |

Уникального кода ~500/4300 строк. 15% маркетинг без реализации. Ниша при этом реальна (нет прямых конкурентов ≥2 компонентов).

---

## 2. Кибернетика второго порядка (фон Фёрстер, Матурана/Варела, Умплби)

**Идеи:** observing systems (каждое наблюдение автобиографично), autopoiesis (operational closure, structural coupling), second-order science (эффект теории на систему, observer effect у LLM уже измерен: `2505.17815` +16% детекта оценки).

**Механизмы:**

- **M1 Observer-block** (дешево): каждое `evidence/hypothesis` = `observer_id` (модель+промпт), `criteria_version`, `confidence+calibration`, `distinction`. `PROV-AGENT 2508.02866` — MCP provenance как first-class узлы.
- **M2 Нормы как узлы DAG:** правила E-уровней версионированы, изменение = событие. `invalid under v3`, не стирание. Сохраняет identity при эволюции структуры.
- **M3 Observer-effect:** `eval_framing vs deploy_framing` + парные прогоны. Дивергенция = сигнал артефакта.
- **M4 Re-entry:** статистика леджера формулируется как гипотезы в том же DAG и фальсифицируется тем же протоколом.

---

## 3. Управление: Эшби + Бир (VSM, POSIWID, algedonic)

**Requisite variety:** угроз много (`rewardhackwatch` 89.7% F1, `METR 2025`, `OpenAI CoT` — скрывает, не чинит). Один судья не покрывает разнообразие — нужен набор разнотипных детекторов.

**VSM реконструкция Lead-PI:**

```
S5  Человек+устав (критерии фальсификации) — неизменяем вне цикла
S4  Скаут литературы/стратегии — не закрывает гипотезы
S3  Lead-PI (ресурсы/приоритеты)
S3* Аудитор (другая модель, read-only, перепрогон тестов, POSIWID-метрики) — ГЛАВНАЯ ДЫРА
S2  Механизм: граф+схема+anti-conflict+vollzug-таймауты (каскад уже S2)
S1  Кoderы с autonomy matrix
```

**Algedonic bypass:** противоречие вердиктов / провал аудита / N фейлов → сигнал мимо Lead-PI к S5 + заморозка ветки. Пороги заранее, метрики `escalation rate / decision latency`.

**POSIWID:** цель = то, что система делает. `Integrity gap = доля принятых с последующей находкой манипуляции`. Аудит post-hoc, невидим для агентов. `hidden tests + grader recomputation` −88% эксплойтов `2605.02964`.

---

## 4. Логика фальсификации: Дунг + ATMS + Дюэм-Куайн + Лакатос

**Дюэм-Куайн:** `⟨H + auxiliaries⟩ ⊢ O`, флаг на H некорректен. Фикс: `anomaly_raised → attributed:hypothesis|auxiliary:<id>|inconclusive`, assumption-узлы (`instrument/dataset/commit/eval_config`) первоклассные, тест ссылается на `assumption_id[]`. Атрибуция по Дорлингу (априорная надёжность) + severe-тест Мейо для каждого допущения. Только аномалия на ≥2 независимых инструментах → `attributed:hypothesis`.

**Дунг AF:** `ACTIVE/BLOCKED/FALSIFIED` ≅ `IN/UNDEC/OUT`. `CONFLICTS_WITH → attack`, `grounded` за `O(n·|E|)` (`Nofal 2021`). Статус = фиксированная точка, агент лишь добавляет рёбра. Взаимный конфликт → `UNDEC/BLOCKED` честно. `Bipolar AF` (`Cayrol`) — `SUPPORTS+CONFLICTS` с `supported attack`; `Carneades 2007` — `E0-E5 → proof standards` (preponderance/clear-and-convincing/beyond reasonable doubt). Либ `ctoth/argumentation`.

**TMS:** `JTMS-lite` (Doyle) — `justifications(in/out)`, relabel только forward-closure (~200 LOC). Узел с двумя SUPPORTS выживает при падении одной. `Entrenchment` (AGM Gärdenfors) — одна колонка `REAL` для жертвы при `nogood` (`LatticeMind 2608.08236`). Полный ATMS не делать (экспонента).

**Лакатос:** `hard core / protective belt`, `ad hoc₁/₂/₃` Захара, `use-novelty` (timestamp предсказания < результата). Индекс дегенерации `belt_patches / novel_confirmed`. `Verisimilitude` Фесты-Чеволани для ранжирования.

---

## 5. Шкала доказательств: GRADE → проверяемые гейты

Критика `Stegenga 2015` / `Blunt 2015`: иерархии без обоснования. Выход — уровень = предсказание "дальнейшее исследование не изменит уверенность".

| Гейт | Предикат | Провал |
|---|---|---|
| G0 Provenance | ссылка резолвится | [V] инвалид |
| G1 Seed variance | ≥3 seeds | cap E1 |
| G2 Held-out | хеш сплита < результата | cap E3 |
| G3 Prereg | гипотеза+метрика+stop-rule до прогона | cap E3 |
| G4 Precision | CI95 вне порога значимости | −1 |
| G5 Consistency | знак согласован | −1 |
| G6 Task validity (ABC NeurIPS 2025) | claim→benchmark mapping | −1 |
| G7 No file-drawer | все запуски в леджере | флаг |
| G8 Independence | ≥2 оси `{env,data,model,agent}` | не E5 |

`E0→E5` = потолок пройденных гейтов. `VoI (ISPOR)`: `P(изменит решение)·|Δutility|−cost>0`, иначе эксперимент запрещён.

---

## 6. Социальная эпистемология

**Debate:** `Khan 2024` 76% vs 54%, `Kenton 2024` — 2 раунда достаточно, больше растит сикофансию. Self-play 0.98 vs 0.51 — дебатеры учатся информативности. Протокол: защитник/оппонент случайно (не авторы), судья другое семейство, асимметрия (receipts без резюме автора), вердикт калибруется.

**Calibration:** `ConfidenceBench 2607.20526` Brier — единственный честный. Per-agent `brier_rolling+Platt(a,b)`, вес = откалиброванная вероятность, <30 резолюций — вес понижен.

**Peer review провалы:** `AgentReview 2406.12708` 37% решений, `Za NeurIPS 2025` 29-38% маршрутизация к союзникам, стеганография `2410.03768`. Защита: случайное назначение, анонимизация, граф ревью, ротация `producer≠reviewer≠judge`, sycophancy priors +10.5% `2509.23055`.

**Distributed cognition (Hutchins):** карта трансформаций `логи→отчёт→леджер→сводка`, selection bias таскинга, лексическая контаминация (`2407.17489` — сохраняется после ухода ИИ).

---

## 7. Выбор эксперимента: Active Inference + PCT

`Gupta EMNLP 2025` — LLM не чувствительны к фидбеку, GP обыгрывает. Фикс: `BED-LLM 2508.21184` явное `q(h)` + `EIG=E[KL]`, `sample-then-filter`, до 95%. `G(π)=pragmatic+epistemic` (Friston) — баланс без ε-greedy. `pymdp JOSS 2022`. Тест Гупты: перемешанные исходы не должны не менять выбор.

`PCT TCV (Marken 2014)`: возмущай переменную → компенсация = контролируемая цель. Дешевле самоотчёта.

FEP брать как формулы, метафизику — как вдохновение (`Colombo Synthese 2021`).

---

## 8. Память, поиск, структура знания

**VSA:** оставить `BSC/MAP XOR+roll` — только self-inverse даёт Канерву `query⊗F≈answer` (`Schlegel 2022`). Фикс: теги → бандлы символьных триграмм `ρ²A⊗ρB⊗C` (`Rachkovskij 2024`), fuzzy без словаря. Узел = `bundle(edge⊗neighbor, status⊗phase, trigram-профиль)`. Индекс `FAISS IndexBinaryFlat` (1250 Б/вектор) вместо скана `store.py:944`. Честно: как замена BM25 — не держится (`HDC review 2025`, `LIMIT DeepMind 2025`). Держать только для `structure mapping` + `unbind` по ролям, иначе гибрид `FTS5→VSA rerank` + A/B.

**Pask:** `CONFLICTS_WITH` → узел-разговор `asserted→in-conversation→resolved` с `teachback` и `merge/split/add`. `Bootstrapping Heylighen` на VSA-окрестностях — авто-детект идентичности.

**Стигмергия (Heylighen):** леджер = феромонная среда (свежесть/вес/затухание), Hebbian-усиление рёбер. `Bateson` фильтр: пишем только "различие, меняющее будущее решение". `von Foerster eigenform`: гипотеза = объект ⇔ `F(e)=e` после N воспроизведений (дискретна/стабильна/отделима/компонуема). `Турчин MST`: мета-гипотезы появляются квантом при loose coupling, диагностика — доля решений на мета-уровне.

**Лефевр (ранги рефлексии):** `W₁=T1·(1+W₂)`, глубина 2 достаточна: `belief_B_about_A` как отдельный контекст.

---

## 9. Дорожная карта

**Фаза 0 — 1 неделя:** JTMS-lite, `justifications`, `G0-G3`, observer-block, вынести `trace_md` из дефолта, `CORS/auth` закрыть.
**Фаза 1 — 2 недели:** S3* аудитор, algedonic, Brier per-agent.
**Фаза 2 — месяц:** Bipolar AF grounded+Carneades, assumption-узлы+атрибуция, `G4-G8`, EIG-скоринг, trigram VSA+FAISS.

**Не делать:** полный ATMS, FEP-метафизику в архитектуру, полный VSM на 5 агентов (`ViableOS` незрел).

**Метрики:** `Integrity gap ↓`, `Brier→калиброван`, `доля E3+ с атрибуцией 100%`, `EIG vs рандом`, `VSA rerank vs BM25`.

---

## 10. Файлы ветки `exp`

- `epires_core/gates.py` — G0-G8 предикаты
- `epires_core/tms.py` — JTMS worklist
- `epires_core/argumentation.py` — Dung grounded
- `epires_core/provenance.py` / `observer.py` — observer-block, criteria versions
- `epires_core/audit.py` + `algedonic.py` — S3* + bypass
- `epires_core/calibration.py` + `scoring.py` — Brier/Platt, EIG
- `epires_core/conversation.py` + `stigmergy.py` — Pask/Bateson/Heylighen
- `epires_core/search_index.py` — FAISS binary
- Короткие файлы <200 строк, типы, `ruff` clean.

*Источники: PROV-AGENT 2508.02866, BED-LLM 2508.21184, Khan 2402.06782, Kenton 2407.04622, Schlegel 2022, Rachkovskij 2024, Nofal 2021, Cayrol 2005, Gordon 2007, Stegenga 2015, ABC NeurIPS 2025, TRIPOD+AI BMJ 2024, etc.*
