import AppKit
import SwiftUI

@main
struct Risk2MacBuilder: App {
    @StateObject private var build = BuildModel()
    @StateObject private var updates = BuilderUpdates()

    init() {
        BuilderUpdater.applyPendingIfRequested()
    }

    var body: some Scene {
        WindowGroup("Risk2Mac Builder") {
            BuilderView(build: build, updates: updates)
                .frame(minWidth: 690, minHeight: 535)
        }
        Settings {
            BuilderSettings(updates: updates)
        }
    }
}

private func tr(_ en: String, _ ru: String) -> String {
    guard let preferred = Locale.preferredLanguages.first else { return en }
    return Locale(identifier: preferred).languageCode == "ru" ? ru : en
}

private struct BuilderView: View {
    @ObservedObject var build: BuildModel
    @ObservedObject var updates: BuilderUpdates
    @AppStorage("game") private var game = ""
    @AppStorage("prerequisites") private var prerequisites = ""
    @AppStorage("destination") private var destination = ""
    @AppStorage("steam") private var steam = true
    @AppStorage("steamLibrary") private var steamLibrary = ""
    @AppStorage("unity") private var unity = ""
    @AppStorage("wwise") private var wwise = ""
    @AppStorage("wwiser") private var wwiser = ""
    @AppStorage("dotnet") private var dotnet = ""
    @AppStorage("tools") private var tools = ""
    @AppStorage("arch") private var arch = ""
    @State private var advanced = false
    @State private var windowID = UUID()

    private var busy: Bool { build.running || updates.installing }

    private var updatePresented: Binding<Bool> {
        Binding(
            get: { updates.sheetWindow == windowID && updates.dialog != nil && !build.running },
            set: { if !$0 && !build.running && updates.sheetWindow == windowID { updates.dismiss() } }
        )
    }

    var body: some View {
        HStack(spacing: 0) {
            VStack(alignment: .leading, spacing: 14) {
                Image(nsImage: NSApp.applicationIconImage)
                    .resizable().frame(width: 60, height: 60)
                    .accessibilityHidden(true)
                Text("Risk2Mac").font(.system(size: 25, weight: .semibold))
                Text(tr("macOS build tool", "Сборщик для macOS"))
                    .font(.callout).foregroundColor(.secondary)
                Spacer()
                Button(tr("Build instructions ↗", "Инструкция ↗")) {
                    let instructions = tr("https://github.com/TsiFroviK/Risk2Mac#requirements",
                                          "https://github.com/TsiFroviK/Risk2Mac/blob/main/README.ru.md")
                    if let url = URL(string: instructions) {
                        NSWorkspace.shared.open(url)
                    }
                }.buttonStyle(PlainButtonStyle()).foregroundColor(.accentColor)
            }
            .padding(23).frame(width: 175, alignment: .leading)
            .background(Color(NSColor.underPageBackgroundColor))
            Divider()
            VStack(alignment: .leading, spacing: 0) {
                ScrollView {
                    VStack(alignment: .leading, spacing: 17) {
                        Text(tr("Build Risk of Rain 2", "Сборка Risk of Rain 2"))
                            .font(.system(size: 25, weight: .semibold))
                            .accessibilityAddTraits(.isHeader)
                        VStack(alignment: .leading, spacing: 12) {
                            PathRow(title: tr("Windows game folder", "Папка игры для Windows"), path: $game)
                            PathRow(title: tr("Local port files", "Локальные файлы порта"), path: $prerequisites,
                                    hint: "Prerequisites")
                            Text(tr("Choose the folder with the remaining converted Unity assets and port assemblies.",
                                    "Укажите папку с оставшимися преобразованными ресурсами Unity и сборками порта."))
                                .font(.caption).foregroundColor(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        Divider()
                        Toggle(tr("Steam integration", "Интеграция Steam"), isOn: $steam)
                            .toggleStyle(SwitchToggleStyle())
                        if steam {
                            PathRow(title: tr("Steam library", "Библиотека Steam"), path: $steamLibrary,
                                    hint: tr("Default Steam library", "Основная библиотека Steam"))
                            Text(tr("The app is built inside this Steam library.",
                                    "Приложение будет собрано в выбранной библиотеке Steam."))
                                .font(.caption).foregroundColor(.secondary)
                        } else {
                            PathRow(title: tr("Output folder", "Папка для готовой игры"), path: $destination,
                                    canCreateDirectories: true)
                        }
                        Divider()
                        DisclosureGroup(tr("Advanced inputs", "Дополнительные параметры"), isExpanded: $advanced) {
                            VStack(alignment: .leading, spacing: 12) {
                                PathRow(title: "Unity 2023.1.0f1 MacStandaloneSupport", path: $unity)
                                PathRow(title: "Wwise 2024.1.18", path: $wwise, selection: .either)
                                PathRow(title: "wwiser", path: $wwiser,
                                        hint: tr("Downloaded when needed", "Скачивается при необходимости"))
                                PathRow(title: tr(".NET 8 executable", "Исполняемый файл .NET 8"), path: $dotnet, selection: .file)
                                PathRow(title: tr("Tool cache", "Кэш инструментов"), path: $tools, canCreateDirectories: true)
                                Picker(tr("Architecture", "Архитектура"), selection: $arch) {
                                    Text(tr("This Mac", "Этот Mac")).tag("")
                                    Text("Apple Silicon (arm64)").tag("arm64")
                                    Text("Intel (x86_64)").tag("x86_64")
                                }
                            }.padding(.top, 12)
                        }
                    }
                    .padding(24)
                    .disabled(busy)
                }
                Divider()
                VStack(alignment: .leading, spacing: 9) {
                    if build.running {
                        if let progress = build.progress {
                            ProgressView(value: progress).accessibilityLabel(tr("Build progress", "Ход сборки"))
                        } else {
                            ProgressView().controlSize(.small)
                        }
                    }
                    if !build.status.isEmpty {
                        Text(build.status)
                            .foregroundColor(build.failed ? Color(NSColor.systemRed) : .secondary)
                            .fixedSize(horizontal: false, vertical: true)
                            .textSelectionIfAvailable()
                    }
                    HStack {
                        if build.logURL != nil {
                            Button(tr("Show log", "Открыть журнал")) {
                                if let url = build.logURL { NSWorkspace.shared.open(url) }
                            }
                        }
                        if let app = build.builtApp {
                            Button(tr("Show in Finder", "Показать в Finder")) {
                                NSWorkspace.shared.activateFileViewerSelecting([app])
                            }
                            if build.needsSteamShortcut {
                                Button(tr("Add to Steam", "Добавить в Steam")) {
                                    if !busy { build.registerInSteam(app) }
                                }.disabled(busy)
                            }
                        }
                        Spacer()
                        Button(tr("Build", "Собрать"), action: beginBuild)
                            .keyboardShortcut(.defaultAction)
                            .disabled(busy || game.trimmed.isEmpty || prerequisites.trimmed.isEmpty
                                      || (!steam && destination.trimmed.isEmpty))
                    }
                }.padding(.horizontal, 24).padding(.vertical, 15)
            }
        }
        .frame(idealWidth: 780, idealHeight: 600)
        .onAppear { updates.attachWindow(windowID) }
        .onDisappear { updates.detachWindow(windowID) }
        .sheet(isPresented: updatePresented) {
            UpdateSheet(updates: updates, build: build)
        }
    }

    private func beginBuild() {
        guard !busy, !game.trimmed.isEmpty, !prerequisites.trimmed.isEmpty,
              steam || !destination.trimmed.isEmpty else { return }
        var arguments = ["--game", game.trimmed, "--private", prerequisites.trimmed]
        let output: URL?
        if steam {
            arguments.append("--steam")
            arguments.appendPath("--steam-library", steamLibrary)
            output = nil
        } else {
            let app = URL(fileURLWithPath: (destination.trimmed as NSString).expandingTildeInPath)
                .appendingPathComponent("Risk of Rain 2.app", isDirectory: true)
            arguments += ["--output", app.path]
            output = app
        }
        arguments.appendPath("--unity-support", unity)
        arguments.appendPath("--wwise", wwise)
        arguments.appendPath("--wwiser", wwiser)
        arguments.appendPath("--dotnet", dotnet)
        arguments.appendPath("--tools", tools)
        arguments.appendPath("--arch", arch)
        build.start(arguments: arguments, steam: steam, prerequisites: prerequisites.trimmed, output: output)
    }
}

private struct BuilderSettings: View {
    @ObservedObject var updates: BuilderUpdates

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Toggle(tr("Check for updates", "Проверять обновления"), isOn: Binding(
                get: { updates.checksEnabled },
                set: { updates.setChecksEnabled($0) }
            ))
            .toggleStyle(SwitchToggleStyle())
            .disabled(updates.installing)

            if let error = updates.checkError {
                Text(tr("Could not check for updates.", "Не удалось проверить обновления."))
                    .fontWeight(.medium)
                Text(error).font(.caption).foregroundColor(.secondary).textSelectionIfAvailable()
                Button(tr("Try again", "Повторить")) { updates.check() }
                    .disabled(updates.checking || updates.installing)
            }
        }
        .padding(22)
        .frame(width: 385, alignment: .leading)
    }
}

private struct UpdateSheet: View {
    @ObservedObject var updates: BuilderUpdates
    @ObservedObject var build: BuildModel

    var body: some View {
        VStack(alignment: .leading, spacing: 13) {
            if let dialog = updates.dialog {
                switch dialog {
                case let .offer(release):
                    heading(tr("Risk2Mac Builder update available", "Доступно обновление Risk2Mac Builder"))
                    Text("\(updates.currentVersion) -> \(release.version)").font(.headline)
                    Text(tr("Risk2Mac Builder will install the update and restart.",
                            "Risk2Mac Builder установит обновление и перезапустится."))
                        .foregroundColor(.secondary)
                    Divider().padding(.vertical, 3)
                    HStack {
                        Spacer()
                        Button(tr("Update", "Обновить")) {
                            if !build.running { updates.install(release) }
                        }
                        .keyboardShortcut(.defaultAction)
                        .disabled(build.running)
                        Button(tr("Later", "Позже"), action: updates.dismiss)
                            .keyboardShortcut(.cancelAction)
                        Button(tr("Don't remind me", "Не напоминать")) { updates.setChecksEnabled(false) }
                    }
                case let .installing(progress):
                    heading(tr("Updating Risk2Mac Builder", "Обновление Risk2Mac Builder"))
                    Text(progress < 1
                         ? tr("Downloading the disk image…", "Скачивание образа DMG…")
                         : tr("Verifying and installing…", "Проверка и установка…"))
                        .foregroundColor(.secondary)
                    HStack {
                        ProgressView(value: progress)
                            .accessibilityLabel(tr("Update progress", "Ход обновления"))
                        Text("\(Int(progress * 100))%").font(.system(.caption, design: .monospaced))
                    }
                case let .failure(message, release):
                    heading(tr("Could not update Risk2Mac Builder", "Не удалось обновить Risk2Mac Builder"))
                    ScrollView {
                        Text(message).frame(maxWidth: .infinity, alignment: .leading)
                            .font(.callout).foregroundColor(.secondary).textSelectionIfAvailable()
                    }.frame(maxHeight: 125)
                    HStack {
                        Spacer()
                        Button(tr("Later", "Позже"), action: updates.dismiss)
                            .keyboardShortcut(.cancelAction)
                        if updates.checksEnabled {
                            Button(tr("Try again", "Повторить")) {
                                guard !build.running else { return }
                                if let release = release {
                                    updates.install(release)
                                } else {
                                    updates.dismiss()
                                    updates.check(showFailure: true)
                                }
                            }
                            .keyboardShortcut(.defaultAction)
                            .disabled(build.running)
                        }
                    }
                }
            }
        }
        .padding(24)
        .frame(width: 450, alignment: .leading)
        .preventDismissalIfAvailable(updates.installing)
    }

    private func heading(_ title: String) -> some View {
        Text(title).font(.title2).fontWeight(.semibold).accessibilityAddTraits(.isHeader)
    }
}

private final class BuilderUpdates: ObservableObject {
    enum Dialog {
        case offer(BuilderRelease)
        case installing(Double)
        case failure(String, BuilderRelease?)
    }

    private static let preference = "checkUpdates"
    private static let interval: TimeInterval = 6 * 60 * 60

    let currentVersion = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0.0.0"
    @Published private(set) var checksEnabled = UserDefaults.standard.object(forKey: BuilderUpdates.preference) as? Bool ?? true
    @Published private(set) var dialog: Dialog?
    @Published private(set) var checkError: String?
    @Published private(set) var checking = false
    @Published private(set) var sheetWindow: UUID?

    private var windows: [UUID] = []
    private var timer: Timer?
    private var checkToken: UUID?

    var installing: Bool {
        if case .installing? = dialog { return true }
        return false
    }

    func attachWindow(_ id: UUID) {
        if !windows.contains(id) { windows.append(id) }
        if sheetWindow == nil { sheetWindow = id }
        guard timer == nil else { return }
        let timer = Timer(timeInterval: Self.interval, repeats: true) { [weak self] _ in self?.check() }
        self.timer = timer
        RunLoop.main.add(timer, forMode: .common)
        if let failure = BuilderUpdater.takePendingError() {
            dialog = .failure(failure, nil)
        } else {
            check()
        }
    }

    func detachWindow(_ id: UUID) {
        windows.removeAll { $0 == id }
        if sheetWindow == id { sheetWindow = windows.first }
    }

    func setChecksEnabled(_ enabled: Bool) {
        guard checksEnabled != enabled, !installing else { return }
        checksEnabled = enabled
        UserDefaults.standard.set(enabled, forKey: Self.preference)
        if enabled {
            check()
        } else {
            checkToken = nil
            checking = false
            checkError = nil
            dialog = nil
        }
    }

    func check(showFailure: Bool = false) {
        guard checksEnabled, !checking, dialog == nil else { return }
        postponeAutomaticCheck()
        let token = UUID()
        checkToken = token
        checking = true
        BuilderUpdater.check(currentVersion: currentVersion) { [weak self] result in
            DispatchQueue.main.async {
                guard let self = self, self.checkToken == token else { return }
                self.checkToken = nil
                self.checking = false
                switch result {
                case let .success(release):
                    self.checkError = nil
                    if let release = release { self.dialog = .offer(release) }
                case let .failure(error):
                    self.checkError = error.localizedDescription
                    if showFailure { self.dialog = .failure(error.localizedDescription, nil) }
                }
            }
        }
    }

    func install(_ release: BuilderRelease) {
        guard checksEnabled, !installing else { return }
        dialog = .installing(0)
        BuilderUpdater.install(release, progress: { [weak self] progress in
            DispatchQueue.main.async {
                guard let self = self, case let .installing(previous)? = self.dialog,
                      progress.isFinite else { return }
                self.dialog = .installing(max(previous, min(progress, 1)))
            }
        }, completion: { [weak self] result in
            DispatchQueue.main.async {
                guard let self = self else { return }
                switch result {
                case .success:
                    self.dialog = .installing(1)
                    NSApp.terminate(nil)
                case let .failure(error):
                    self.dialog = .failure(error.localizedDescription, release)
                }
            }
        })
    }

    func dismiss() {
        guard dialog != nil, !installing else { return }
        dialog = nil
        postponeAutomaticCheck()
    }

    private func postponeAutomaticCheck() {
        timer?.fireDate = Date().addingTimeInterval(Self.interval)
    }
}

private extension View {
    @ViewBuilder func textSelectionIfAvailable() -> some View {
        if #available(macOS 12, *) { textSelection(.enabled) } else { self }
    }

    @ViewBuilder func preventDismissalIfAvailable(_ prevent: Bool) -> some View {
        if #available(macOS 12, *) { interactiveDismissDisabled(prevent) } else { self }
    }
}

private extension String {
    var trimmed: String { trimmingCharacters(in: .whitespacesAndNewlines) }
}

private extension Array where Element == String {
    mutating func appendPath(_ option: String, _ value: String) {
        if !value.trimmed.isEmpty { append(contentsOf: [option, value.trimmed]) }
    }
}

private struct PathRow: View {
    enum Selection { case folder, file, either }
    let title: String
    @Binding var path: String
    var hint = ""
    var selection: Selection = .folder
    var canCreateDirectories = false

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title).font(.callout).fontWeight(.medium)
            HStack {
                TextField(hint, text: $path)
                    .textFieldStyle(RoundedBorderTextFieldStyle()).accessibilityLabel(title)
                Button(tr("Choose…", "Выбрать…"), action: choose)
                    .accessibilityLabel("\(tr("Choose", "Выбрать")) \(title)")
            }
        }
    }

    private func choose() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = selection != .folder
        panel.canChooseDirectories = selection != .file
        panel.canCreateDirectories = canCreateDirectories
        panel.allowsMultipleSelection = false
        panel.message = title
        if !path.isEmpty {
            let url = URL(fileURLWithPath: path)
            panel.directoryURL = selection == .folder ? url : url.deletingLastPathComponent()
        }
        panel.begin { result in
            if result == .OK, let url = panel.url { path = url.path }
        }
    }
}

private final class BuildModel: ObservableObject {
    @Published private(set) var running = false
    @Published private(set) var failed = false
    @Published private(set) var progress: Double?
    @Published private(set) var status = ""
    @Published private(set) var logURL: URL?
    @Published private(set) var builtApp: URL?
    @Published private(set) var needsSteamShortcut = false

    func start(arguments: [String], steam: Bool, prerequisites: String, output: URL?) {
        guard !running, let recipe = Bundle.main.resourceURL?.appendingPathComponent("Recipe") else { return }
        running = true
        failed = false
        progress = nil
        builtApp = nil
        needsSteamShortcut = false
        status = tr("Preparing build…", "Подготовка сборки…")
        logURL = nil
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                let logs = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/Risk2Mac Builder")
                try FileManager.default.createDirectory(at: logs, withIntermediateDirectories: true)
                let logPath = logs.appendingPathComponent("Build-\(UUID().uuidString).log")
                FileManager.default.createFile(atPath: logPath.path, contents: nil)
                let journal = try FileHandle(forWritingTo: logPath)
                defer { try? journal.close() }
                DispatchQueue.main.async { self.logURL = logPath }

                try self.run("/usr/bin/xcode-select", ["-p"], recipe: recipe, journal: journal) { _ in }
                if steam {
                    try self.run("/usr/bin/python3", ["-u", "scripts/prepare-steam.py", "--private", prerequisites], recipe: recipe, journal: journal) { _ in }
                }
                var app = output
                var registered = false
                try self.run("/usr/bin/python3", ["-u", "scripts/build.py"] + arguments, recipe: recipe, journal: journal) { line in
                    if line.hasPrefix("Built ") { app = URL(fileURLWithPath: String(line.dropFirst(6))) }
                    if line.hasPrefix("Steam shortcut registered.") || line.hasPrefix("Steam shortcut was already registered.") {
                        registered = true
                    }
                    if line.hasPrefix("["), let phase = line.dropFirst().first?.wholeNumberValue,
                       (1...4).contains(phase), line.dropFirst(2).hasPrefix("/4]") {
                        let titles = [tr("Native runtime", "Нативная среда"), tr("Game data", "Данные игры"),
                                      tr("Managed assemblies", "Сборки .NET"), tr("App bundle and signature", "Приложение и подпись")]
                        DispatchQueue.main.async {
                            self.progress = Double(phase - 1) / 4.0
                            self.status = "\(phase) / 4  ·  \(titles[phase - 1])"
                        }
                    }
                }
                let built = app
                let addedToSteam = registered
                DispatchQueue.main.async {
                    self.running = false
                    self.progress = 1
                    self.needsSteamShortcut = steam && !addedToSteam
                    if self.needsSteamShortcut {
                        self.status = tr("Build complete. Quit Steam, then click Add to Steam.",
                                         "Сборка готова. Закройте Steam и нажмите «Добавить в Steam».")
                    } else if addedToSteam {
                        self.status = tr("Build complete. Open Steam to play from your library.",
                                         "Сборка готова. Откройте Steam, чтобы запустить игру из библиотеки.")
                    } else {
                        self.status = tr("Build complete.", "Сборка готова.")
                    }
                    self.builtApp = built
                }
            } catch {
                DispatchQueue.main.async {
                    self.running = false
                    self.failed = true
                    self.status = self.localizedFailure(error)
                }
            }
        }
    }

    func registerInSteam(_ app: URL) {
        guard !running, let log = logURL,
              let recipe = Bundle.main.resourceURL?.appendingPathComponent("Recipe") else { return }
        running = true
        failed = false
        progress = nil
        status = tr("Adding the Steam shortcut…", "Добавление ярлыка Steam…")
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                let journal = try FileHandle(forWritingTo: log)
                defer { try? journal.close() }
                try journal.seekToEnd()
                try self.run("/usr/bin/python3", ["-u", "scripts/steam_install.py", "--register-shortcut", app.path],
                             recipe: recipe, journal: journal) { _ in }
                DispatchQueue.main.async {
                    self.running = false
                    self.needsSteamShortcut = false
                    self.status = tr("Open Steam to play from your library.", "Откройте Steam, чтобы запустить игру из библиотеки.")
                }
            } catch {
                DispatchQueue.main.async {
                    self.running = false
                    self.failed = true
                    self.status = self.localizedFailure(error)
                }
            }
        }
    }

    private func localizedFailure(_ error: Error) -> String {
        let detail = error.localizedDescription
        if detail.contains("Quit Steam") {
            return tr("Quit Steam and try adding the shortcut again.",
                      "Закройте Steam и повторите добавление ярлыка.")
        }
        if detail.hasPrefix("Risk2Mac:") || detail.hasPrefix("Risk2Mac Steam") {
            return tr(detail, "Сборщик не смог завершить действие. Причина указана в журнале.")
        }
        return detail
    }

    private func run(_ executable: String, _ args: [String], recipe: URL, journal: FileHandle,
                     onLine: (String) -> Void) throws {
        let process = Process()
        let pipe = Pipe()
        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin"
        process.environment = environment
        process.executableURL = URL(fileURLWithPath: executable)
        process.currentDirectoryURL = recipe
        process.arguments = args
        process.standardOutput = pipe
        process.standardError = pipe
        process.standardInput = FileHandle.nullDevice
        try process.run()
        defer { try? pipe.fileHandleForReading.close() }
        var pending = Data()
        var detail: String?
        func line(_ bytes: Data) {
            let value = String(decoding: bytes, as: UTF8.self).trimmed
            if value.hasPrefix("Risk2Mac:") || value.hasPrefix("Risk2Mac Steam") {
                detail = value
            }
            onLine(value)
        }
        while let data = try pipe.fileHandleForReading.read(upToCount: 16_384), !data.isEmpty {
            try journal.write(contentsOf: data)
            pending.append(data)
            while let end = pending.firstIndex(of: 10) {
                line(Data(pending[..<end]))
                pending.removeSubrange(...end)
            }
            if pending.count > 65_536 { pending.removeAll() }
        }
        if !pending.isEmpty { line(pending) }
        process.waitUntilExit()
        if process.terminationStatus != 0 {
            let fallback = executable == "/usr/bin/xcode-select"
                ? tr("Install Xcode Command Line Tools and try again.", "Установите Xcode Command Line Tools и повторите сборку.")
                : tr("The build failed. Open the log for details.", "Сборка завершилась ошибкой. Откройте журнал для подробностей.")
            throw NSError(domain: "Risk2Mac.Builder", code: Int(process.terminationStatus),
                          userInfo: [NSLocalizedDescriptionKey: detail ?? fallback])
        }
    }
}
