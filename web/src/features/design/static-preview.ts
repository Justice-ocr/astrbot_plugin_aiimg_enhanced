export interface PreviewFile {
  path: string;
  content: string;
}

// Reconstruct static markup rather than mounting an untrusted document.
export function buildStaticPreview(files: PreviewFile[], assets: Record<string, string> = {}): string {
  const resolveAssets = (content: string) => content.replace(
    /asset:\/\/([a-f0-9]{32})/g,
    (_match, id: string) => assets[id] || "",
  );
  const allowed = new Set(("main section article aside header footer nav div span p h1 h2 h3 h4 h5 h6 " +
    "ul ol li dl dt dd table thead tbody tfoot tr th td caption colgroup col " +
    "strong em b i u s small pre code blockquote br hr figure figcaption img " +
    "button label input textarea select option details summary a").split(" "));
  const attributes = new Set(["class", "id", "title", "alt", "width", "height", "colspan", "rowspan", "style"]);
  const input = new DOMParser().parseFromString(
    resolveAssets(files.find((file) => file.path.toLowerCase() === "index.html")?.content || ""), "text/html",
  );
  const output = document.implementation.createHTMLDocument("");
  function copy(source: Node, target: Node) {
    if (source.nodeType === Node.TEXT_NODE) {
      target.appendChild(output.createTextNode(source.textContent || ""));
      return;
    }
    if (!(source instanceof Element) || !allowed.has(source.localName)) return;
    const element = output.createElement(source.localName);
    for (const attribute of Array.from(source.attributes)) {
      if (attributes.has(attribute.name)) element.setAttribute(attribute.name, attribute.value);
    }
    // Only inline raster images are eligible; links, forms and embedded documents
    // cannot initiate navigation or requests from the static preview.
    if (source.localName === "img") {
      const src = source.getAttribute("src") || "";
      if (/^data:image\/(?:png|jpeg|webp|gif);base64,[a-z0-9+/=\s]+$/i.test(src)) element.setAttribute("src", src);
    }
    for (const child of Array.from(source.childNodes)) copy(child, element);
    target.appendChild(element);
  }
  for (const child of Array.from(input.body.childNodes)) copy(child, output.body);
  const styles = [
    ...Array.from(input.querySelectorAll("style")).map((item) => item.textContent || ""),
    ...files.filter((file) => file.path.toLowerCase().endsWith(".css")).map((file) => resolveAssets(file.content)),
  ].join("\n").replace(/<\/style/gi, "<\\/style");
  const policy = "default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none';";
  return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${policy}"><style>${styles}</style></head><body>${output.body.innerHTML}</body></html>`;
}
