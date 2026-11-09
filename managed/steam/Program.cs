using Mono.Cecil;
using Mono.Cecil.Cil;
using System.Security.Cryptography;
using System.Text.Json;

if (args.Length != 3) throw new ArgumentException("Patcher <existing Managed> <Risk2Mac.Steam.dll> <new output>");
string source = Path.GetFullPath(args[0]);
string helperPath = Path.GetFullPath(args[1]);
string output = Path.GetFullPath(args[2]);
if (Directory.Exists(output)) throw new IOException("Candidate output already exists");
if (output.StartsWith(source + Path.DirectorySeparatorChar) || output == source)
    throw new IOException("Output must be outside the source");
var resolver = new DefaultAssemblyResolver();
resolver.AddSearchDirectory(source);
resolver.AddSearchDirectory(Path.GetDirectoryName(helperPath)!);
var reader = new ReaderParameters { AssemblyResolver = resolver, InMemory = true };
using var helper = AssemblyDefinition.ReadAssembly(helperPath, reader);
var bridge = helper.MainModule.GetType("Risk2Mac.SteamCompatibility");
Directory.CreateDirectory(output);
var report = new List<object>();
var expected = new Dictionary<string, string> {
    ["RoR2.dll"] = "b6dcf730d3c1ce9245b2fd035cea7042ee88342e7fa9bcc31d5a6291895d9c9c"
};
foreach (string name in new[] { "RoR2.dll", "RoR2Arm64.OfflinePlatform.dll", "RoR2Arm64.ManagedSolo.dll", "Facepunch.Steamworks.dll" })
{
    string input = Path.Combine(source, name);
    string beforeHash = Hash(input);
    if (expected.TryGetValue(name, out string? expectedHash) && beforeHash != expectedHash)
        throw new InvalidDataException("Unreviewed source " + name);
    using var assembly = AssemblyDefinition.ReadAssembly(input, reader);
    var module = assembly.MainModule;
    var originalBodies = Types(module.Types).SelectMany(t => t.Methods).ToDictionary(m => m.FullName, BodyFingerprint);
    var changes = new List<string>();
    if (name == "RoR2.dll")
    {
        var constructor = module.GetType("RoR2.SteamworksClientManager").Methods.Single(m => m.IsConstructor && !m.IsStatic);
        var clientAllocations = constructor.Body.Instructions.Where(i => i.OpCode == OpCodes.Newobj &&
            i.Operand is MethodReference m && m.DeclaringType.FullName == "Facepunch.Steamworks.Client").ToArray();
        if (clientAllocations.Length != 1) throw new InvalidDataException("Expected one original Steam client allocation");
        clientAllocations[0].OpCode = OpCodes.Call;
        clientAllocations[0].Operand = module.ImportReference(bridge.Methods.Single(m => m.Name == "TakePreparedClient"));
        changes.Add(constructor.FullName);
        var validator = module.GetType("SteamAPIValidator.SteamApiValidator");
        foreach (string methodName in new[] { "IsValidSteamApiDll", "IsValidSteamClientDll" })
        {
            var method = validator.Methods.Single(m => m.Name == methodName);
            Replace(method, module.ImportReference(bridge.Methods.Single(m => m.Name == "ValidateSteamLibraries")));
            changes.Add(method.FullName);
        }
        foreach (var pair in new[] {
            ("RoR2.EntitlementManagement.EntitlementAbstractions", "VerifyLocalSteamUser"),
            ("RoR2.EntitlementManagement.SteamworksEntitlementResolver", "BuildEntitlements") })
        {
            var method = module.GetType(pair.Item1).Methods.Single(m => m.Name == pair.Item2);
            var sites = method.Body.Instructions.Where(i => i.Operand is MethodReference m &&
                m.DeclaringType.FullName == "Facepunch.Steamworks.App" && m.Name == "IsDlcInstalled").ToArray();
            if (sites.Length != 1) throw new InvalidDataException("Expected one DLC depot query in " + method.FullName);
            sites[0].OpCode = OpCodes.Call;
            sites[0].Operand = module.ImportReference(bridge.Methods.Single(m => m.Name == "IsOwnedContentInstalled"));
            changes.Add(method.FullName + " licensed loaded content check");
        }
    }
    if (name == "RoR2Arm64.OfflinePlatform.dll")
    {
        var method = module.GetType("RoR2Arm64.Offline.OfflinePlatform").Methods.Single(m => m.Name == "IsRequested");
        Replace(method, module.ImportReference(bridge.Methods.Single(m => m.Name == "ShouldUseLocalPlatform")));
        changes.Add(method.FullName);
    }
    if (name == "RoR2Arm64.ManagedSolo.dll")
    {
        var method = module.GetType("RoR2Arm64.ManagedSoloBootstrap").Methods.Single(m => m.Name == "Install");
        var allocations = method.Body.Instructions.Where(i => i.OpCode == OpCodes.Newobj &&
            i.Operand is MethodReference m && m.DeclaringType.FullName == "RoR2Arm64.ManagedSoloTransport").ToArray();
        if (allocations.Length != 1) throw new InvalidDataException("Unexpected transport allocation count");
        allocations[0].OpCode = OpCodes.Call;
        allocations[0].Operand = module.ImportReference(bridge.Methods.Single(m => m.Name == "CreateTransport"));
        var notices = method.Body.Instructions.Where(i => i.OpCode == OpCodes.Ldstr && i.Operand is string text &&
            text.StartsWith("ARM64_SOLO_TRANSPORT_INSTALLED:", StringComparison.Ordinal)).ToArray();
        if (notices.Length != 1) throw new InvalidDataException("Expected one old transport notice");
        notices[0].Operand = "RISK2MAC_TRANSPORT_INSTALLED: platform transport initialized; graphics/input compatibility active";
        changes.Add(method.FullName);
    }
    if (name == "Facepunch.Steamworks.dll")
    {
        var imports = Types(module.Types).SelectMany(t => t.Methods).Where(m => m.HasPInvokeInfo &&
            m.PInvokeInfo.Module.Name.Contains("libsteam_api", StringComparison.OrdinalIgnoreCase) &&
            !m.PInvokeInfo.Module.Name.EndsWith(".so", StringComparison.OrdinalIgnoreCase)).ToArray();
        if (imports.Length == 0) throw new InvalidDataException("macOS Steam imports missing");
        var native = new ModuleReference("__Internal");
        var compatibilityNative = new ModuleReference("Risk2MacSteamBridge");
        module.ModuleReferences.Add(native);
        module.ModuleReferences.Add(compatibilityNative);
        foreach (var method in imports)
        {
            string original = method.PInvokeInfo.EntryPoint;
            bool needsLegacyInterface = original.StartsWith("SteamAPI_ISteam", StringComparison.Ordinal) ||
                original == "SteamInternal_GameServer_Init";
            method.PInvokeInfo.Module = needsLegacyInterface ? compatibilityNative : native;
            if (needsLegacyInterface) method.PInvokeInfo.EntryPoint = "Risk2MacLegacy_" + original;
            if (original == "SteamAPI_Init") method.PInvokeInfo.EntryPoint = "SteamAPI_InitSafe";
            changes.Add(method.FullName + " => " + method.PInvokeInfo.EntryPoint);
        }
    }
    string target = Path.Combine(output, name);
    assembly.Write(target);
    using (var verified = AssemblyDefinition.ReadAssembly(target, reader))
    {
        var actualChanges = Types(verified.MainModule.Types).SelectMany(t => t.Methods)
            .Where(m => originalBodies[m.FullName] != BodyFingerprint(m)).Select(m => m.FullName).ToArray();
        var expectedChanges = name == "Facepunch.Steamworks.dll" ? Array.Empty<string>() :
            changes.Select(s => s.Replace(" licensed loaded content check", "")).ToArray();
        if (!actualChanges.Order().SequenceEqual(expectedChanges.Order()))
            throw new InvalidDataException("Unexpected method body changes in " + name + ": " + string.Join(",", actualChanges));
    }
    if (Hash(input) != beforeHash) throw new IOException("Source changed while patching");
    report.Add(new { file = name, sourceSha256 = beforeHash, candidateSha256 = Hash(target), changes });
}
File.Copy(helperPath, Path.Combine(output, "Risk2Mac.Steam.dll"));
File.WriteAllText(Path.Combine(output, "patch-report.json"), JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true }));
Console.WriteLine("Candidate written and every method body checked against its source. Manifest: " + Path.Combine(output, "patch-report.json"));

static void Replace(MethodDefinition method, MethodReference target)
{
    if (method.Parameters.Count != 0 || method.ReturnType.FullName != "System.Boolean")
        throw new InvalidDataException("Unexpected replacement signature");
    method.Body = new MethodBody(method);
    method.Body.Instructions.Add(Instruction.Create(OpCodes.Call, target));
    method.Body.Instructions.Add(Instruction.Create(OpCodes.Ret));
}
static IEnumerable<TypeDefinition> Types(IEnumerable<TypeDefinition> roots)
{
    foreach (var type in roots)
    {
        yield return type;
        foreach (var nested in Types(type.NestedTypes)) yield return nested;
    }
}
static string Hash(string path) => Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant();
static string BodyFingerprint(MethodDefinition method)
{
    if (!method.HasBody) return "no-body";
    var body = method.Body;
    string Operand(object? value) => value switch {
        Instruction i => "instruction:" + body.Instructions.IndexOf(i),
        Instruction[] targets => "switch:" + string.Join(",", targets.Select(i => body.Instructions.IndexOf(i))),
        VariableDefinition local => "local:" + local.Index,
        ParameterDefinition parameter => "parameter:" + parameter.Index,
        MemberReference member => member.FullName,
        _ => value?.ToString() ?? "null"
    };
    return JsonSerializer.Serialize(new {
        body.InitLocals,
        locals = body.Variables.Select(v => v.VariableType.FullName),
        instructions = body.Instructions.Select(i => i.OpCode.Name + " " + Operand(i.Operand)),
        handlers = body.ExceptionHandlers.Select(h => new {
            h.HandlerType, catchType = h.CatchType?.FullName,
            start = Operand(h.TryStart), end = Operand(h.TryEnd),
            handler = Operand(h.HandlerStart), handlerEnd = Operand(h.HandlerEnd), filter = Operand(h.FilterStart)
        })
    });
}
