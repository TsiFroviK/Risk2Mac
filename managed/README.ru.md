# Управляемые сборки

[English version](README.md)

В `inputs.json` указаны контрольные суммы Windows-источников и 155 основных управляемых сборок. Скрипт копирует подходящие DLL из Windows-версии, выбирает библиотеки SDK, компилирует вспомогательный код и применяет локальные исправления совместимости. Сборки Unity Mono используются на обеих архитектурах Mac. Для режима Steam сборщик дополнительно компилирует библиотеку совместимости со Steam.

Для обычной сборки используются подходящая Windows-установка и официальные SDK Unity и Wwise. Контрольные суммы в манифесте определяют совместимые готовые файлы и варианты, получаемые при сборке. [Основная инструкция по сборке](../README.ru.md#сборка)

Для недостающих файлов скрипт использует 70 DLL из Unity 2023.1.0f1 Mac Mono Build Support. Профиль Mono из полного редактора Unity предоставляет ещё до 22 DLL. Ещё 48 файлов, включая базовую `ModLoader.dll`, скрипт генерирует из подходящей Windows-установки через [AsmResolver.DotNet 6.0.1](https://www.nuget.org/packages/AsmResolver.DotNet/6.0.1). Два отдельных исправления адаптируют `HGUnityUtils.dll` и `Unity.RenderPipelines.Core.Runtime.dll`. Для всех файлов проверяются SHA-256 из манифеста. Если модуль Unity установлен вне стандартной папки Unity Hub, передай `--unity-support /путь/к/MacStandaloneSupport`.

Сборщик компилирует Unity AI Navigation и Memory Profiler из официальных пакетов Unity. Для `Assembly-CSharp.dll` он берёт соответствующую Windows-сборку, закреплённую версию ILSpy и генератор исходников из Unity Editor. Сборщик применяет к оригинальной Windows-версии `RoR2.dll` исправления совместимости и хранения данных. Локальный провайдер собирается для базовой игры и локальных профилей. Владение DLC проверяет Steam, когда он доступен.

Основной сборщик пересобирает `AK.Wwise.Unity.API.dll` из Windows-сборки и официальных исходников из проверенных архивов Wwise Unity Integration. Выгрузи версии для macOS и Windows из Audiokinetic Launcher. [Настройка SDK](../native/README.ru.md)

## Повторное использование сборок

Если комплект собран из Steam-версии от 8 октября, сборщик заново подготовит `RoR2.dll`, `Assembly-CSharp.dll` и `KinematicCharacterController.dll` из файлов Windows-версии от 14 октября. Для пересборки `Assembly-CSharp.dll` укажи Unity Editor 2023.1.0f1.

Чтобы использовать совместимые файлы из прошлых сборок через `--private`, помести записи `private`, `storage` и `wwise` в `PRIVATE/managed/`. Записи `storage` означают `RoR2.dll` и `ModLoader.dll` до исправления хранения данных. Сверяй их с допустимой контрольной суммой исходной сборки в манифесте. Если у тебя есть подходящий `.app` и резервные копии обеих исходных DLL, выполни команду ниже.

```bash
python3 scripts/build-managed-inputs.py --port-app "$PORT" --pre-storage "$PRE_STORAGE" --private "$PRIVATE"
```

Для Wwise можно использовать готовую проверенную DLL или два указанных ниже файла разработчика в `PRIVATE/wwise/`.

- `AkUnitySoundEnginePINVOKE_Mac.cs` из `Wwise/API/Runtime/Generated/Mac/`.
- `AkVector64.cs` из `Wwise/API/Runtime/Handwritten/Common/`.

Для отдельной проверки подготовленной папки выполни команду ниже.

```bash
python3 scripts/build-managed.py --game "$GAME" --private "$PRIVATE" --check-inputs
```
