import { test, expect } from '@playwright/test';
import { deflateSync } from 'zlib';

/**
 * Confirms LM Studio's vision endpoint (localhost:1234, qwen3-vl-4b-instruct
 * per registry.yaml) accepts a large (2000x2000) image upload end-to-end —
 * the pipeline's own resize step (agents/shared/llm_client.py, max 1024px)
 * masks this normally, so this hits the raw endpoint directly to confirm
 * the server itself has no hard size/payload ceiling below that.
 *
 * Network-dependent on a local, always-on service (unlike the GitHub-hitting
 * tests elsewhere in this suite) — skips rather than fails when offline.
 */

const LM_STUDIO_URL = 'http://localhost:1234/v1/chat/completions';
const MODEL = 'qwen3-vl-4b-instruct';

function crc32(buf: Buffer): number {
  let c: number;
  const table: number[] = [];
  for (let n = 0; n < 256; n++) {
    c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c;
  }
  let crc = 0xffffffff;
  for (let i = 0; i < buf.length; i++) crc = table[(crc ^ buf[i]) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function chunk(type: string, data: Buffer): Buffer {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length, 0);
  const typeAndData = Buffer.concat([Buffer.from(type, 'ascii'), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(typeAndData), 0);
  return Buffer.concat([len, typeAndData, crc]);
}

/** Builds a minimal valid solid-color PNG at the given size (no deps beyond zlib). */
function makeSolidPng(width: number, height: number): Buffer {
  const sig = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

  const ihdrData = Buffer.alloc(13);
  ihdrData.writeUInt32BE(width, 0);
  ihdrData.writeUInt32BE(height, 4);
  ihdrData[8] = 8;  // bit depth
  ihdrData[9] = 2;  // color type: RGB
  const ihdr = chunk('IHDR', ihdrData);

  // one scanline filter byte (0=none) + RGB row, repeated per row
  const rowBytes = 1 + width * 3;
  const raw = Buffer.alloc(rowBytes * height);
  for (let y = 0; y < height; y++) {
    const rowStart = y * rowBytes;
    raw[rowStart] = 0;
    for (let x = 0; x < width; x++) {
      const px = rowStart + 1 + x * 3;
      raw[px] = 120; raw[px + 1] = 90; raw[px + 2] = 200;
    }
  }
  const idat = chunk('IDAT', deflateSync(raw));
  const iend = chunk('IEND', Buffer.alloc(0));

  return Buffer.concat([sig, ihdr, idat, iend]);
}

async function isLmStudioUp(): Promise<boolean> {
  try {
    const res = await fetch(LM_STUDIO_URL.replace('/chat/completions', '/models'), {
      signal: AbortSignal.timeout(3000),
    });
    return res.ok;
  } catch {
    return false;
  }
}

test.describe('LM Studio vision upload (e2e)', () => {
  test('accepts a 2000x2000 image and returns a completion', async () => {
    test.skip(!(await isLmStudioUp()), 'LM Studio not reachable on localhost:1234');

    const png = makeSolidPng(2000, 2000);
    const b64 = png.toString('base64');

    const res = await fetch(LM_STUDIO_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: 'Bearer lm-studio' },
      body: JSON.stringify({
        model: MODEL,
        temperature: 0,
        max_tokens: 64,
        messages: [
          { role: 'system', content: 'Reply with one word describing the dominant color.' },
          {
            role: 'user',
            content: [
              { type: 'image_url', image_url: { url: `data:image/png;base64,${b64}` } },
              { type: 'text', text: 'What color is this image?' },
            ],
          },
        ],
      }),
      signal: AbortSignal.timeout(120_000),
    });

    const text = await res.text();
    expect(res.ok, text).toBe(true);
    const body = JSON.parse(text);
    expect(body.choices?.[0]?.message?.content).toBeTruthy();
  });
});
