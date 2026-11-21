using System;
using System.IO;
using System.Runtime.InteropServices;
using AssetRipper.TextureDecoder.Bc;
using AssetRipper.TextureDecoder.Rgb.Formats;

if (args.Length != 5)
    throw new ArgumentException("Usage: CubeDecoder INPUT OUTPUT WIDTH HEIGHT FACE_STRIDE");
int width = int.Parse(args[2]);
int height = int.Parse(args[3]);
int faceStride = int.Parse(args[4]);
byte[] input = File.ReadAllBytes(args[0]);
if (width <= 0 || height <= 0 || faceStride < 1 || input.Length != checked(faceStride * 6))
    throw new InvalidDataException("Unexpected cubemap size.");
var pixels = new ColorRGBA<byte>[checked(width * height)];
using var output = new FileStream(args[1], FileMode.CreateNew);
for (int face = 0; face < 6; ++face)
{
    ReadOnlySpan<byte> encoded = input.AsSpan(face * faceStride, faceStride);
    Bc6h.Decompress<ColorRGBA<byte>, byte>(encoded, width, height, false, pixels);
    output.Write(MemoryMarshal.AsBytes(pixels.AsSpan()));
}
