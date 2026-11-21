using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Serialization;
using AsmResolver.DotNet;
using AsmResolver.DotNet.Builder;
using AsmResolver.DotNet.Signatures;
using AsmResolver.PE.Builder;
using AsmResolver.PE.DotNet.Metadata.Tables;

const string UnsafeAssembly = "System.Runtime.CompilerServices.Unsafe.dll";
const string UnsafeInput = "mscorlib.dll";

if (args.Length != 3)
{
    Console.Error.WriteLine("Usage: Risk2Mac.ReemitPatcher WINDOWS_MANAGED PLAN_JSON NEW_OUTPUT_DIRECTORY");
    return 2;
}

try
{
    string source = Path.GetFullPath(args[0]);
    string destination = Path.GetFullPath(args[2]);
    var plan = JsonSerializer.Deserialize<PlannedAssembly[]>(File.ReadAllBytes(args[1]));
    if (plan is not { Length: > 0 })
        throw new InvalidDataException("The assembly build plan is missing or has an unsupported format.");
    if (!Directory.Exists(source))
        throw new DirectoryNotFoundException($"Missing Windows Managed directory: {source}");
    if (Directory.Exists(destination) || File.Exists(destination))
        throw new IOException($"Use a new output directory: {destination}");

    var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
    foreach (var entry in plan)
    {
        var (name, inputHash, outputHash, sourceName) = entry;
        if (name.Length <= 4 || !name.EndsWith(".dll", StringComparison.Ordinal) ||
            !name.All(character => char.IsAsciiLetterOrDigit(character) || character is '.' or '_' or '-') ||
            (name == UnsafeAssembly ? sourceName != UnsafeInput : sourceName is not null) ||
            !IsHash(inputHash) || !IsHash(outputHash) || !names.Add(name))
            throw new InvalidDataException($"Invalid assembly build plan entry: {name}");
    }

    string parent = Path.GetDirectoryName(destination) ?? throw new IOException("Missing output parent directory.");
    if (!Directory.Exists(parent))
        throw new DirectoryNotFoundException($"Missing output parent directory: {parent}");
    string staging = Path.Combine(parent, $".risk2mac-reemit-{Guid.NewGuid():N}");
    Directory.CreateDirectory(staging);
    try
    {
        foreach (var (name, inputHash, outputHash, sourceName) in plan.OrderBy(entry => entry.Name, StringComparer.Ordinal))
        {
            byte[] input = File.ReadAllBytes(Path.Combine(source, sourceName ?? name));
            CheckHash(input, inputHash, $"Unsupported Windows input {sourceName ?? name}");
            var module = name == UnsafeAssembly ? CreateUnsafeFacade(input) : ModuleDefinition.FromBytes(input);
            RepairStockMetadata(module, name);
            var image = module.ToPEImage(new ManagedPEImageBuilder(), true);
            using var memory = new MemoryStream();
            image.ToPEFile(new ManagedPEFileBuilder()).Write(memory);
            var output = memory.ToArray();
            CheckHash(output, outputHash, $"Re-emitted {name} did not match the supported build");
            using var generated = new FileStream(Path.Combine(staging, name), FileMode.CreateNew);
            generated.Write(output);
        }
        Directory.Move(staging, destination);
    }
    finally
    {
        if (Directory.Exists(staging))
        {
            foreach (string file in Directory.EnumerateFiles(staging))
                File.Delete(file);
            Directory.Delete(staging);
        }
    }
    Console.WriteLine(JsonSerializer.Serialize(new { files = plan.Length }));
    return 0;
}
catch (Exception error)
{
    Console.Error.WriteLine($"Risk2Mac managed re-emission: {error.Message}");
    return 1;
}

static ModuleDefinition CreateUnsafeFacade(byte[] mscorlib)
{
    const string fullName = "System.Runtime.CompilerServices.Unsafe";
    var core = ModuleDefinition.FromBytes(mscorlib);
    if (core.Assembly?.Name != "mscorlib" || !core.GetAllTypes().Any(type => type.FullName == fullName))
        throw new InvalidDataException("Windows Mono mscorlib does not provide the expected Unsafe type.");
    var scope = new AssemblyReference(core.Assembly);
    var wrapper = new AssemblyDefinition(fullName, core.Assembly.Version);
    var module = new ModuleDefinition(fullName, scope)
    {
        Mvid = Guid.Parse("8f5abbff-cf29-03ce-2a87-297afbb7b1fc"),
        TimeDateStamp = DateTime.UnixEpoch,
    };
    module.AssemblyReferences.Add(scope);
    wrapper.Modules.Add(module);
    module.ExportedTypes.Add(new ExportedType(scope, "System.Runtime.CompilerServices", "Unsafe"));
    return module;
}

static void RepairStockMetadata(ModuleDefinition module, string name)
{
    const string Embedded = "Microsoft.CodeAnalysis.EmbeddedAttribute";
    const string ReadOnly = "System.Runtime.CompilerServices.IsReadOnlyAttribute";
    const string Unmanaged = "System.Runtime.CompilerServices.IsUnmanagedAttribute";
    const string CanvasElement = "UnityEngine.UI.ICanvasElement";
    const string Clippable = "UnityEngine.UI.IClippable";
    (string[] Attributes, (string Type, string Contract, string Property)[] Properties) recipe = name switch
    {
        "Unity.Burst.dll" => ([Embedded, ReadOnly, Unmanaged], []),
        "Unity.Collections.LowLevel.ILSupport.dll" => ([Embedded, ReadOnly], []),
        "Unity.Collections.dll" => ([Embedded, Unmanaged], []),
        "Unity.TextMeshPro.dll" => ([], [("TMPro.TMP_InputField", CanvasElement, "transform")]),
        "UnityEngine.UI.dll" => ([], [
            ("UnityEngine.UI.Graphic", CanvasElement, "transform"),
            ("UnityEngine.UI.InputField", CanvasElement, "transform"),
            ("UnityEngine.UI.MaskableGraphic", Clippable, "gameObject"),
            ("UnityEngine.UI.Scrollbar", CanvasElement, "transform"),
            ("UnityEngine.UI.ScrollRect", CanvasElement, "transform"),
            ("UnityEngine.UI.Slider", CanvasElement, "transform"),
            ("UnityEngine.UI.Toggle", CanvasElement, "transform"),
        ]),
        _ => ([], []),
    };
    foreach (var typeName in recipe.Attributes)
    {
        var type = module.GetAllTypes().Single(type => type.FullName == typeName);
        var attribute = type.CustomAttributes.Single(item =>
            item.Constructor?.DeclaringType?.FullName == "System.Runtime.CompilerServices.CompilerGeneratedAttribute");
        type.CustomAttributes.Remove(attribute);
    }
    foreach (var (typeName, contract, propertyName) in recipe.Properties)
    {
        var type = module.GetAllTypes().Single(type => type.FullName == typeName);
        var getter = type.Methods.Single(method => method.Name == $"{contract}.get_{propertyName}");
        // Associate the existing getter with its explicit interface property.
        var property = new PropertyDefinition($"{contract}.{propertyName}", PropertyAttributes.None,
            PropertySignature.CreateInstance(getter.Signature!.ReturnType));
        type.Properties.Add(property);
        property.SetSemanticMethods(getter, null);
    }
}

static bool IsHash(string? hash) =>
    hash is { Length: 64 } && hash.All(character => character is >= '0' and <= '9' or >= 'a' and <= 'f');

static void CheckHash(byte[] bytes, string expected, string message)
{
    string actual = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
    if (actual != expected)
        throw new InvalidDataException($"{message}. Expected {expected}, found {actual}.");
}

internal sealed record PlannedAssembly(
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("inputSha256")] string InputSha256,
    [property: JsonPropertyName("outputSha256")] string OutputSha256,
    [property: JsonPropertyName("sourceName")] string? SourceName);
