import sharp from "sharp";
import { readFileSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");
const svgSource = readFileSync(resolve(root, "branding/sigil.svg"));
const outDir = resolve(root, "public/icons");

const BG = { r: 10, g: 14, b: 26, alpha: 1 };

async function generateIcon(name, size, paddingFraction) {
  const sigilSize = Math.round(size * (1 - paddingFraction * 2));
  const offset = Math.round((size - sigilSize) / 2);

  const sigilPng = await sharp(svgSource, { density: Math.ceil((sigilSize / 240) * 96) })
    .resize(sigilSize, sigilSize, { fit: "contain", background: { r: 0, g: 0, b: 0, alpha: 0 } })
    .png()
    .toBuffer();

  await sharp({
    create: { width: size, height: size, channels: 4, background: BG },
  })
    .composite([{ input: sigilPng, left: offset, top: offset }])
    .png()
    .toFile(`${outDir}/${name}`);

  console.log(`  ${name} (${size}x${size}, padding ${Math.round(paddingFraction * 100)}%)`);
}

console.log("Generating icons...");
await generateIcon("icon-192.png", 192, 0.12);
await generateIcon("icon-512.png", 512, 0.12);
await generateIcon("icon-maskable-512.png", 512, 0.20);
await generateIcon("apple-touch-icon-180.png", 180, 0.12);
await generateIcon("apple-touch-icon-167.png", 167, 0.12);
await generateIcon("apple-touch-icon-152.png", 152, 0.12);
console.log("Done.");
