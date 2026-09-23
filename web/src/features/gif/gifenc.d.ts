declare module "gifenc" {
  export function GIFEncoder(): {
    writeFrame(
      indexed: Uint8Array, width: number, height: number,
      options: { palette: number[][]; delay: number; repeat: number; dispose: number },
    ): void;
    finish(): void;
    bytes(): Uint8Array;
  };
  export function quantize(pixels: Uint8ClampedArray, colors: number): number[][];
  export function applyPalette(pixels: Uint8ClampedArray, palette: number[][]): Uint8Array;
}
