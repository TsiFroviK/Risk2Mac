# Нативные компоненты

[English](README.md)

Risk2Mac использует macOS Mono Player из **Unity 2023.1.0f1** и плагин **Wwise Unity Integration 2024.1.18 Release** для macOS. Получите их по условиям поставщиков и храните в закрытой папке сборки за пределами Git.

Нажмите **«Настроить Unity»** или **«Настроить Wwise»** в графическом сборщике. Из корня репозитория те же действия доступны командами ниже.

```bash
bash build.sh --setup unity
bash build.sh --setup wwise
```

Войдите в Unity Hub, установите Unity 2023.1.0f1 и активируйте лицензию редактора. Если Hub недоступен, команда откроет страницу этой версии на сайте Unity. Активированный редактор используется для генерации штатной заставки Unity и компиляции шейдеров Metal. [Установка и вход в Unity Hub](https://docs.unity.com/en-us/hub/install-hub-win-mac)

Скрипт находит стандартную установку Unity Hub в `/Applications/Unity/Hub/Editor/2023.1.0f1`. Если локального плеера или модуля нет, он скачивает официальный Mac Mono Build Support, проверяет SHA-256 и извлекает плеер и 70 подходящих DLL в кэш. Полный редактор предоставляет дополнительный профиль Mono для macOS и может скомпилировать шейдер копирования глубины. Для нестандартного расположения укажите `--unity-support` или поместите `MacStandaloneSupport` в `<private>/native/UnityMacSupport`. В модуле должны быть следующие компоненты.

```text
MacStandaloneSupport/
  Variations/macos_x64arm64_player_nondevelopment_mono/UnityPlayer.app/
  MonoBleedingEdge/etc/
  Source/Player/MacPlayer/MacPlayerEntryPoint/Resources/MainMenu.nib/
```

Подойдёт и штатный Mono Player для одной архитектуры из варианта `macos_arm64_player_nondevelopment_mono` или `macos_x64_player_nondevelopment_mono`. [Архив версий Unity](https://unity.com/releases/editor/archive)

Войдите в Audiokinetic Launcher. В разделе **Unity → Offline Integration Files** выгрузите версию **2024.1.18** для macOS и Windows в «Загрузки». Основной сборщик находит `Unity.Mac.tar.xz` и `Unity.Windows.tar.xz`, сверяет SHA‑256 и извлекает нужные файлы во время сборки. Локальный архив или распакованную интеграцию также можно указать через `--wwise`. Готовые файлы в `<private>/native/wwise/` по-прежнему поддерживаются. [Загрузки Audiokinetic](https://www.audiokinetic.com/en/download/) · [Пример выгрузки offline-пакетов](https://www.youtube.com/watch?v=KvgcYpvOtWk&t=825s)

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
