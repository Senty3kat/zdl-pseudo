# HOWTO

Пошаговое применение инструмента. Общее устройство и источники — в [README.md](README.md).

## 1. Подготовка

Нужны Python 3.10+ и один из двух видов входа:

- готовый листинг дизассемблера TI с расширением `.lst`;
- бинарный эффект с расширением `.ZDL` или `.S3K` плюс внешний дизассемблер и `dis6x` из TI CGT C6000 8.5.x.

Дополнительные библиотеки Python не требуются.

## 2. Подъём из готового листинга

```
python zdl2pseudo.py effect.lst -o effect.pc --cfg effect.dot
```

На консоли печатается число разобранных команд, найденные слоты и параметры. Файл `.pc` содержит псевдокод, файл `.dot` — граф блоков.

## 3. Подъём из бинарного эффекта

```
python zdl2pseudo.py effect.ZDL -o effect.pc --cfg effect.dot \
  --disasm <path-to-disassembler>
```

Дизассемблер принимает тот же набор аргументов, что и внутренний инструмент проекта: входной файл, `-o`, `--symbols`, `--lines 0`. Если дизассемблер лежит рядом с инструментом, ключ можно опустить.

## 4. Ключи `zdl2pseudo.py`

| Ключ | Назначение |
| --- | --- |
| `-o FILE`, `--output FILE` | Записать псевдокод в файл. Без ключа вывод идёт на экран |
| `--cfg FILE` | Записать граф блоков в формате DOT |
| `--func NAME` | Ограничить разбор одной аудиофункцией |
| `--disasm PATH` | Путь к внешнему дизассемблеру для бинарного входа |
| `-h`, `--help` | Краткая справка |

## 5. Что читать в псевдокоде

Заголовок файла содержит контракт эффекта: список слотов и параметров. Основная часть — операции с адресами исходных команд в комментариях.

| Запись | Смысл |
| --- | --- |
| `ctx[1]` | Параметры эффекта |
| `ctx[3]` | Дополнительная память |
| `ctx[5]` | Аудиобуфер |
| `/* delay N */` | Обязательная задержка конвейера; удалять нельзя |
| `__unknown(...)` | Команда без шаблона; это честная граница подъёма |
| `for (;;) { /* pipelined loop */ }` | Найденный цикл; счёт может быть неточным |

## 6. Калибровка

Калибровка ищет пары и сравнивает структурные признаки, а не текст.

```
python calibrate_pseudo.py \
  --zdl-dir <effects-dir> \
  --src-dir <sources-dir> \
  --src-dir <other-sources-dir> \
  --disasm <path-to-disassembler> \
  --out CALIBRATION.md
```

Ожидаемая раскладка:

- в каталогах `--zdl-dir` лежат бинарные эффекты;
- в каждом каталоге `--src-dir` есть подкаталог с исходной реализацией;
- имя подкаталога совпадает с именем эффекта.

Рядом с отчётом создаётся `CALIBRATION.json`.

## 7. Ключи `calibrate_pseudo.py`

| Ключ | Назначение |
| --- | --- |
| `--zdl-dir DIR` | Каталог с бинарными эффектами; можно повторять |
| `--src-dir DIR` | Каталог с исходными реализациями; можно повторять |
| `--disasm PATH` | Внешний дизассемблер для бинарного входа |
| `--out FILE` | Файл отчёта; рядом появится JSON |
| `-h`, `--help` | Краткая справка |

## 8. Пересборка в ZDL

```
python emit_c.py effect.ZDL -o effect.c --func Fx_...
cd examples/st_gt_geq
python build.py
```

`emit_c.py` выдаёт компилируемый C с union-регистрами. Пример сборки
компилирует его через TI `cl6x` и собирает ZDL через `toolchain/zdl/linker.py`.
Набор команд пока ограничен примером; для других эффектов шаблоны расширяются.

## 9. Метрики отчёта

| Столбец | Смысл |
| --- | --- |
| `ctx recall` | Доля найденных слотов от известной реализации |
| `params recall` | Доля найденных параметров |
| `loops src/got` | Число циклов в исходной реализации и в подъёме |
| `unknown %` | Доля команд без шаблона |

## 10. Частые проблемы

| Симптом | Причина и действие |
| --- | --- |
| `disassembler not found` | Указать `--disasm` или передать готовый `.lst` |
| `no instructions parsed` | Листинг пустой или не в формате TI; пересобрать листинг |
| Подъём показывает edit-хендлер или объект в `.const` | Указать `--func` с точным именем аудиофункции |
| `no ZDL/source pairs found` | Проверить имена подкаталогов и ключи `--zdl-dir`, `--src-dir` |
| Высокий `unknown %` | Добавить шаблон команды и повторить калибровку |
| Расхождение по циклам | Определить, это вложенный цикл или копии конвейера; сравнить с исходной реализацией |

## 11. Границы применимости

Псевдокод — средство понимания структуры, а не замена бинарника. Звук и нагрузка проверяются отдельно в эмуляторе или на устройстве. Не публикуйте чужие бинарные эффекты и исходные реализации без разрешения.

---

# English HOWTO

## Setup

Use Python 3.10+. Provide either a TI disassembly listing (`.lst`) or a binary effect (`.ZDL`/`.S3K`) with an external disassembler and `dis6x` from TI CGT C6000 8.5.x.

## Lift a listing

```
python zdl2pseudo.py effect.lst -o effect.pc --cfg effect.dot
```

## Lift a binary effect

```
python zdl2pseudo.py effect.ZDL -o effect.pc --cfg effect.dot \
  --disasm <path-to-disassembler>
```

## Options

| Option | Purpose |
| --- | --- |
| `-o FILE`, `--output FILE` | Write pseudo-C; stdout by default |
| `--cfg FILE` | Write a DOT graph |
| `--func NAME` | Restrict analysis to one audio function |
| `--disasm PATH` | External disassembler for binary input |
| `-h`, `--help` | Show help |

## Calibration

```
python calibrate_pseudo.py \
  --zdl-dir <effects-dir> \
  --src-dir <sources-dir> \
  --disasm <path-to-disassembler> \
  --out CALIBRATION.md
```

`--zdl-dir` and `--src-dir` can be repeated. Each source directory contains subdirectories with known implementations.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| `disassembler not found` | Pass `--disasm` or use a ready `.lst` |
| `no instructions parsed` | Rebuild the TI listing |
| Lift shows an edit handler or a `.const` object | Pass `--func` with the exact audio function name |
| `no ZDL/source pairs found` | Check directory names and input options |
| High `unknown %` | Add an instruction template and recalibrate |
| Loop mismatch | Separate nested loops from software-pipeline copies |

Pseudo-C is a structure aid, not a replacement for audio verification.
