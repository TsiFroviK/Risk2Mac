# Управляемые сборки

[English version](README.md)

В `inputs.json` указаны контрольные суммы Windows-источников и 155 ожидаемых результатов. Записи `windows` копируются из твоей Windows-установки. Записи `private` требуют точных локальных файлов, в том числе библиотек восстановленного Unity Player, базовых сборок совместимости и существующего локального провайдера игры. Скрипт компилирует вспомогательный код и применяет изменения хранения и управления через Mono.Cecil. Сборки Unity Mono подходят обеим архитектурам Mac.

Помести готовые файлы с типами `private`, `storage` и `wwise` в `PRIVATE/managed/`. Записи `storage` означают `RoR2.dll` и `ModLoader.dll` до исправления хранения. При использовании готовых файлов сверяй их с `input_sha256`. Если есть совпадающий порт и резервные копии обеих базовых DLL, команда из главной инструкции извлечёт 148 файлов в локальную папку.

Для недостающих файлов скрипт использует 70 DLL из Unity 2023.1.0f1 Mac Mono Build Support. Профиль Mono из полного редактора Unity предоставляет ещё до 22 DLL. Ещё 48 файлов, включая базовую `ModLoader.dll`, скрипт генерирует из подходящей Windows-установки через [AsmResolver.DotNet 6.0.1](https://www.nuget.org/packages/AsmResolver.DotNet/6.0.1). Два отдельных исправления адаптируют `HGUnityUtils.dll` и `Unity.RenderPipelines.Core.Runtime.dll`. Для всех файлов проверяются SHA-256 из манифеста. Если модуль Unity установлен вне стандартной папки Unity Hub, передай `--unity-support /путь/к/MacStandaloneSupport`.

При наличии обоих источников и полного профиля Mono всё ещё требуются четыре готовые DLL, изменённая базовая `RoR2.dll` и описанный ниже адаптер Wwise.

Для `wwise` можно использовать подготовленную `AK.Wwise.Unity.API.dll`. Другой вариант — положить в `PRIVATE/wwise/` два официальных файла из пакетов Wwise 2024.1.18 Unity Integration. Скрипт проверит их суммы и пересоберёт адаптер из Windows-сборки.

- `AkUnitySoundEnginePINVOKE_Mac.cs` из `Wwise/API/Runtime/Generated/Mac/`.
- `AkVector64.cs` из `Wwise/API/Runtime/Handwritten/Common/`.

Проверка перед сборкой.

```bash
python3 scripts/build-managed.py --game "$GAME" --private "$PRIVATE" --check-inputs
```
