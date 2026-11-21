using System.Security.Cryptography;
using System.Text.Json;
using AsmResolver.DotNet.Builder;
using AsmResolver.PE.Builder;
using Mono.Cecil;
using Mono.Cecil.Cil;

const string ColliderAssembly = "HGUnityUtils.dll";
const string RenderAssembly = "Unity.RenderPipelines.Core.Runtime.dll";

if (args.Length < 4 || args[3..].Distinct(StringComparer.Ordinal).Count() != args.Length - 3 ||
    args[3..].Any(name => name != ColliderAssembly && name != RenderAssembly))
{
    Console.Error.WriteLine("Usage: Risk2Mac.CompatPatcher WINDOWS_MANAGED UNITY_CORE NEW_OUTPUT_DIRECTORY ASSEMBLY...");
    return 2;
}

try
{
    string windows = Path.GetFullPath(args[0]);
    string output = Path.GetFullPath(args[2]);
    if (File.Exists(output) || Directory.Exists(output))
        throw new IOException("Choose a fresh output directory.");
    var generated = new Dictionary<string, byte[]>(StringComparer.Ordinal);
    foreach (var name in args[3..])
    {
        string input = Path.Combine(windows, name);
        generated.Add(name, name == ColliderAssembly
            ? PrepareColliderAssembly(input)
            : PrepareRenderAssembly(input, Path.GetFullPath(args[1])));
    }

    string parent = Path.GetDirectoryName(output) ?? throw new IOException("Missing output parent directory.");
    if (!Directory.Exists(parent))
        throw new DirectoryNotFoundException("Missing output parent directory.");
    string staging = Path.Combine(parent, $".risk2mac-compat-{Guid.NewGuid():N}");
    Directory.CreateDirectory(staging);
    try
    {
        foreach (var (name, bytes) in generated)
        {
            using var file = new FileStream(Path.Combine(staging, name), FileMode.CreateNew);
            file.Write(bytes);
        }
        Directory.Move(staging, output);
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
    Console.WriteLine(JsonSerializer.Serialize(new { files = generated.Count }));
    return 0;
}
catch (Exception error)
{
    Console.Error.WriteLine($"Risk2Mac managed compatibility: {error.Message}");
    return 1;
}

static byte[] PrepareColliderAssembly(string filename)
{
    var original = File.ReadAllBytes(filename);
    CheckHash(original, "dafbadf2b58c2aad67a2324c1d3593af5a957e9c9f5c307d6651077c980fb02a", filename);

    // Normalise the PE layout before editing the two reviewed sweep helper methods.
    var serialized = AsmResolver.DotNet.ModuleDefinition.FromBytes(original);
    using var intermediate = new MemoryStream();
    serialized.ToPEImage(new ManagedPEImageBuilder(), true).ToPEFile(new ManagedPEFileBuilder()).Write(intermediate);
    CheckHash(intermediate.ToArray(), "5448e8c1654d8181d229f85e54819c4f15ed59b2ce69a2a69be64eba3038ac66",
        "Normalised HGUnityUtils.dll");
    intermediate.Position = 0;
    using var assembly = AssemblyDefinition.ReadAssembly(intermediate, new ReaderParameters { InMemory = true });
    var module = assembly.MainModule;
    var helper = module.GetType("HG.ColliderUtils/SweepColliderHelper");
    var create = helper.Methods.Single(method => method.Name == "Create");
    var copy = helper.Methods.Single(method => method.Name == "CopyCollider");
    var terrain = helper.Fields.Single(field => field.Name == "terrainCollider");
    var add = create.Body.Instructions.Single(instruction =>
        instruction.Operand is GenericInstanceMethod method && method.Name == "AddComponent" &&
        method.GenericArguments.Single().FullName == "UnityEngine.TerrainCollider");
    var load = create.Body.Instructions.Single(instruction => instruction.OpCode.Code == Code.Ldfld &&
        instruction.Operand is FieldReference field && field.FullName == terrain.FullName);
    foreach (var instruction in new[] { add.Previous.Previous, add.Previous, add, add.Next,
                 load.Previous, load, load.Next, load.Next.Next })
    {
        instruction.OpCode = OpCodes.Nop;
        instruction.Operand = null;
    }

    // Unity's rigidbody sweep accepts primitive and convex moving colliders.
    // Preserve the original routines for those shapes and for world terrain targets.
    var exception = new TypeReference("System", "NotSupportedException", module, module.TypeSystem.CoreLibrary);
    var ctor = new MethodReference(".ctor", module.TypeSystem.Void, exception) { HasThis = true };
    ctor.Parameters.Add(new ParameterDefinition(module.TypeSystem.String));
    var entry = copy.Body.Instructions[0];
    var patch = new[] {
        Instruction.Create(OpCodes.Ldarg_1),
        Instruction.Create(OpCodes.Isinst, terrain.FieldType),
        Instruction.Create(OpCodes.Brfalse, entry),
        Instruction.Create(OpCodes.Ldstr, "TerrainCollider cannot be used as the moving shape of Rigidbody.SweepTest. World terrain remains available as a collision target."),
        Instruction.Create(OpCodes.Newobj, ctor),
        Instruction.Create(OpCodes.Throw),
    };
    var il = copy.Body.GetILProcessor();
    foreach (var instruction in patch)
        il.InsertBefore(entry, instruction);
    return WriteVerified(assembly, "2dfb8e5dd16ec5509561eaa4f258c8ba9f866ac768925026970d2d219904e2dd");
}

static byte[] PrepareRenderAssembly(string filename, string unityCore)
{
    var original = File.ReadAllBytes(filename);
    CheckHash(original, "7353b54f3dc5313134cb8fe6f6d7dd7260fb05af01ccdf9ad9145b415e755c6f", filename);
    var coreBytes = File.ReadAllBytes(unityCore);
    CheckHash(coreBytes, "9ef5b07bfd9136a3036a21c3645ed2580e8752bfea227060929183bb1aeabdf1", unityCore);
    using var core = AssemblyDefinition.ReadAssembly(new MemoryStream(coreBytes));
    const string newNamespace = "UnityEngine.Rendering";
    const string obsoleteNamespace = "UnityEngine.Rendering.RendererUtils";
    var names = new[] { "RendererList", "RendererListStatus" };
    if (names.Any(name => core.MainModule.GetType($"{newNamespace}.{name}") is null))
        throw new InvalidDataException("The vendor Unity player does not provide the expected RendererList types.");
    using var resolver = new DefaultAssemblyResolver();
    resolver.AddSearchDirectory(Path.GetDirectoryName(filename)!);
    resolver.AddSearchDirectory(Path.GetDirectoryName(unityCore)!);
    using var assembly = AssemblyDefinition.ReadAssembly(new MemoryStream(original),
        new ReaderParameters { AssemblyResolver = resolver });
    foreach (string name in names)
    {
        var reference = assembly.MainModule.GetTypeReferences().Single(type =>
            type.Namespace == obsoleteNamespace && type.Name == name);
        reference.Namespace = newNamespace;
    }
    return WriteVerified(assembly, "9b4cf70d6aa226f94dbda0203a7fa0e534c7be896183dea43c32541b569bcfdb");
}

static byte[] WriteVerified(AssemblyDefinition assembly, string expected)
{
    using var file = new MemoryStream();
    assembly.Write(file);
    var image = file.ToArray();
    CheckHash(image, expected, assembly.Name.Name + " output");
    return image;
}

static void CheckHash(byte[] bytes, string expected, string subject)
{
    string actual = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
    if (actual != expected)
        throw new InvalidDataException($"{subject} requires SHA-256 {expected}; found {actual}.");
}
