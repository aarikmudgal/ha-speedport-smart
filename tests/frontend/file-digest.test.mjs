import assert from "node:assert/strict";
import {createHash, randomBytes} from "node:crypto";
import test from "node:test";
import {FileSHA256, digestFile} from "../../custom_components/speedport_smart/frontend/file-digest.js";

for (const length of [0, 1, 3, 55, 56, 63, 64, 65, 119, 120, 128, 4096, 1_000_000]) {
  test(`incremental digest matches platform SHA-256 for ${length} bytes`, () => {
    const bytes = randomBytes(length);
    const expected = createHash("sha256").update(bytes).digest("hex");
    for (const stride of [1, 7, 64, 131, Math.max(1, length)]) {
      const hash = new FileSHA256();
      for (let i = 0; i < bytes.length; i += stride) hash.update(bytes.subarray(i, i + stride));
      assert.equal(hash.finish(), expected);
      assert.throws(() => hash.update(bytes), /invalid_digest_input/);
      assert.throws(() => hash.finish(), /digest_already_finished/);
    }
  });
}

test("large file digest works without WebCrypto", async () => {
  const bytes = randomBytes(900_000);
  assert.equal(await digestFile(new Blob([bytes])), createHash("sha256").update(bytes).digest("hex"));
});

test("navigation cancellation stops before reading another chunk", async () => {
  let reads = 0;
  const file = {size: 1_000_000, slice() {reads++; return new Blob([new Uint8Array(256 * 1024)]);}};
  await assert.rejects(digestFile(file, () => reads === 0), /digest_cancelled/);
  assert.equal(reads, 1);
});
