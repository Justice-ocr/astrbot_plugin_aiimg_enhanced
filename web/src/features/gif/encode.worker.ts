import { GIFEncoder, applyPalette, quantize } from "gifenc";

type Frame = { dataUri: string; durationMs: number };
type EncodeRequest = { frames: Frame[]; width: number; height: number; loop: number };

self.onmessage = async (event: MessageEvent<EncodeRequest>) => {
  try {
    const { frames, width, height, loop } = event.data;
    if (
      !Array.isArray(frames) || !frames.length || frames.length > 60
      || !Number.isInteger(width) || !Number.isInteger(height)
      || width < 16 || height < 16 || width > 1024 || height > 1024
      || !Number.isInteger(loop) || loop < 0 || loop > 999
    ) throw new Error("GIF 导出参数无效");
    if (typeof OffscreenCanvas === "undefined" || typeof createImageBitmap === "undefined") {
      throw new Error("当前浏览器不支持后台 GIF 编码，请使用服务端导出");
    }
    const canvas = new OffscreenCanvas(width, height);
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) throw new Error("无法创建 GIF 绘制上下文");
    const gif = GIFEncoder();
    for (let index = 0; index < frames.length; index++) {
      const frame = frames[index];
      if (!/^data:image\/(?:png|jpeg|webp|gif);base64,/i.test(frame.dataUri)
          || !Number.isInteger(frame.durationMs) || frame.durationMs < 20 || frame.durationMs > 10000) {
        throw new Error(`第 ${index + 1} 帧无效`);
      }
      const image = await createImageBitmap(await (await fetch(frame.dataUri)).blob());
      try {
        context.fillStyle = "#ffffff";
        context.fillRect(0, 0, width, height);
        const scale = Math.min(width / image.width, height / image.height);
        const drawWidth = Math.round(image.width * scale);
        const drawHeight = Math.round(image.height * scale);
        context.drawImage(image, Math.floor((width - drawWidth) / 2), Math.floor((height - drawHeight) / 2), drawWidth, drawHeight);
        const pixels = context.getImageData(0, 0, width, height).data;
        const palette = quantize(pixels, 256);
        gif.writeFrame(applyPalette(pixels, palette), width, height, {
          palette, delay: frame.durationMs, repeat: loop, dispose: 2,
        });
      } finally {
        image.close();
      }
      self.postMessage({ type: "progress", current: index + 1, total: frames.length });
    }
    gif.finish();
    const bytes = gif.bytes().slice();
    self.postMessage({ type: "complete", buffer: bytes.buffer }, { transfer: [bytes.buffer] });
  } catch (error) {
    self.postMessage({ type: "error", message: error instanceof Error ? error.message : "GIF 编码失败" });
  }
};
