using Mono.Cecil;
using Mono.Cecil.Cil;
using System.Text.Json;
using System.Security.Cryptography;

if(args.Length!=3)throw new ArgumentException("CompatibilityPatcher <original Wwise API.dll> <official 2024 PInvoke metadata.dll> <new output directory>");
string input=Path.GetFullPath(args[0]),metadata=Path.GetFullPath(args[1]),output=Path.GetFullPath(args[2]);
string inputHash=Hash(input);
if(inputHash!="564B74EC232E81AF8FA4B65C17537A4D05890D9181281EAB0BC28BD441A3A781")throw new InvalidDataException("Expected unchanged shipped 2023 Wwise managed API.");
if (Directory.Exists(output)) throw new IOException("Use a new output directory.");
using var assembly=AssemblyDefinition.ReadAssembly(input,new ReaderParameters{InMemory=true});
using var current=AssemblyDefinition.ReadAssembly(metadata);
var module=assembly.MainModule;
var imports=AllMethods(module).Where(m=>m.HasPInvokeInfo&&m.PInvokeInfo.Module.Name=="AkSoundEngine").ToArray();
var official=AllMethods(current.MainModule).Where(m=>m.HasPInvokeInfo&&m.PInvokeInfo.Module.Name=="AkUnitySoundEngine").ToDictionary(m=>m.PInvokeInfo.EntryPoint);
var scope=module.ModuleReferences.Single(m=>m.Name=="AkSoundEngine");scope.Name="AkUnitySoundEngine";
var changes=new List<object>();
var exceptionType=new TypeReference("System","NotSupportedException",module,module.TypeSystem.CoreLibrary);
var exceptionCtor=new MethodReference(".ctor",module.TypeSystem.Void,exceptionType){HasThis=true};exceptionCtor.Parameters.Add(new ParameterDefinition(module.TypeSystem.String));
foreach(var method in imports)
{
    string name=method.PInvokeInfo.EntryPoint;
    if(name.StartsWith("CSharp_LoadBank__SWIG_",StringComparison.Ordinal))
    {
        var matches=official.Values.Where(m=>m.PInvokeInfo.EntryPoint.StartsWith("CSharp_LoadBank__SWIG_",StringComparison.Ordinal)&&ShapeTypes(m)==ShapeTypes(method)).ToArray();
        if(matches.Length!=1)throw new InvalidDataException("Ambiguous bank overload: "+name);
        AdoptMacStringMarshalling(method,matches[0]);
        string next=matches[0].PInvokeInfo.EntryPoint;
        if(next!=name){method.PInvokeInfo.EntryPoint=next;changes.Add(new{Method=name,Change="Map same bank operation/signature to its new SWIG index",Target=next});}
        continue;
    }
    if(name.StartsWith("CSharp_new_AkOutputSettings__SWIG_",StringComparison.Ordinal)&&method.Parameters.Count>0)
    {
        method.Parameters[0].MarshalInfo=new MarshalInfo(NativeType.LPStr);
        changes.Add(new{Method=name,Change="Use official 2024 Mac narrow device-share-set parameter"});continue;
    }
    if(name=="CSharp_RegisterGameObjInternal_WithName")
    {
        method.Parameters[1].MarshalInfo=new MarshalInfo(NativeType.LPStr);
        changes.Add(new{Method=name,Change="Use official 2024 narrow diagnostic object-name parameter"});continue;
    }
    if(name=="CSharp_AkRoomParams_RoomPriority_get"||name=="CSharp_AkRoomParams_RoomPriority_set")
    {
        var native=CloneExtern(method,"Native2024_"+method.Name);
        if(name.EndsWith("_get"))native.ReturnType=module.TypeSystem.Single;else native.Parameters[1].ParameterType=module.TypeSystem.Single;
        StartBody(method);var il=method.Body.GetILProcessor();il.Append(il.Create(OpCodes.Ldarg_0));
        if(name.EndsWith("_set")){il.Append(il.Create(OpCodes.Ldarg_1));il.Append(il.Create(OpCodes.Conv_R_Un));il.Append(il.Create(OpCodes.Conv_R4));}
        il.Append(il.Create(OpCodes.Call,native));if(name.EndsWith("_get"))il.Append(il.Create(OpCodes.Conv_U4));il.Append(il.Create(OpCodes.Ret));
        changes.Add(new{Method=name,Change="Adapt legacy unsigned room priority to real SDK 2024 float priority; no synthetic status"});continue;
    }
    if(name=="CSharp_SetGeometryInstance")
    {
        var native=CloneExtern(method,"Native2024_"+method.Name);native.Parameters[4].ParameterType=module.TypeSystem.Boolean;
        StartBody(method);var il=method.Body.GetILProcessor();var allowed=il.Create(OpCodes.Ldarg_0);
        il.Append(il.Create(OpCodes.Ldarg,method.Parameters[4]));il.Append(il.Create(OpCodes.Ldc_I8,-1L));il.Append(il.Create(OpCodes.Beq,allowed));
        il.Append(il.Create(OpCodes.Ldstr,"Wwise 2024: explicit legacy geometry RoomID needs semantic migration; only AK_INVALID_ROOM_ID is supported."));il.Append(il.Create(OpCodes.Newobj,exceptionCtor));il.Append(il.Create(OpCodes.Throw));
        il.Append(allowed);il.Append(il.Create(OpCodes.Ldarg_1));il.Append(il.Create(OpCodes.Ldarg_2));il.Append(il.Create(OpCodes.Ldarg_3));il.Append(il.Create(OpCodes.Ldarg,method.Parameters[5]));il.Append(il.Create(OpCodes.Ldc_I4_1));il.Append(il.Create(OpCodes.Call,native));il.Append(il.Create(OpCodes.Ret));
        changes.Add(new{Method=name,Change="Require no explicit legacy RoomID, retain reflection flag and use SDK default Solid=true"});continue;
    }
    // SWIG overload indices can differ by platform even in the same Wwise release.
    // Retarget only when the managed parameter and return types identify exactly one candidate.
    int swigMarker=name.LastIndexOf("__SWIG_",StringComparison.Ordinal);
    bool incompatibleArray=(name.StartsWith("CSharp_PrepareEvent__SWIG_",StringComparison.Ordinal)||name.StartsWith("CSharp_PrepareGameSyncs__SWIG_",StringComparison.Ordinal));
    if(swigMarker>0 && !incompatibleArray && (!official.ContainsKey(name)||ShapeTypes(method)!=ShapeTypes(official[name])))
    {
        string prefix=name.Substring(0,swigMarker+7);
        string baseName=name.Substring(0,swigMarker);
        var matches=official.Values.Where(m=>(m.PInvokeInfo.EntryPoint.StartsWith(prefix,StringComparison.Ordinal)||m.PInvokeInfo.EntryPoint==baseName)&&ShapeTypes(m)==ShapeTypes(method)).ToArray();
        if(matches.Length>1 || (matches.Length==0 && official.ContainsKey(name)))throw new InvalidDataException("Ambiguous Mac SWIG overload "+name+" matches="+matches.Length);
        if(matches.Length==1){string next=matches[0].PInvokeInfo.EntryPoint;
          method.PInvokeInfo.EntryPoint=next;changes.Add(new{Method=name,Change="Map unique Mac SWIG overload by managed types",Target=next});name=next;}
    }
    if(!official.ContainsKey(name))
    {
        StartBody(method);var il=method.Body.GetILProcessor();il.Append(il.Create(OpCodes.Ldstr,"Wwise 2024 compatibility boundary is not implemented: "+name));il.Append(il.Create(OpCodes.Newobj,exceptionCtor));il.Append(il.Create(OpCodes.Throw));
        changes.Add(new{Method=name,Change="Explicit unsupported exception; never reports native success"});continue;
    }
    if(ShapeTypes(method)==ShapeTypes(official[name]))
    {
        AdoptMacStringMarshalling(method,official[name]);
    }
    else if(name.StartsWith("CSharp_PrepareEvent__SWIG_",StringComparison.Ordinal)||name.StartsWith("CSharp_PrepareGameSyncs__SWIG_",StringComparison.Ordinal))
    {
        StartBody(method);var il=method.Body.GetILProcessor();il.Append(il.Create(OpCodes.Ldstr,"Mac Wwise string-array conversion not yet implemented: "+name));il.Append(il.Create(OpCodes.Newobj,exceptionCtor));il.Append(il.Create(OpCodes.Throw));
        changes.Add(new{Method=name,Change="Reject incompatible legacy UTF-16 pointer arrays on Mac pending conversion"});
    }
    else throw new InvalidDataException("Unreviewed Mac ABI change: "+name+" old="+Shape(method)+" new="+Shape(official[name]));
}
PatchSettingsGetter();
PatchOsStringDecoder();
PatchWindowsPlatformAdvanced();
Directory.CreateDirectory(output);
string resultPath=Path.Combine(output,"AK.Wwise.Unity.API.dll");assembly.Write(resultPath);
if(Hash(input)!=inputHash)throw new IOException("Input changed.");
using var original=AssemblyDefinition.ReadAssembly(input);
using var verified=AssemblyDefinition.ReadAssembly(resultPath);
var oldBodies=AllMethods(original.MainModule).Where(m=>m.HasBody).ToDictionary(m=>m.FullName);
var written=AllMethods(verified.MainModule).ToDictionary(m=>m.FullName);
int unchanged=0;
foreach(var pair in oldBodies)
{
    if(pair.Key=="AkInitializationSettings AkCommonPlatformSettings::get_AkInitializationSettings()" || pair.Key=="System.String AkSoundEngine::StringFromIntPtrOSString(System.IntPtr)" || pair.Key=="System.Void AkWindowsSettings/PlatformAdvancedSettings::CopyTo(AkPlatformInitSettings)")continue;
    var before=pair.Value;var after=written[pair.Key];
    if(!before.Body.Instructions.Select(i=>Tuple(i,before)).SequenceEqual(after.Body.Instructions.Select(i=>Tuple(i,after))))throw new InvalidDataException("Unexpected original managed CIL change: "+pair.Key);
    unchanged++;
}
var manifest=new{Operation="EXPERIMENTAL Mac-specific legacy managed Wwise 2023 API to official 2024.1.18 native wrapper candidate",Input=input,InputSHA256=inputHash,OfficialMetadata=metadata,OfficialMetadataSHA256=Hash(metadata),Output=resultPath,OutputSHA256=Hash(resultPath),OriginalNativeImports=imports.Length,UnchangedOriginalManagedBodies=unchanged,SettingsGetterChanged=1,OsStringDecoderChanged=1,Changes=changes,Limitations=new[]{"UNVALIDATED: Mac runtime, sound banks, callbacks and OS-string return conversions require real native testing.","PrepareEvent/PrepareGameSyncs legacy pointer-array overloads throw until a safe Mac conversion is implemented.","Unsupported removed functions throw rather than emulate success.","Legacy allocator span setting is removed; SDK 2024 defaults are used. Nonzero legacy memory-allocation limit is explicitly rejected.","Explicit geometry RoomID association is rejected; unassociated geometry uses the SDK 2024 Solid=true default.","Room priority is represented as a native float in 2024; very large integers can lose precision."}};
File.WriteAllText(Path.Combine(output,"compatibility-manifest.json"),JsonSerializer.Serialize(manifest,new JsonSerializerOptions{WriteIndented=true}));
Console.WriteLine(JsonSerializer.Serialize(new{resultPath,manifest.OutputSHA256,Changes=changes.Count,UnchangedManagedBodies=unchanged}));

void AdoptMacStringMarshalling(MethodDefinition method,MethodDefinition native)
{
    for(int i=0;i<method.Parameters.Count;i++)
    {
        var p=method.Parameters[i];var q=native.Parameters[i];
        if(p.ParameterType.FullName!="System.String") continue;
        var before=p.HasMarshalInfo?p.MarshalInfo.NativeType.ToString():"none";
        var after=q.HasMarshalInfo?q.MarshalInfo.NativeType.ToString():"none";
        if(before==after) continue;
        if(q.HasMarshalInfo && q.MarshalInfo.NativeType != NativeType.LPStr) throw new InvalidDataException("Unexpected Mac string encoding: "+method.FullName);
        p.MarshalInfo=q.HasMarshalInfo?new MarshalInfo(NativeType.LPStr):null;
        changes.Add(new{Method=method.PInvokeInfo.EntryPoint,Change="Mac string parameter "+i+" "+before+" -> "+after});
    }
}
static string ShapeTypes(MethodDefinition method)=>method.ReturnType.FullName+"("+string.Join(",",method.Parameters.Select(p=>p.ParameterType.FullName))+")";
MethodDefinition CloneExtern(MethodDefinition source,string name)
{
    var clone=new MethodDefinition(name,MethodAttributes.Private|MethodAttributes.Static|MethodAttributes.HideBySig|MethodAttributes.PInvokeImpl,source.ReturnType){ImplAttributes=source.ImplAttributes,PInvokeInfo=new PInvokeInfo(source.PInvokeInfo.Attributes,source.PInvokeInfo.EntryPoint,scope)};
    foreach(var p in source.Parameters){var copy=new ParameterDefinition(p.Name,p.Attributes,p.ParameterType);if(p.HasMarshalInfo)copy.MarshalInfo=p.MarshalInfo;clone.Parameters.Add(copy);}
    source.DeclaringType.Methods.Add(clone);return clone;
}
void PatchOsStringDecoder()
{
    var type=module.GetType("AkSoundEngine");
    var method=type.Methods.Single(m=>m.Name=="StringFromIntPtrOSString");
    var target=type.Methods.Single(m=>m.Name=="StringFromIntPtrString");
    var call=method.Body.Instructions.Single(i=>i.Operand is MethodReference x&&x.Name=="StringFromIntPtrWString");
    call.Operand=target;
    changes.Add(new{Method=method.FullName,Change="Decode Mac AkOSChar pointers using PtrToStringAnsi, matching official Mac integration"});
}
void PatchWindowsPlatformAdvanced()
{
    var type=module.GetType("AkWindowsSettings/PlatformAdvancedSettings") ?? throw new InvalidDataException("Expected Windows settings type is missing");
    var method=type.Methods.Single(m=>m.Name=="CopyTo" && m.Parameters.Count==1 && m.Parameters[0].ParameterType.Name=="AkPlatformInitSettings");
    var instructions=method.Body.Instructions;
    if(instructions.Count!=5 || instructions[2].Operand is not FieldReference field || field.Name!="MaxSystemAudioObjects" || instructions[3].Operand is not MethodReference call || call.Name!="set_uMaxSystemAudioObjects" || instructions[4].OpCode!=OpCodes.Ret)
        throw new InvalidDataException("Unexpected Windows platform settings method; refusing to suppress unrelated settings.");
    method.Body.Instructions.Clear();method.Body.GetILProcessor().Append(Instruction.Create(OpCodes.Ret));
    changes.Add(new{Method=method.FullName,Change="Mac-only: omit Windows-only MaxSystemAudioObjects setting; preserve general user/device/platform settings"});
}
void StartBody(MethodDefinition method){method.PInvokeInfo=null;method.IsPInvokeImpl=false;method.ImplAttributes=MethodImplAttributes.IL|MethodImplAttributes.Managed;method.Body=new MethodBody(method){MaxStackSize=8};}
void PatchSettingsGetter()
{
    var type=module.GetType("AkCommonPlatformSettings");var method=type.Methods.Single(m=>m.Name=="get_AkInitializationSettings");var instructions=method.Body.Instructions;var il=method.Body.GetILProcessor();
    if(method.Body.ExceptionHandlers.Count!=0||instructions.Any(i=>i.Operand is Instruction||i.Operand is Instruction[]))throw new InvalidDataException("Unexpected settings getter control flow.");
    var userCall=instructions.Single(i=>i.Operand is MethodReference m&&m.DeclaringType.Name=="AkCommonUserSettings"&&m.Name=="CopyTo"&&m.Parameters[0].ParameterType.Name=="AkUnityPlatformSpecificSettings");
    int at=instructions.IndexOf(userCall);if(instructions[at-2].OpCode!=OpCodes.Ldloc_0)throw new InvalidDataException("Unexpected user platform-copy stack.");
    var begin=instructions[at-2];var getter=instructions[at-1];il.Replace(begin,il.Create(OpCodes.Pop));il.Remove(getter);il.Remove(userCall);
    var advancedCall=instructions.Single(i=>i.Operand is MethodReference m&&m.DeclaringType.Name=="AkCommonAdvancedSettings"&&m.Name=="CopyTo"&&m.Parameters[0].ParameterType.Name=="AkUnityPlatformSpecificSettings");
    RemoveStatement(advancedCall,4);
    foreach(string name in new[]{"set_uMemAllocationSizeLimit","set_uMemSpanCount"})RemoveStatement(instructions.Single(i=>i.Operand is MethodReference m&&m.DeclaringType.Name=="AkInitializationSettings"&&m.Name==name),4);
    var originalEntry=instructions[0];var getAdvanced=type.Methods.Single(m=>m.Name=="GetAdvancedSettings");var allocationField=module.GetType("AkCommonAdvancedSettings").Fields.Single(f=>f.Name=="m_MemoryAllocationSizeLimit");
    var prefix=new[]{il.Create(OpCodes.Ldarg_0),il.Create(OpCodes.Callvirt,getAdvanced),il.Create(OpCodes.Ldfld,allocationField),il.Create(OpCodes.Brfalse,originalEntry),il.Create(OpCodes.Ldstr,"Wwise 2024 allocator migration: nonzero legacy memory limit is unsupported; refusing to silently ignore it."),il.Create(OpCodes.Newobj,exceptionCtor),il.Create(OpCodes.Throw)};
    foreach(var item in prefix)il.InsertBefore(originalEntry,item);
    changes.Add(new{Method=method.FullName,Change="Remove empty Windows platform-specific CopyTo calls and removed allocator fields; retain all supported device/sound/platform/music settings, reject nonzero legacy memory limit, use native 2024 allocator defaults"});
    void RemoveStatement(Instruction call,int count){int index=instructions.IndexOf(call);for(int i=0;i<count;i++)il.Remove(instructions[index-count+1]);}
}
static IEnumerable<MethodDefinition> AllMethods(ModuleDefinition module)=>module.Types.SelectMany(Types).SelectMany(t=>t.Methods);
static IEnumerable<TypeDefinition> Types(TypeDefinition type){yield return type;foreach(var child in type.NestedTypes.SelectMany(Types))yield return child;}
static string Shape(MethodDefinition method)=>method.ReturnType.FullName+"("+string.Join(",",method.Parameters.Select(p=>p.ParameterType.FullName+":"+(p.HasMarshalInfo?p.MarshalInfo.NativeType.ToString():"none")))+")";
static string Tuple(Instruction instruction,MethodDefinition method)=>instruction.OpCode.Code+"|"+(instruction.Operand switch{Instruction target=>"branch:"+method.Body.Instructions.IndexOf(target),Instruction[] targets=>"switch:"+string.Join(",",targets.Select(t=>method.Body.Instructions.IndexOf(t))),IMetadataTokenProvider token=>token.ToString(),_=>instruction.Operand?.ToString()??""});
static string Hash(string path){using var stream=File.OpenRead(path);return Convert.ToHexString(SHA256.HashData(stream));}
