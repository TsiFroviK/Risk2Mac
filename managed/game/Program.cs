using Mono.Cecil;
using Mono.Cecil.Cil;
using System.Security.Cryptography;
using System.Text.Json;

const string StockHash = "48F2758CCCBE1A5EFBA88CFFE0A68631953F489A71A92726572C15A4C57FF90C";
if (args.Length != 4) throw new ArgumentException("GamePatcher <stock RoR2.dll> <ManagedSolo.dll> <OfflinePlatform.dll> <new output directory>");
string stock = Path.GetFullPath(args[0]);
string helperPath = Path.GetFullPath(args[1]);
string offlinePath = Path.GetFullPath(args[2]);
string scratch = Path.GetFullPath(args[3]);
if (Directory.Exists(scratch) || File.Exists(scratch)) throw new IOException("Choose a fresh scratch directory.");
if (Hash(stock) != StockHash) throw new InvalidDataException("The stock game input doesn't match the reviewed version.");

using var resolver = new DefaultAssemblyResolver();
resolver.AddSearchDirectory(Path.GetDirectoryName(stock)!);
resolver.AddSearchDirectory(Path.GetDirectoryName(helperPath)!);
resolver.AddSearchDirectory(Path.GetDirectoryName(offlinePath)!);
using var game = ModuleDefinition.ReadModule(stock, new ReaderParameters { InMemory = true, AssemblyResolver = resolver });
using var unity = ModuleDefinition.ReadModule(Path.Combine(Path.GetDirectoryName(stock)!, "UnityEngine.CoreModule.dll"));
using var helper = ModuleDefinition.ReadModule(helperPath);
using var offline = ModuleDefinition.ReadModule(offlinePath);
if (offline.Assembly.Name.Name != "RoR2Arm64.OfflinePlatform" || helper.Assembly.Name.Name != "RoR2Arm64.ManagedSolo")
    throw new InvalidDataException("Unexpected compatibility assembly identity.");
if (game.Assembly.Name.HasPublicKey) throw new InvalidDataException("Unexpected strong-name identity.");
var originalMethods = game.GetTypes().SelectMany(t => t.Methods).ToDictionary(m => m.FullName, Fingerprint);
var platform = game.GetMemberReferences().OfType<MethodReference>().Single(m =>
    m.DeclaringType.FullName == "UnityEngine.Application" && m.Name == "get_platform" &&
    m.ReturnType.FullName == "UnityEngine.RuntimePlatform" && m.Parameters.Count == 0 && !m.HasThis);
int mac = (int)unity.GetType("UnityEngine.RuntimePlatform").Fields.Single(f => f.Name == "OSXPlayer").Constant;
if (mac != 1) throw new InvalidDataException("Unexpected Unity RuntimePlatform enum.");
var expected = new HashSet<string>();

foreach (var (type, name) in new[] {
    ("FlashWindow", "Init"), ("FlashWindow", ".cctor"),
    ("RoR2.WindowsConVars/TimerResolutionConVar", "SetString"),
    ("RoR2.WindowsConVars/TimerResolutionConVar", "GetString")
}) {
    var method = game.GetType(type).Methods.Single(m => m.Name == name);
    var il = method.Body.GetILProcessor();
    var start = method.Body.Instructions[0];
    il.InsertBefore(start, il.Create(OpCodes.Call, platform));
    il.InsertBefore(start, il.Create(OpCodes.Ldc_I4, mac));
    il.InsertBefore(start, il.Create(OpCodes.Bne_Un, start));
    if (method.ReturnType.FullName == "System.String") {
        il.InsertBefore(start, il.Create(OpCodes.Ldstr, "0"));
    } else if (method.ReturnType.FullName != "System.Void") {
        throw new InvalidDataException("Unexpected guard return type.");
    }
    il.InsertBefore(start, il.Create(OpCodes.Ret));
    expected.Add(method.FullName);
}

foreach (var (wrapper, old) in new[] { ("FromCurrent", "get_customReflection"), ("Apply", "set_customReflection") }) {
    var method = game.GetType("RenderSettingsState").Methods.Single(m => m.Name == wrapper);
    var call = method.Body.Instructions.Single(i => i.OpCode == OpCodes.Call && i.Operand is MethodReference m &&
        m.DeclaringType.FullName == "UnityEngine.RenderSettings" && m.Name == old);
    var reference = (MethodReference)call.Operand;
    var replacement = new MethodReference(old + "Texture", reference.ReturnType, reference.DeclaringType) {
        HasThis = reference.HasThis, ExplicitThis = reference.ExplicitThis, CallingConvention = reference.CallingConvention
    };
    foreach (var parameter in reference.Parameters) replacement.Parameters.Add(new ParameterDefinition(parameter.ParameterType));
    call.Operand = replacement;
    expected.Add(method.FullName);
}

var sobel = game.GetType("RoR2.PostProcess.SobelCommandBuffer").Methods.Single(m => m.Name == "Rebuild");
var depth = sobel.Body.Instructions.Single(i => i.Previous?.OpCode == OpCodes.Ldc_I4_5 &&
    i.Operand is MethodReference m && m.Name == ".ctor" &&
    m.DeclaringType.FullName == "UnityEngine.Rendering.RenderTargetIdentifier" &&
    m.Parameters.Count == 1 && m.Parameters[0].ParameterType.FullName == "UnityEngine.Rendering.BuiltinRenderTextureType");
depth.Previous.OpCode = OpCodes.Ldc_I4_0;
expected.Add(sobel.FullName);

var rewired = game.GetType("RoR2.RewiredIntegrationManager").Methods.Single(m => m.Name == "FinishInit" && m.Parameters.Count == 1);
var prepare = helper.GetType("RoR2Arm64.ManagedSoloBootstrap").Methods.Single(m =>
    m.Name == "PrepareRewiredPrefab" && m.IsStatic && m.Parameters.Count == 1 &&
    m.Parameters[0].ParameterType.FullName == "UnityEngine.GameObject" && m.ReturnType.FullName == "System.Void");
var rewiredIl = rewired.Body.GetILProcessor();
var originalEntry = rewired.Body.Instructions[0];
rewiredIl.InsertBefore(originalEntry, rewiredIl.Create(OpCodes.Ldarg_0));
rewiredIl.InsertBefore(originalEntry, rewiredIl.Create(OpCodes.Call, game.ImportReference(prepare)));
expected.Add(rewired.FullName);

var context = offline.GetType("RoR2Arm64.Offline.OfflinePlatform");
AddLocalDispatch("RoR2.PlatformSystems", "Init", "TryInitialize");
AddLocalDispatch("RoR2.PlatformSystems", "InitNetworkManagerSystem", "TryInitializeNetworkManager", OpCodes.Ldarg_0);
AddLocalDispatch("RoR2.UserProfile", "LoadPortrait", "TryLoadLocalPortrait", OpCodes.Ldarg_0, OpCodes.Ldarg_1);

var playerName = game.GetType("RoR2.NetworkPlayerName");
var resolveName = playerName.Methods.Single(m => m.Name == "GetResolvedName" && m.Parameters.Count == 0);
var nameIl = resolveName.Body.GetILProcessor();
var nameEntry = resolveName.Body.Instructions[0];
nameIl.InsertBefore(nameEntry, nameIl.Create(OpCodes.Call, LocalMethod("IsRequested")));
nameIl.InsertBefore(nameEntry, nameIl.Create(OpCodes.Brfalse, nameEntry));
nameIl.InsertBefore(nameEntry, nameIl.Create(OpCodes.Ldarg_0));
nameIl.InsertBefore(nameEntry, nameIl.Create(OpCodes.Ldfld, playerName.Fields.Single(f => f.Name == "playerId")));
nameIl.InsertBefore(nameEntry, nameIl.Create(OpCodes.Call, LocalMethod("ResolveLocalPlayerName")));
nameIl.InsertBefore(nameEntry, nameIl.Create(OpCodes.Ret));
expected.Add(resolveName.FullName);

Directory.CreateDirectory(scratch);
string result = Path.Combine(scratch, "RoR2.dll");
using (var output = new FileStream(result, FileMode.CreateNew)) game.Write(output);
using var audited = ModuleDefinition.ReadModule(result);
var currentMethods = audited.GetTypes().SelectMany(t => t.Methods).ToDictionary(m => m.FullName, Fingerprint);
if (expected.Count != 12 || !currentMethods.Keys.ToHashSet().SetEquals(originalMethods.Keys) ||
    !currentMethods.Where(m => m.Value != originalMethods[m.Key]).Select(m => m.Key).ToHashSet().SetEquals(expected) ||
    audited.AssemblyReferences.Count(r => r.Name == "RoR2Arm64.OfflinePlatform") != 1 ||
    audited.Mvid != game.Mvid || Hash(stock) != StockHash)
    throw new InvalidDataException("The candidate's changed methods or dependencies don't match the expected scope.");
Console.WriteLine(JsonSerializer.Serialize(new {
    changes = expected.Order(), methodsAudited = currentMethods.Count, stockSha256 = StockHash.ToLowerInvariant(),
    candidateSha256 = Hash(result).ToLowerInvariant(), output = result
}));

MethodReference LocalMethod(string name) => game.ImportReference(context.Methods.Single(m => m.Name == name && m.IsStatic));

void AddLocalDispatch(string type, string name, string localName, params OpCode[] arguments) {
    var target = game.GetType(type).Methods.Single(m => m.Name == name);
    var local = LocalMethod(localName);
    if (target.ReturnType.FullName != "System.Void" || local.ReturnType.FullName != "System.Boolean" ||
        local.Parameters.Count != arguments.Length || target.Parameters.Count + (target.HasThis ? 1 : 0) != arguments.Length)
        throw new InvalidDataException("Unexpected local platform dispatch signature: " + target.FullName);
    var start = target.Body.Instructions[0];
    var il = target.Body.GetILProcessor();
    foreach (var argument in arguments) il.InsertBefore(start, il.Create(argument));
    il.InsertBefore(start, il.Create(OpCodes.Call, local));
    il.InsertBefore(start, il.Create(OpCodes.Brfalse, start));
    il.InsertBefore(start, il.Create(OpCodes.Ret));
    expected.Add(target.FullName);
}

static string Hash(string path) {
    using var stream = File.OpenRead(path);
    return Convert.ToHexString(SHA256.HashData(stream));
}

static string Fingerprint(MethodDefinition method) {
    if (!method.HasBody) return "no-body";
    var body = method.Body;
    string Value(object? operand) => operand switch {
        Instruction label => "label:" + body.Instructions.IndexOf(label),
        Instruction[] labels => "switch:" + string.Join(",", labels.Select(label => body.Instructions.IndexOf(label))),
        VariableDefinition local => "local:" + local.Index,
        ParameterDefinition arg => "arg:" + arg.Index,
        MemberReference reference => reference.FullName,
        _ => operand?.ToString() ?? "null"
    };
    return JsonSerializer.Serialize(new {
        body.InitLocals,
        locals = body.Variables.Select(v => v.VariableType.FullName),
        instructions = body.Instructions.Select(i => i.OpCode.Name + " " + Value(i.Operand)),
        exceptions = body.ExceptionHandlers.Select(e => new {
            e.HandlerType, type = e.CatchType?.FullName, tryStart = Value(e.TryStart), tryEnd = Value(e.TryEnd),
            handlerStart = Value(e.HandlerStart), handlerEnd = Value(e.HandlerEnd), filter = Value(e.FilterStart)
        })
    });
}
