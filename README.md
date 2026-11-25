# zdl-pseudo — подъём ZDL до читаемого псевдокода

Инструмент превращает дизассемблированный эффект в псевдокод с подписями внутренних структур. Он показывает структуру алгоритма: циклы, ветвления, используемые слоты contexts, параметры и адреса операций.

Это не полный декомпилятор. Он не восстанавливает исходный код и не доказывает эквивалентность звука. Подробное применение — в [HOWTO.md](HOWTO.md). Ниже — устройство, границы применимости и источники.

## Зачем

| Задача | Что даёт инструмент |
| --- | --- |
| Понять закрытый бинарный эффект | Видно, какие слоты памяти и параметры используются, где находятся циклы и ветвления |
| Подготовить перенос на другую платформу | Структура алгоритма видна до написания новой реализации |
| Сверить преобразование формата | Сравниваются структурные признаки до и после преобразования |
| Документировать эффект | Псевдокод с адресами служит общим описанием для разработчиков |

## Как устроен

1. Слой, который понимает контейнер эффекта, снимает заголовок, применяет релокации и затем вызывает дизассемблер TI. TI-утилита работает только с ELF и не знает формат эффекта; весь ZDL-специфичный слой относится к проекту и сообществу. На выходе — листинг команд с абсолютными адресами.
2. Парсер разбирает строку листинга: адрес, команду, операнды, метку, предикат и признак параллелизма.
3. Построитель графа разбивает код на базовые блоки, находит обратные переходы и циклы, записывает граф в формате DOT.
4. Символический проход подписывает слоты ABI и распространяет имена через копирования в регистры и стек.
5. Библиотека шаблонов переводит повторяющиеся последовательности команд в псевдокод. Неизвестные места остаются явными маркерами, а не выдумываются.
6. Калибровочный скрипт сравнивает структурные признаки с известными реализациями и считает полноту распознавания.

## Формат результата

| Выход | Назначение |
| --- | --- |
| `.pc` | Псевдокод с комментариями адресов, списком слотов и параметров |
| `.dot` | Граф базовых блоков для просмотра в Graphviz |
| `CALIBRATION.md`, `CALIBRATION.json` | Отчёт по парам «бинарник + известная реализация» |

Подписи в псевдокоде:

- `ctx[1]` — параметры;
- `ctx[3]` — дополнительная память;
- `ctx[5]` — аудиобуфер;
- `/* delay N */` — обязательная задержка конвейера;
- `__unknown(...)` — команда без шаблона;
- `for (;;) { /* pipelined loop */ }` — найденный цикл.

## Требования

- Python 3.10 или новее, только стандартная библиотека.
- Для работы с бинарным эффектом — внешний дизассемблер и утилита `dis6x` из TI CGT C6000 8.5.x.
- Для работы с готовым листингом TI-инструменты не нужны.

## Быстрый старт

Из готового листинга:

```
python zdl2pseudo.py effect.lst -o effect.pc --cfg effect.dot
```

Из бинарного эффекта:

```
python zdl2pseudo.py effect.ZDL -o effect.pc --cfg effect.dot \
  --disasm <path-to-disassembler>
```

Калибровка:

```
python calibrate_pseudo.py \
  --zdl-dir <effects-dir> \
  --src-dir <sources-dir> \
  --disasm <path-to-disassembler> \
  --out CALIBRATION.md
```

Пересборка lifted-кода:

```
python emit_c.py effect.ZDL -o effect.c --func Fx_...
cd examples/st_gt_geq
python build.py
```

## Ограничения

- Исходные имена переменных и типы не восстанавливаются.
- Для стоковых эффектов нужно явно указывать `--func`: автопоиск может выбрать edit-хендлер или объект в данных вместо аудиофункции.
- Эмиттер C покрывает команды из `examples/REBUILD_ALL.md`; `MPYSPDP` пока пропускается.
- Циклы с программным конвейером считаются приблизительно.
- Предикаты и параллельные пакеты показываются как структура, а не как точный порядок вычислений.
- Таблицы коэффициентов и линии задержки видны как адреса чтения и записи; их смысл определяет человек.
- Звук проверяется отдельно в эмуляторе или на устройстве.

## Файлы

| Файл | Назначение |
| --- | --- |
| `zdl2pseudo.py` | Парсер, граф, символический проход и генератор псевдокода |
| `calibrate_pseudo.py` | Поиск пар и сравнение структурных признаков |
| `emit_c.py` | Генератор компилируемого C по аудиофункции |
| `examples/st_gt_geq/` | Пример пересборки lifted-кода в ZDL |
| `HOWTO.md` | Пошаговое применение и описание ключей |
| `CONTRIBUTING.md` | Правила участия |

## Источники

Ни один из перечисленных проектов не является зависимостью инструмента. Это источники знаний и смежные работы. Дизассемблер TI дизассемблирует только машинный код C6000 внутри ELF; понимание контейнера эффекта и релокаций сделано в сообществе и в этом проекте, а не в TI.

### Документация и инструменты

- Texas Instruments C6000 Code Generation Tools, дизассемблер `dis6x`: https://www.ti.com/tool/C6000-CGT
- Texas Instruments, C674x CPU and Instruction Set Reference Guide, SPRUFE8B: https://www.ti.com/lit/ug/sprufe8b/sprufe8b.pdf
- GNU binutils, порт C6000, файл `tic6x-dis.c`: https://sourceware.org/git/?p=binutils-gdb.git;a=blob;f=opcodes/tic6x-dis.c;hb=HEAD

### Формат и ABI

- Инструментарий формата ZDL и линкер сообщества: https://github.com/themanro/ZoomMultistompZDL
- Помощник сообщества для дизассемблирования ZDL: https://github.com/themanro/ZoomMultistompZDL/blob/main/build/disassemble_zdl.py
- Набор эффектов сообщества с открытыми реализациями: https://github.com/matujuice/zoom-ms-zdl-effects-pack

### Связанные проекты

- Эмулятор педали и стенд эффектов: https://github.com/Senty3kat/zoom-ms-emulator
- Эмулятор эффектов, VST/CLAP адаптеры и офлайн-рендерер Ziddle: https://www.berbasoft.com/

## Лицензия

MIT. См. [LICENSE](LICENSE).

---

# English version

# zdl-pseudo — lift ZDL into readable pseudo-C

The tool turns a disassembled effect into pseudo-C with labels for internal structures. It shows the algorithm structure: loops, branches, memory slots, parameters and operation addresses.

This is not a full decompiler. It does not recover the original source and does not prove audio equivalence. See [HOWTO.md](HOWTO.md) for step-by-step use. This file describes the design, limits and sources.

## Purpose

| Task | Result |
| --- | --- |
| Understand a closed binary effect | Used memory slots, parameters, loops and branches become visible |
| Prepare a port to another platform | The algorithm structure is available before writing a new implementation |
| Verify a format conversion | Structural features are compared before and after conversion |
| Document an effect | Address-annotated pseudo-C becomes a shared description for developers |

## Design

1. A container-aware layer strips the header, applies relocations and then calls the TI disassembler. The TI tool only handles a C6000 ELF and knows nothing about the effect container; the format-specific layer belongs to the project and the community. The result is an instruction listing with absolute addresses.
2. The parser reads each line: address, opcode, operands, label, predicate and parallel flag.
3. The CFG builder splits code into basic blocks, finds back edges and loops, and writes a DOT graph.
4. The symbolic pass labels ABI slots and propagates names through register and stack copies.
5. A template library converts recurring instruction patterns into pseudo-C. Unknown instructions stay explicit.
6. The calibration script compares structural features with known implementations and reports recall.

## Output

| File | Purpose |
| --- | --- |
| `.pc` | Pseudo-C with address comments, slot list and parameter list |
| `.dot` | Basic-block graph for Graphviz |
| `CALIBRATION.md`, `CALIBRATION.json` | Report for binary plus known-implementation pairs |

Labels:

- `ctx[1]` — parameters;
- `ctx[3]` — scratch memory;
- `ctx[5]` — audio buffer;
- `/* delay N */` — required pipeline delay;
- `__unknown(...)` — instruction without a template;
- `for (;;) { /* pipelined loop */ }` — detected loop.

## Requirements

- Python 3.10+ and the standard library only.
- For binary input: an external disassembler and `dis6x` from TI CGT C6000 8.5.x.
- For an existing TI listing: no TI tools are needed.

## Quick start

From a ready listing:

```
python zdl2pseudo.py effect.lst -o effect.pc --cfg effect.dot
```

From a binary effect:

```
python zdl2pseudo.py effect.ZDL -o effect.pc --cfg effect.dot \
  --disasm <path-to-disassembler>
```

Calibration:

```
python calibrate_pseudo.py \
  --zdl-dir <effects-dir> \
  --src-dir <sources-dir> \
  --disasm <path-to-disassembler> \
  --out CALIBRATION.md
```

Rebuilding lifted code:

```
python emit_c.py effect.ZDL -o effect.c --func Fx_...
cd examples/st_gt_geq
python build.py
```

## Limits

- Original variable names and types are not recovered.
- For stock effects, pass `--func` explicitly: auto-detection may pick an edit handler or a data object instead of the audio function.
- The C emitter covers the instructions listed in `examples/REBUILD_ALL.md`; `MPYSPDP` is still skipped.
- Software-pipelined loops are counted approximately.
- Predicates and parallel packets are shown as structure, not exact evaluation order.
- Coefficient tables and delay lines appear as read/write addresses; their meaning is decided by the reader.
- Audio is verified separately in an emulator or on hardware.

## Files

| File | Purpose |
| --- | --- |
| `zdl2pseudo.py` | Parser, CFG, symbolic pass and pseudo-C generator |
| `calibrate_pseudo.py` | Pair discovery and structural comparison |
| `emit_c.py` | Compilable C emitter for an audio function |
| `examples/st_gt_geq/` | Example rebuild of lifted code into a ZDL |
| `HOWTO.md` | Step-by-step usage and options |
| `CONTRIBUTING.md` | Contribution rules |

## Sources

None of the projects below is a dependency. They are sources of knowledge and related work. The TI disassembler only decodes C6000 machine code inside an ELF; understanding the effect container and its relocations was developed by the community and in this project, not by TI.

### Documentation and tools

- Texas Instruments C6000 Code Generation Tools, `dis6x`: https://www.ti.com/tool/C6000-CGT
- Texas Instruments, C674x CPU and Instruction Set Reference Guide, SPRUFE8B: https://www.ti.com/lit/ug/sprufe8b/sprufe8b.pdf
- GNU binutils C6000 port, `tic6x-dis.c`: https://sourceware.org/git/?p=binutils-gdb.git;a=blob;f=opcodes/tic6x-dis.c;hb=HEAD

### Format and ABI

- Community ZDL toolchain and linker: https://github.com/themanro/ZoomMultistompZDL
- Community ZDL disassembly helper: https://github.com/themanro/ZoomMultistompZDL/blob/main/build/disassemble_zdl.py
- Community effect pack with open implementations: https://github.com/matujuice/zoom-ms-zdl-effects-pack

### Related projects

- Pedal emulator and effect bench: https://github.com/Senty3kat/zoom-ms-emulator
- Ziddle effect emulator, VST/CLAP adapters and offline renderer: https://www.berbasoft.com/

## License

MIT. See [LICENSE](LICENSE).
