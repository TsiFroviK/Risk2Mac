using Mono.Cecil;
using Mono.Cecil.Cil;
using System.Security.Cryptography;
using System.Text.Json;

static string Sha(string path)=>Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant();
static IEnumerable<TypeDefinition> Types(IEnumerable<TypeDefinition> types)
{foreach(var t in types){yield return t;foreach(var child in Types(t.NestedTypes))yield return child;}}
static Dictionary<string,string[]> Bodies(AssemblyDefinition a)=>Types(a.MainModule.Types).SelectMany(t=>t.Methods).ToDictionary(m=>m.FullName,m=>m.HasBody?m.Body.Instructions.Select(i=>i.ToString()).ToArray():Array.Empty<string>());
static MethodDefinition Method(AssemblyDefinition a,string type,string name)=>Types(a.MainModule.Types).Single(t=>t.FullName==type).Methods.Single(m=>m.Name==name&&m.Parameters.Count==0);
static bool Call(Instruction i,string type,string name)=>i.OpCode==OpCodes.Call && i.Operand is MethodReference m && m.DeclaringType.FullName==type && m.Name==name;

if (args.Length != 3) throw new ArgumentException("StoragePatcher <baseline directory> <storage helper> <new output directory>");
string source=Path.GetFullPath(args[0]),helper=Path.GetFullPath(args[1]),output=Path.GetFullPath(args[2]);
if (Directory.Exists(output)) throw new IOException("Use a fresh output directory.");
Directory.CreateDirectory(output);
using var resolver=new DefaultAssemblyResolver();
resolver.AddSearchDirectory(source);resolver.AddSearchDirectory(Path.GetDirectoryName(helper));
using var bridge=AssemblyDefinition.ReadAssembly(helper,new ReaderParameters{AssemblyResolver=resolver});
var storage=bridge.MainModule.Types.Single(t=>t.FullName=="RoR2Arm64.Storage.MacWritableStorage");
var dataRoot=storage.Methods.Single(m=>m.Name=="ApplicationFileSystemRoot");
var modsRoot=storage.Methods.Single(m=>m.Name=="ModLoaderWorkingDirectory");
var conVarRoot=storage.Methods.Single(m=>m.Name=="ConVarCacheRoot");
var expected=new Dictionary<string,string>{
    ["RoR2.dll"]="ea13200d83e7db2342879b39c9e80f2c08808fb86e8b217387554aba574b15b5",
    ["ModLoader.dll"]="c27cf114c79abe7646dbc2062215859de14563678596fec5b52be95e8015ccc5"};
var records=new List<object>();
foreach(var pair in expected)
{
    string input=Path.Combine(source,pair.Key),destination=Path.Combine(output,pair.Key);
    if(Sha(input)!=pair.Value)throw new Exception("Unexpected source assembly: "+input);
    using var assembly=AssemblyDefinition.ReadAssembly(input,new ReaderParameters{ReadSymbols=false,AssemblyResolver=resolver});
    var before=Bodies(assembly);var edits=new List<object>();
    void Replace(MethodDefinition method,Instruction instruction,MethodDefinition replacement)
    {
        string previous=instruction.ToString();
        instruction.Operand=assembly.MainModule.ImportReference(replacement);
        edits.Add(new{method=method.FullName,offset=instruction.Offset,before=previous,after=instruction.ToString()});
    }
    if(pair.Key=="RoR2.dll")
    {
        var initialize=Method(assembly,"RoR2.RoR2Application/<InitializeGameRoutine>d__114","MoveNext");
        var pathCall=initialize.Body.Instructions.Single(i=>Call(i,"UnityEngine.Application","get_dataPath") &&
            i.Next?.Operand is MethodReference next && next.DeclaringType.FullName=="Zio.FileSystems.FileSystem" && next.Name=="ConvertPathFromInternal");
        Replace(initialize,pathCall,dataRoot);
        var runReport=Method(assembly,"RoR2.RunReport","Init");
        Replace(runReport,runReport.Body.Instructions.Single(i=>Call(i,"UnityEngine.Application","get_dataPath")),dataRoot);
        var consoleType=Types(assembly.MainModule.Types).Single(t=>t.FullName=="RoR2.Console");
        var cacheMethods=new[]{consoleType.Methods.Single(m=>m.Name=="CacheConVars"),
            consoleType.Methods.Single(m=>m.Name=="InternalInitConVars"),
            Types(consoleType.NestedTypes).Single(t=>t.Name.StartsWith("<InternalInitConVarsCoroutine>" )).Methods.Single(m=>m.Name=="MoveNext")};
        foreach(var method in cacheMethods)
            Replace(method,method.Body.Instructions.Single(i=>Call(i,"UnityEngine.Application","get_streamingAssetsPath")),conVarRoot);
    }
    else
    {
        var initializer=Method(assembly,"RoR2.Modding.ModLoader",".cctor");
        Replace(initializer,initializer.Body.Instructions.Single(i=>Call(i,"System.Environment","get_CurrentDirectory")),modsRoot);
    }
    assembly.Write(destination);
    using var written=AssemblyDefinition.ReadAssembly(destination,new ReaderParameters{AssemblyResolver=resolver});
    var after=Bodies(written);
    if(before.Count!=after.Count || before.Keys.Except(after.Keys).Any())throw new Exception("Method inventory changed");
    int differences=0,unchanged=0;
    foreach(var method in before)
    {
        var right=after[method.Key];
        if(method.Value.Length!=right.Length)throw new Exception("Instruction count changed: "+method.Key);
        int changed=method.Value.Zip(right).Count(x=>x.First!=x.Second);
        if(changed==0){unchanged++;continue;}
        if(changed!=1 || !method.Value.Zip(right).Any(x=>x.First!=x.Second && x.First.Contains(": call System.String ") && x.Second.Contains(": call System.String RoR2Arm64.Storage.MacWritableStorage::")))
            throw new Exception("Unexpected method change: "+method.Key);
        differences+=changed;
    }
    if(differences!=(pair.Key=="RoR2.dll"?5:1))throw new Exception("Unexpected total operand changes");
    records.Add(new{input,sourceSha256=pair.Value,output=destination,sha256=Sha(destination),methods=before.Count,unchangedMethods=unchanged,changedCallOperands=differences,edits});
}
Console.WriteLine(JsonSerializer.Serialize(new{helper,helperSha256=Sha(helper),assemblies=records},new JsonSerializerOptions{WriteIndented=true}));
