using System; using System.IO; using UnityEditor; using UnityEngine; using UnityEngine.Rendering;
public static class BuildSafeDepth { public static void Build(){
 var t=BuildTarget.StandaloneOSX; EditorUserBuildSettings.SwitchActiveBuildTarget(BuildTargetGroup.Standalone,t);
 PlayerSettings.SetUseDefaultGraphicsAPIs(t,false); PlayerSettings.SetGraphicsAPIs(t,new[]{GraphicsDeviceType.Metal});
 string p=Environment.GetEnvironmentVariable("SAFE_DEPTH_OUT"); if(Directory.Exists(p)) throw new Exception("Fresh output required"); Directory.CreateDirectory(p);
 var builds=new[]{new AssetBundleBuild{assetBundleName="safe-depth-copy.bundle",assetNames=new[]{"Assets/SafeDepthCopy.shader"}}};
 if(!BuildPipeline.BuildAssetBundles(p,builds,BuildAssetBundleOptions.None,t))throw new Exception("Failed"); Debug.Log("SAFE_DEPTH_BUILD_OK");
}}
