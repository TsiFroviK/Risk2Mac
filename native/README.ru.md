# Нативные компоненты

[English](README.md)

Risk2Mac использует macOS Mono Player из **Unity 2023.1.0f1** и плагин **Wwise Unity Integration 2024.1.18 Release** для macOS. Получите их по условиям поставщиков и храните в закрытой папке сборки за пределами Git.

Установите эту версию Unity и модуль сборки macOS Mono через Unity Hub. Скрипт найдёт стандартную установку в `/Applications/Unity/Hub/Editor/2023.1.0f1`. Для другого расположения поместите папку `MacStandaloneSupport` или ссылку на неё по пути `<private>/native/UnityMacSupport`. В ней должны быть следующие компоненты.

```text
MacStandaloneSupport/
  Variations/macos_x64arm64_player_nondevelopment_mono/UnityPlayer.app/
  MonoBleedingEdge/etc/
  Source/Player/MacPlayer/MacPlayerEntryPoint/Resources/MainMenu.nib/
```

Подойдёт и штатный Mono Player для одной архитектуры из варианта `macos_arm64_player_nondevelopment_mono` или `macos_x64_player_nondevelopment_mono`. [Архив версий Unity](https://unity.com/releases/editor/archive)

Получите `Unity.Mac.tar.xz` через Audiokinetic Launcher или из доступной вам лицензионной загрузки интеграции. Поместите архив в `<private>/native/wwise/Unity.Mac.tar.xz`. Уже распакованный `AkUnitySoundEngine.bundle` из каталога Release того же архива можно поместить в `<private>/native/wwise/AkUnitySoundEngine.bundle`. Скрипт сверит контрольную сумму исполняемого файла перед выбором архитектуры. [Загрузки Audiokinetic](https://www.audiokinetic.com/en/download/)

Установите инструменты командной строки Xcode командой `xcode-select --install`. Скрипт выбирает нужную архитектуру в Unity и Wwise с помощью `lipo` и компилирует модуль крестовины из исходника Objective-C в репозитории. Для модуля задана минимальная версия macOS 11. Готовое приложение подписывает основной скрипт сборки. [Инструменты Apple](https://developer.apple.com/documentation/xcode/installing-the-command-line-tools)

Если у вас уже есть текущая частная сборка порта и вы можете использовать её компоненты, скопируйте только нужные нативные файлы этой командой из корня репозитория. Подкаталог `native` в выбранной папке должен быть новым.

```bash
bash scripts/build-native-inputs.sh \
  --port-app "/путь/к/Risk of Rain 2.app" \
  --private "/путь/к/закрытым-файлам-сборки"
```

Скрипт извлечёт Unity Player с четырьмя библиотеками, настройки Mono, два ресурса Unity и комплект Wwise. Результат храните отдельно от публикуемого репозитория.

Основной скрипт автоматически запускает этап сборки нативных компонентов. Для отдельного запуска используйте новую промежуточную папку `.app`. Расположение исходных компонентов можно явно передать через `--unity-support /путь/к/MacStandaloneSupport` или `--wwise /путь/к/Unity.Mac.tar.xz`.

```bash
bash scripts/build-native.sh \
  --game "/путь/к/Windows/Risk of Rain 2" \
  --app "/путь/к/промежуточному/Risk of Rain 2.app" \
  --private "/путь/к/закрытым-файлам-сборки" \
  --arch arm64
```

Для Intel укажите `x86_64`. Для запуска игры требуется также подготовить ресурсы, собрать управляемый код и подписать `.app` по основной инструкции.
