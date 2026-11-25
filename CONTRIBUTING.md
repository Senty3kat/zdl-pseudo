# Участие

Приветствуются сообщения об ошибках, запросы на новые шаблоны команд и изменения, улучшающие калибровку.

## Правила

- Описывайте расхождение структурно: вход, ожидаемый и полученный псевдокод, метрики отчёта.
- Не добавляйте бинарные эффекты, прошивки, дампы и чужие исходные реализации.
- Новые шаблоны команд должны сопровождаться проверкой на калибровочной паре.
- Код на Python должен опираться только на стандартную библиотеку.
- Перед запросом на включение изменений запустите `python -m py_compile zdl2pseudo.py calibrate_pseudo.py` и калибровку на доступных парах.

## Лицензия

Внося изменения, вы соглашаетесь с лицензией MIT проекта.

---

# Contributing

Bug reports, template requests and calibration improvements are welcome.

## Rules

- Describe a mismatch structurally: input, expected and observed pseudo-C, report metrics.
- Do not add binary effects, firmware images, dumps or third-party source implementations.
- Every new instruction template should be covered by a calibration pair.
- Keep the code dependency-free.
- Before opening a pull request, run `python -m py_compile zdl2pseudo.py calibrate_pseudo.py` and calibration on available pairs.

## License

Contributions are accepted under the MIT license.
