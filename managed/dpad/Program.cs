using Mono.Cecil;
using Mono.Cecil.Cil;
using System.Security.Cryptography;
using System.Text.Json;
if(args.Length != 3) throw new ArgumentException("original bridge output");
string Sha(string path)=>Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant();
const string expected="3b74451386d8bb90d1cba9bf423eff9e2fe9ba1d7b3ed4ce6e3341b2b932b93a";
if(Sha(args[0])!=expected)throw new Exception("Source must be the accepted Mac Rewired baseline");
if(File.Exists(args[2]))throw new IOException("Refusing to overwrite candidate");
var resolver=new DefaultAssemblyResolver();
resolver.AddSearchDirectory(Path.GetDirectoryName(Path.GetFullPath(args[0]))!);
using var original=AssemblyDefinition.ReadAssembly(args[0],new ReaderParameters{AssemblyResolver=resolver,InMemory=true});
using var bridge=AssemblyDefinition.ReadAssembly(args[1],new ReaderParameters{InMemory=true});
var module=original.MainModule;
var hook=module.ImportReference(bridge.MainModule.GetType("RoR2Arm64.Input.MacDpadInput").Methods.Single(x=>x.Name=="TryReadAxis"));
var type=module.GetType("Rewired.UnityInputHelper");
var modified=new List<object>();
foreach(string name in new[]{"GetJoystickAxisValueByJoystickId","GetJoystickAxisRawValueByJoystickId"}) {
 var method=type.Methods.Single(x=>x.Name==name);
 if(!method.IsStatic||method.ReturnType.FullName!="System.Single"||method.Parameters.Count!=2||method.Parameters.Any(x=>x.ParameterType.FullName!="System.Int32")||method.Body.HasExceptionHandlers)throw new Exception("Unexpected boundary signature");
 var originalInstructions=method.Body.Instructions.Select(x=>x.ToString()).ToArray();
 var value=new VariableDefinition(module.TypeSystem.Single);method.Body.Variables.Add(value);method.Body.InitLocals=true;
 var il=method.Body.GetILProcessor();var first=method.Body.Instructions[0];
 foreach(var inst in new[]{il.Create(OpCodes.Ldarg_0),il.Create(OpCodes.Ldarg_1),il.Create(OpCodes.Ldloca,value),il.Create(OpCodes.Call,hook),il.Create(OpCodes.Brfalse,first),il.Create(OpCodes.Ldloc,value),il.Create(OpCodes.Ret)})il.InsertBefore(first,inst);
 modified.Add(new{name,token=method.MetadataToken.ToString(),originalInstructions,prefix="if (MacDpadInput.TryReadAxis(joystickId,axisIndex,out value)) return value;"});
}
original.Write(args[2]);
Console.WriteLine(JsonSerializer.Serialize(new{source=args[0],sourceSha256=expected,bridgeSha256=Sha(args[1]),output=args[2],sha256=Sha(args[2]),modified},new JsonSerializerOptions{WriteIndented=true}));
