# Управляемые сборки

[English version](README.md)

В `inputs.json` указаны контрольные суммы Windows-источников и 155 ожидаемых результатов. Записи `windows` копируются из твоей Windows-установки. Записи `private` требуют точных локальных файлов, в том числе библиотек восстановленного Unity Player, базовых сборок совместимости и существующего локального провайдера игры. Скрипт компилирует вспомогательный код и применяет изменения хранения и управления через Mono.Cecil. Сборки Unity Mono подходят обеим архитектурам Mac.

Помести файлы с типами `private`, `storage` и `wwise` в `PRIVATE/managed/`. Записи `storage` означают `RoR2.dll` и `ModLoader.dll` до исправления хранения. Используй `input_sha256`, после чего скрипт применит исправление. Оригинальные Windows-сборки отличаются по контрольным суммам. Если есть совпадающий порт и резервные копии двух базовых DLL, команда из главной инструкции извлечёт 148 файлов в локальную папку.

Для `wwise` можно использовать подготовленную `AK.Wwise.Unity.API.dll`. Другой вариант — положить в `PRIVATE/wwise/` два официальных файла из пакетов Wwise 2024.1.18 Unity Integration. Скрипт проверит их суммы и пересоберёт адаптер из Windows-сборки.

- `AkUnitySoundEnginePINVOKE_Mac.cs` из `Wwise/API/Runtime/Generated/Mac/`.
- `AkVector64.cs` из `Wwise/API/Runtime/Handwritten/Common/`.

Проверка перед сборкой.

```bash
python3 scripts/build-managed.py --game "$GAME" --private "$PRIVATE" --check-inputs
```
