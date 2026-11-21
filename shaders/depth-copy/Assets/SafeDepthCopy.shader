Shader "Hidden/RoR2/SafeDepthCopy" {
 SubShader { Cull Off ZWrite Off ZTest Always Pass {
 CGPROGRAM
 #pragma vertex vert_img
 #pragma fragment frag
 #include "UnityCG.cginc"
 sampler2D _CameraDepthTexture;
 float4 frag(v2f_img i):SV_Target {float d=SAMPLE_DEPTH_TEXTURE(_CameraDepthTexture,i.uv);return float4(d,0,0,1);}
 ENDCG
 } }
}
