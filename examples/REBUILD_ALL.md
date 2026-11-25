# T37 — пересборка четырёх эффектов и проверка звука

## Собрано

| Эффект | Пересобранный ZDL | Размер |
| --- | --- | --- |
| ST GT GEQ | `ST_GT_GEQ_REBUILT.ZDL` | 8538 B |
| Hall | `HALL_REBUILT.ZDL` | 6534 B |
| HD Hall | `HDHALL_REBUILT.ZDL` | 8902 B |
| BaFzSmile | `BAFZSMILE_REBUILT.ZDL` | 7018 B |
| FuzzSmile | `FUZZSMILE_REBUILT.ZDL` | 6990 B |

Для BaFzSmile и FuzzSmile в сгенерированный C встроен один и тот же движок
`SUB_Drive_KawaOD`, поднятый из BaFzSmile. Это заменяет вызов в прошивку,
которого нет в автономном стенде.

## Звук

| Эффект | Проверка | Результат |
| --- | --- | --- |
| Hall | Полный `c6xboot`, стоковая прошивка, один и тот же сценарий нажатий | Оригинал RMS 0.0142163, rebuilt 0.0142157; RMS разницы 0.0003578. Экран HALL REV совпал |
| ST GT GEQ | `c6xzdl`, `--func Fx_ST_GT_GEQ --fw-stubs` | Rebuilt RMS 0.19843; оригинальный ZDL в стенде дал нулевой вывод |
| HD Hall | `c6xzdl`, `--func Fx_REV_HD_Hall --fw-stubs` | Rebuilt RMS 0.14031; оригинальный ZDL дал нулевой вывод |
| BaFzSmile | `c6xzdl`, `--func Fx_BASSDRV_B_FzSmile --fw-stubs` | Rebuilt RMS 0.20540; оригинал дал нулевой вывод |
| FuzzSmile | `c6xzdl`, `--func Fx_DRV_FuzzSmile --fw-stubs` | Rebuilt RMS 0.20540; оригинал не выдал ни одного сэмпла |

Прямое сравнение original ↔ rebuilt удалось только для Hall: в полном
эмуляторе оба варианта дали практически одинаковый звук. Для остальных
автономный `c6xzdl` не воспроизводит стоковый ZDL без инициализации ОС,
поэтому там удалось подтвердить только наличие звука у пересобранной версии.

## Расширение эмиттера

В `emit_c.py` добавлены шаблоны: LDW, LDDW/LDNDW, STW, STDW/STNDW, MV, MVK,
MVKH, ADD, ADDK, ADDAW, ADDAD, SUB, SHL, SET, MPYSP, ADDSP, SUBSP, CMPLTSP,
CMPGTSP, CMPLTU, CMPGTU, CMPGT, CMPLT, B, BDEC, BNOP. Команды SPLOOP,
SPKERNEL, SPMASK, MVC и системные инструкции игнорируются: они относятся к
аппаратному конвейеру, а не к арифметике алгоритма.

MPYSPDP пока пропускается: это редкая double-операция, корректный шаблон
для неё ещё не проверен. Из-за этого точность пересобранного HD Hall может
отличаться от оригинала.

## Границы

- Пересобранный код — рабочий эквивалент machine-кода, не исходник завода.
- Для эффектов с вызовами прошивки нужен встроенный движок, как для пары
  BaFzSmile/FuzzSmile.
- Для окончательного сравнения HD Hall, BaFzSmile и FuzzSmile нужны прогоны
  в полной прошивке с правильной навигацией или с установкой пересобранного
  ZDL на то же место в образе флеша.
