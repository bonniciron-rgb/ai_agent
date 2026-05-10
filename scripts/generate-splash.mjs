import sharp from "sharp";
import { readFileSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");
const svgSource = readFileSync(resolve(root, "branding/sigil.svg"));
const outDir = resolve(root, "public/splash");

const BG = { r: 10, g: 14, b: 26, alpha: 1 };

function wordmarkSvg(width, sigilSize) {
  const fontSize = Math.round(sigilSize * 0.22);
  const gap = Math.round(sigilSize * 0.12);
  const totalHeight = sigilSize + gap + fontSize;
  const yText = sigilSize + gap + fontSize;
  return Buffer.from(
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${totalHeight}">` +
    `<text x="${width / 2}" y="${yText}" text-anchor="middle"` +
    ` font-family="system-ui,-apple-system,BlinkMacSystemFont,sans-serif"` +
    ` font-size="${fontSize}" font-weight="600" letter-spacing="0.12em"` +
    ` fill="#F2F0EC">ETHERA TRADING</text>` +
    `</svg>`
  );
}

async function generateSplash(filename, canvasW, canvasH) {
  const sigilSize = Math.round(Math.min(canvasW, canvasH) * 0.28);
  const fontSize = Math.round(sigilSize * 0.22);
  const gap = Math.round(sigilSize * 0.12);
  const compositeH = sigilSize + gap + fontSize;
  const sigilX = Math.round((canvasW - sigilSize) / 2);
  const sigilY = Math.round((canvasH - compositeH) / 2);
  const wordmarkY = sigilY + sigilSize;

  const sigilPng = await sharp(svgSource, { density: Math.ceil((sigilSize / 240) * 96) })
    .resize(sigilSize, sigilSize, { fit: "contain", background: { r: 0, g: 0, b: 0, alpha: 0 } })
    .png()
    .toBuffer();

  const wm = wordmarkSvg(canvasW, sigilSize);
  const wmPng = await sharp(wm)
    .png()
    .toBuffer();

  await sharp({
    create: { width: canvasW, height: canvasH, channels: 4, background: BG },
  })
    .composite([
      { input: sigilPng, left: sigilX, top: sigilY },
      { input: wmPng, left: 0, top: wordmarkY },
    ])
    .png()
    .toFile(`${outDir}/${filename}`);

  console.log(`  ${filename} (${canvasW}x${canvasH})`);
}

console.log("Generating splash screens...");
await generateSplash("iphone-x.png", 1125, 2436);
await generateSplash("iphone-15-pro.png", 1179, 2556);
console.log("Done.");
