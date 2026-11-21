using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Serialization;
using AsmResolver.DotNet;
using AsmResolver.DotNet.Builder;
using AsmResolver.PE.Builder;

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
        var (name, inputHash, outputHash) = entry;
        if (name.Length <= 4 || !name.EndsWith(".dll", StringComparison.Ordinal) ||
            !name.All(character => char.IsAsciiLetterOrDigit(character) || character is '.' or '_' or '-') ||
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
        foreach (var (name, inputHash, outputHash) in plan.OrderBy(entry => entry.Name, StringComparer.Ordinal))
        {
            byte[] input = File.ReadAllBytes(Path.Combine(source, name));
            CheckHash(input, inputHash, $"Unsupported Windows input {name}");
            var module = ModuleDefinition.FromBytes(input);
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
    [property: JsonPropertyName("outputSha256")] string OutputSha256);
