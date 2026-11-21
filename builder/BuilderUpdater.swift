import CryptoKit
import Darwin
import Foundation

struct BuilderRelease: Equatable {
    let version: String
    fileprivate let url: URL
    fileprivate let size: Int64
    fileprivate let sha256: String
}

private struct UpdateError: LocalizedError {
    let detail: String
    init(_ detail: String) { self.detail = detail }
    var errorDescription: String? { detail }
}

private struct BuilderVersion: Comparable {
    let value: String
    private let parts: [UInt64]

    init?(_ value: String) {
        let components = value.split(separator: ".", omittingEmptySubsequences: false)
        guard components.count == 3, components.allSatisfy({
            !$0.isEmpty && ($0.count == 1 || $0.first != "0") && $0.utf8.allSatisfy { (48...57).contains($0) }
        }) else { return nil }
        let parts = components.compactMap { UInt64($0) }
        guard parts.count == 3 else { return nil }
        self.value = value
        self.parts = parts
    }

    static func < (lhs: BuilderVersion, rhs: BuilderVersion) -> Bool {
        lhs.parts.lexicographicallyPrecedes(rhs.parts)
    }
}

enum BuilderUpdater {
    private static let project = "TsiFroviK/Risk2Mac"
    private static let bundleID = "io.github.tsifrovik.risk2mac.builder"
    private static let executable = "Contents/MacOS/Risk2MacBuilder"
    private static let helperFlag = "--risk2mac-builder-finish-update"
    private static let stagePrefix = ".risk2mac-builder-update-"
    private static let candidateName = "Risk2Mac Builder.app"
    private static let maxDiskImage: Int64 = 512 * 1024 * 1024
    private static let worker = DispatchQueue(label: bundleID + ".update", qos: .utility)
    private static let files = FileManager.default

    private struct ReleaseListing: Decodable {
        let tag_name: String
        let draft: Bool
        let prerelease: Bool
        let assets: [Asset]
    }

    private struct Asset: Decodable {
        let name: String
        let size: Int64
        let digest: String?
        let state: String
        let browser_download_url: String
    }

    private struct InstallTransaction {
        let id: UUID
        let app: URL
        var directory: URL { app.deletingLastPathComponent().appendingPathComponent(BuilderUpdater.stagePrefix + id.uuidString) }
        var candidate: URL { directory.appendingPathComponent(BuilderUpdater.candidateName) }
        var ready: URL { directory.appendingPathComponent("ready") }
    }

    static func check(currentVersion: String, completion: @escaping (Result<BuilderRelease?, Error>) -> Void) {
        worker.async {
            completion(Result {
                guard (try? installedBundle(version: currentVersion)) != nil else { return nil }
                var releases: [ReleaseListing] = []
                for page in 1...20 {
                    let url = URL(string: "https://api.github.com/repos/\(project)/releases?per_page=100&page=\(page)")!
                    let download = try BuilderTransfer.fetch(url, maxBytes: 4 * 1024 * 1024)
                    let batch = try JSONDecoder().decode([ReleaseListing].self, from: download.data)
                    releases.append(contentsOf: batch)
                    if batch.count < 100 {
                        return try selectRelease(releases, current: currentVersion)
                    }
                }
                throw UpdateError("GitHub returned too many release pages.")
            })
        }
    }

    /// Pure selection for fixture verification. Release timestamps do not determine the version.
    static func selectRelease(_ metadata: Data, currentVersion: String) throws -> BuilderRelease? {
        try selectRelease(JSONDecoder().decode([ReleaseListing].self, from: metadata), current: currentVersion)
    }

    private static func selectRelease(_ releases: [ReleaseListing], current: String) throws -> BuilderRelease? {
        guard let currentVersion = BuilderVersion(current) else { throw UpdateError("Invalid installed builder version.") }
        let candidates = releases.compactMap { release -> (BuilderVersion, ReleaseListing)? in
            let prefix = "builder-v"
            guard !release.draft, !release.prerelease, release.tag_name.hasPrefix(prefix),
                  let version = BuilderVersion(String(release.tag_name.dropFirst(prefix.count))),
                  version > currentVersion,
                  release.assets.contains(where: { $0.name == diskImageName(version.value) && $0.state == "uploaded" }) else {
                return nil
            }
            return (version, release)
        }
        guard let (version, listing) = candidates.max(by: { $0.0 < $1.0 }) else { return nil }
        guard candidates.filter({ $0.0 == version }).count == 1
        else { throw UpdateError("GitHub returned duplicate Builder releases.") }
        let name = diskImageName(version.value)
        let matching = listing.assets.filter { $0.name == name }
        let exactURL = "https://github.com/\(project)/releases/download/\(listing.tag_name)/\(name)"
        guard matching.count == 1, let asset = matching.first, asset.state == "uploaded",
              asset.size > 0, asset.size <= maxDiskImage,
              asset.browser_download_url == exactURL, let url = URL(string: exactURL),
              let digest = asset.digest, digest.hasPrefix("sha256:") else {
            throw UpdateError("GitHub did not publish valid Builder disk image metadata.")
        }
        let hash = String(digest.dropFirst("sha256:".count)).lowercased()
        guard hash.utf8.count == 64,
              hash.utf8.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }) else {
            throw UpdateError("GitHub did not publish a valid Builder SHA-256 digest.")
        }
        return BuilderRelease(version: version.value, url: url, size: asset.size, sha256: hash)
    }

    private static func diskImageName(_ version: String) -> String {
        "Risk2Mac-Builder-\(version)-macOS-universal.dmg"
    }

    static func install(_ release: BuilderRelease, progress: @escaping (Double) -> Void,
                        completion: @escaping (Result<Void, Error>) -> Void) {
        worker.async {
            completion(Result {
                try prepareInstall(version: release.version) { disk in
                    let download = try BuilderTransfer.fetch(release.url, maxBytes: release.size,
                        out: disk, expectedBytes: release.size, progress: progress)
                    guard download.sha256 == release.sha256 else {
                        throw UpdateError("The Builder download did not match GitHub's SHA-256 digest.")
                    }
                }
            })
        }
    }

    #if RISK2MAC_UPDATE_TESTING
    static func installTestFixture(_ dmg: URL, version: String, progress: @escaping (Double) -> Void,
                                   completion: @escaping (Result<Void, Error>) -> Void) {
        worker.async {
            completion(Result {
                try prepareInstall(version: version) { disk in
                    try files.copyItem(at: dmg, to: disk)
                    progress(1)
                }
            })
        }
    }
    #endif

    private static func prepareInstall(version: String, getDisk: (URL) throws -> Void) throws {
        guard let old = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String,
              let current = BuilderVersion(old), let newer = BuilderVersion(version), newer > current else {
            throw UpdateError("The update is not newer than the installed Builder.")
        }
        let transaction = InstallTransaction(id: UUID(), app: try installedBundle(version: old))
        let directory = transaction.directory
        try files.createDirectory(at: directory, withIntermediateDirectories: false,
                                  attributes: [.posixPermissions: 0o700])
        var leaveStaging = false
        var mounted = false
        defer {
            if !leaveStaging && !mounted {
                try? files.removeItem(at: directory)
            }
        }
        try requirePrivateDirectory(directory)
        let disk = directory.appendingPathComponent("Builder.dmg")
        let mount = directory.appendingPathComponent("Mount")
        try getDisk(disk)
        try files.createDirectory(at: mount, withIntermediateDirectories: false)
        mounted = true
        do {
            try run("/usr/bin/hdiutil", ["attach", "-readonly", "-nobrowse", "-noautoopen", "-mountpoint", mount.path, disk.path])
        } catch {
            // hdiutil may have mounted the image before reporting an error. Do not remove a live mount.
            if mountDeviceDiffers(mount, parent: directory) == true {
                try? run("/usr/bin/hdiutil", ["detach", mount.path])
            }
            mounted = mountDeviceDiffers(mount, parent: directory) != false ||
                (try? files.contentsOfDirectory(atPath: mount.path).isEmpty) != true
            throw error
        }
        let source = mount.appendingPathComponent(candidateName)
        let copyResult = Result {
            try verifyApp(source, version: version)
            try run("/usr/bin/ditto", [source.path, transaction.candidate.path])
            try verifyApp(transaction.candidate, version: version)
        }
        try run("/usr/bin/hdiutil", ["detach", mount.path])
        mounted = false
        try copyResult.get()
        let helper = Process()
        helper.executableURL = transaction.app.appendingPathComponent(executable)
        helper.arguments = [helperFlag, transaction.id.uuidString, String(getpid()), old, version]
        helper.currentDirectoryURL = directory
        try helper.run()
        let deadline = ProcessInfo.processInfo.systemUptime + 20
        while !files.fileExists(atPath: transaction.ready.path) {
            guard helper.isRunning, ProcessInfo.processInfo.systemUptime < deadline else {
                if helper.isRunning { helper.terminate() }
                throw UpdateError("The Builder update installer did not become ready.")
            }
            Thread.sleep(forTimeInterval: 0.05)
        }
        leaveStaging = true
    }

    /// Called from App.init. Helper invocations never create a SwiftUI window.
    static func applyPendingIfRequested() {
        let arguments = ProcessInfo.processInfo.arguments
        guard arguments.count > 1 && arguments[1] == helperFlag else { return }
        guard arguments.count == 6,
              let id = UUID(uuidString: arguments[2]), id.uuidString == arguments[2],
              let parent = Int32(arguments[3]), parent > 1, parent == getppid(),
              let current = BuilderVersion(arguments[4]), let next = BuilderVersion(arguments[5]),
              next > current else { Darwin.exit(EXIT_FAILURE) }
        var original: URL?
        var oldExited = false
        do {
            let app = try installedBundle(version: current.value)
            original = app
            let transaction = InstallTransaction(id: id, app: app)
            try requirePrivateDirectory(transaction.directory)
            try verifyApp(transaction.candidate, version: next.value)
            try Data().write(to: transaction.ready, options: .withoutOverwriting)
            try waitForExit(parent)
            oldExited = true
            try withUpdateLock {
                // Recheck the original bundle in case another instance updated it while we waited.
                try verifyApp(app, version: current.value)
                try verifyApp(transaction.candidate, version: next.value)
                try swapBundles(app, transaction.candidate)
                do {
                    try reopen(app)
                } catch {
                    let restartError = error
                    do {
                        try swapBundles(app, transaction.candidate)
                    } catch {
                        throw UpdateError("Could not restore the previous Builder from \(transaction.candidate.path): \(error.localizedDescription)")
                    }
                    throw restartError
                }
                // The old bundle is now in the private staging folder with the downloaded image.
                try? files.removeItem(at: transaction.directory)
            }
            Darwin.exit(EXIT_SUCCESS)
        } catch {
            if oldExited, let app = original {
                savePendingError(error.localizedDescription)
                if (try? appMetadata(app, version: current.value)) != nil {
                    try? reopen(app)
                }
            }
            Darwin.exit(EXIT_FAILURE)
        }
    }

    static func takePendingError() -> String? {
        guard let file = try? stateDirectory().appendingPathComponent("UpdateError.log"),
              let data = try? Data(contentsOf: file) else { return nil }
        try? files.removeItem(at: file)
        return String(data: data.prefix(4096), encoding: .utf8)
    }

    private static func savePendingError(_ message: String) {
        guard let file = try? stateDirectory().appendingPathComponent("UpdateError.log") else { return }
        try? Data(message.utf8.prefix(4096)).write(to: file, options: .atomic)
    }

    private static func stateDirectory() throws -> URL {
        let support = try files.url(for: .applicationSupportDirectory, in: .userDomainMask,
                                    appropriateFor: nil, create: true)
        #if RISK2MAC_UPDATE_TESTING
        let name = bundleID + ".TestUpdate"
        #else
        let name = bundleID + ".Update"
        #endif
        let directory = support.appendingPathComponent(name)
        try files.createDirectory(at: directory, withIntermediateDirectories: true,
                                  attributes: [.posixPermissions: 0o700])
        try requirePrivateDirectory(directory)
        return directory
    }

    private static func withUpdateLock(_ apply: () throws -> Void) throws {
        let file = try stateDirectory().appendingPathComponent("Update.lock")
        let descriptor = Darwin.open(file.path, O_CREAT | O_RDWR | O_NOFOLLOW, 0o600)
        guard descriptor >= 0 else { throw UpdateError("Could not open the Builder update lock.") }
        defer { Darwin.close(descriptor) }
        var status = stat()
        guard fstat(descriptor, &status) == 0, status.st_uid == getuid(),
              (status.st_mode & S_IFMT) == S_IFREG,
              flock(descriptor, LOCK_EX | LOCK_NB) == 0 else {
            throw UpdateError("Another Builder update is being applied.")
        }
        try apply()
    }

    private static func installedBundle(version: String) throws -> URL {
        let app = Bundle.main.bundleURL.resolvingSymlinksInPath()
        guard app.pathExtension.lowercased() == "app",
              Bundle.main.executableURL?.resolvingSymlinksInPath().path == app.appendingPathComponent(executable).path else {
            throw UpdateError("The Builder must be installed as a macOS application.")
        }
        try appMetadata(app, version: version)
        return app
    }

    private static func appMetadata(_ app: URL, version: String) throws {
        let settings = app.appendingPathComponent("Contents/Info.plist")
        guard (try files.attributesOfItem(atPath: app.path)[.type] as? FileAttributeType) == .typeDirectory,
              settings.resolvingSymlinksInPath().path == settings.path,
              let dictionary = try PropertyListSerialization.propertyList(from: Data(contentsOf: settings),
                   format: nil) as? [String: Any] else {
            throw UpdateError("Invalid Builder application bundle.")
        }
        let expected = [
            "CFBundleIdentifier": bundleID, "CFBundleExecutable": "Risk2MacBuilder", "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": version, "CFBundleVersion": version,
        ]
        for (key, value) in expected where (dictionary[key] as? String) != value {
            throw UpdateError("Invalid Builder application metadata: \(key).")
        }
    }

    private static func verifyApp(_ app: URL, version: String) throws {
        try appMetadata(app, version: version)
        let binary = app.appendingPathComponent(executable)
        guard (try files.attributesOfItem(atPath: binary.path)[.type] as? FileAttributeType) == .typeRegular,
              binary.resolvingSymlinksInPath().path == binary.path, files.isExecutableFile(atPath: binary.path) else {
            throw UpdateError("Invalid Builder executable.")
        }
        let handle = try FileHandle(forReadingFrom: binary)
        defer { try? handle.close() }
        guard let header = try handle.read(upToCount: 4096), isUniversalMachO(header) else {
            throw UpdateError("The Builder update must contain Intel and Apple Silicon executables.")
        }
        try run("/usr/bin/codesign",
                ["--verify", "--deep", "--strict", "--all-architectures", app.path])
    }

    static func isUniversalMachO(_ data: Data) -> Bool {
        func beWord(_ offset: Int) -> UInt32 {
            let index = data.startIndex + offset
            return data[index..<(index + 4)].reduce(UInt32(0)) { $0 << 8 | UInt32($1) }
        }
        guard data.count >= 8 else { return false }
        let magic = beWord(0)
        guard magic == 0xcafebabe || magic == 0xcafebabf else { return false }
        let formatSize = magic == 0xcafebabe ? 20 : 32
        let count = Int(beWord(4))
        guard (2...32).contains(count), data.count >= 8 + count * formatSize else { return false }
        let archs = (0..<count).map { beWord(8 + $0 * formatSize) }
        return archs.contains(0x01000007) && archs.contains(0x0100000c)
    }

    private static func requirePrivateDirectory(_ url: URL) throws {
        var status = stat()
        guard lstat(url.path, &status) == 0, status.st_uid == getuid(), status.st_mode & 0o077 == 0,
              (status.st_mode & S_IFMT) == S_IFDIR else {
            throw UpdateError("The Builder needs a writable, private update directory.")
        }
    }

    private static func mountDeviceDiffers(_ mount: URL, parent: URL) -> Bool? {
        var mountInfo = stat()
        var parentInfo = stat()
        guard lstat(mount.path, &mountInfo) == 0, lstat(parent.path, &parentInfo) == 0,
              (mountInfo.st_mode & S_IFMT) == S_IFDIR else { return nil }
        return mountInfo.st_dev != parentInfo.st_dev
    }

    private static func waitForExit(_ parent: Int32) throws {
        let deadline = ProcessInfo.processInfo.systemUptime + 30
        while kill(parent, 0) == 0 || errno != ESRCH {
            guard ProcessInfo.processInfo.systemUptime < deadline else {
                throw UpdateError("The previous Builder did not close for the update.")
            }
            Thread.sleep(forTimeInterval: 0.1)
        }
    }

    private static func reopen(_ app: URL) throws {
        try run("/usr/bin/open", ["-n", app.path])
    }

    private static func swapBundles(_ installed: URL, _ staged: URL) throws {
        if renamex_np(installed.path, staged.path, UInt32(RENAME_SWAP)) == 0 { return }
        let failure = errno
        guard [ENOTSUP, ENOSYS, EINVAL].contains(failure) else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(failure))
        }
        let backup = staged.deletingLastPathComponent().appendingPathComponent("Previous.app")
        try files.moveItem(at: installed, to: backup)
        do {
            try files.moveItem(at: staged, to: installed)
        } catch {
            try files.moveItem(at: backup, to: installed)
            throw error
        }
        do {
            try files.moveItem(at: backup, to: staged)
        } catch {
            try files.moveItem(at: installed, to: staged)
            try files.moveItem(at: backup, to: installed)
            throw error
        }
    }

    private static func run(_ path: String, _ arguments: [String]) throws {
        let task = Process()
        let output = Pipe()
        task.executableURL = URL(fileURLWithPath: path)
        task.arguments = arguments
        task.standardOutput = output
        task.standardError = output
        try task.run()
        let detail = output.fileHandleForReading.readDataToEndOfFile()
        task.waitUntilExit()
        guard task.terminationStatus == 0 else {
            let message = String(data: detail.prefix(1600), encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            throw UpdateError("\(task.executableURL!.lastPathComponent) exited with status \(task.terminationStatus). \(message)")
        }
    }
}

private final class BuilderTransfer: NSObject, URLSessionDataDelegate {
    struct ResultData {
        let data: Data
        let sha256: String
    }

    private let limit: Int64
    private let expected: Int64?
    private let handle: FileHandle?
    private let progress: (Double) -> Void
    private let finished = DispatchSemaphore(value: 0)
    private var buffer = Data()
    private var hasher = SHA256()
    private var count: Int64 = 0
    private var redirects = 0
    private var failure: Error?

    private init(limit: Int64, expected: Int64?, handle: FileHandle?, progress: @escaping (Double) -> Void) {
        self.limit = limit
        self.expected = expected
        self.handle = handle
        self.progress = progress
    }

    static func allowed(_ url: URL) -> Bool {
        guard url.scheme == "https", url.port == nil, url.user == nil, url.password == nil,
              let host = url.host else { return false }
        return ["api.github.com", "github.com", "release-assets.githubusercontent.com",
                "objects.githubusercontent.com", "github-releases.githubusercontent.com"].contains(host)
    }

    static func fetch(_ url: URL, maxBytes: Int64, out: URL? = nil, expectedBytes: Int64? = nil,
                      progress: @escaping (Double) -> Void = { _ in }) throws -> ResultData {
        guard allowed(url) else { throw UpdateError("Untrusted Builder download URL.") }
        var handle: FileHandle?
        if let out = out {
            guard FileManager.default.createFile(atPath: out.path, contents: nil, attributes: [.posixPermissions: 0o600])
            else { throw UpdateError("Could not create the Builder download file.") }
            handle = try FileHandle(forWritingTo: out)
        }
        defer { try? handle?.close() }
        let transfer = BuilderTransfer(limit: maxBytes, expected: expectedBytes, handle: handle, progress: progress)
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 30
        config.timeoutIntervalForResource = out == nil ? 60 : 600
        config.httpShouldSetCookies = false
        config.urlCredentialStorage = nil
        config.urlCache = nil
        var request = URLRequest(url: url)
        request.setValue("Risk2Mac-Builder-Updater", forHTTPHeaderField: "User-Agent")
        if out == nil {
            request.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        }
        let session = URLSession(configuration: config, delegate: transfer, delegateQueue: nil)
        session.dataTask(with: request).resume()
        transfer.finished.wait()
        session.finishTasksAndInvalidate()
        if let error = transfer.failure { throw error }
        let hash = transfer.hasher.finalize().map { String(format: "%02x", $0) }.joined()
        return ResultData(data: transfer.buffer, sha256: hash)
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        guard redirects < 4, let url = request.url, Self.allowed(url) else {
            failure = UpdateError("GitHub returned an unexpected Builder download redirect.")
            completionHandler(nil)
            return
        }
        redirects += 1
        completionHandler(request)
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive response: URLResponse,
                    completionHandler: @escaping (URLSession.ResponseDisposition) -> Void) {
        guard failure == nil,
              let response = response as? HTTPURLResponse, let url = response.url,
              Self.allowed(url), response.statusCode == 200,
              response.expectedContentLength <= limit else {
            failure = failure ?? UpdateError("GitHub returned an invalid Builder response.")
            completionHandler(.cancel)
            return
        }
        completionHandler(.allow)
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        count += Int64(data.count)
        guard failure == nil && count <= limit else {
            failure = failure ?? UpdateError("The Builder download exceeded its declared size.")
            dataTask.cancel()
            return
        }
        do {
            if let handle = handle {
                try handle.write(contentsOf: data)
                hasher.update(data: data)
            } else {
                buffer.append(data)
            }
            if let expected = expected { progress(Double(count) / Double(expected)) }
        } catch {
            failure = error
            dataTask.cancel()
        }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        if failure == nil {
            failure = error
            if let expected = expected, count != expected {
                failure = failure ?? UpdateError("The Builder download did not match its declared size.")
            }
        }
        finished.signal()
    }
}
