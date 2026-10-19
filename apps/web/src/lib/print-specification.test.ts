import assert from "node:assert/strict";
import test from "node:test";

import { parsePrintSpecification } from "./print-specification.ts";

const specification = {
  presetCode: "pla-standard",
  presetLabel: "PLA standard",
  materialCode: "pla",
  profileSha256: "a".repeat(64),
  colour: "Black",
  settings: {
    nozzleDiameterMm: "0.4",
    layerHeightMm: "0.2",
    infillPercent: 20,
    supports: true,
    wallLoops: 3,
    filamentType: "PLA",
  },
};

test("selected settings survive parsing and legacy orders have no invented specification", () => {
  assert.deepEqual(parsePrintSpecification(specification), specification);
  assert.equal(parsePrintSpecification(undefined), null);
  assert.equal(parsePrintSpecification(null), null);
});

test("malformed print settings are refused instead of being presented to the buyer", () => {
  assert.throws(() =>
    parsePrintSpecification({
      ...specification,
      settings: { ...specification.settings, infillPercent: 200 },
    }),
  );
  assert.throws(() =>
    parsePrintSpecification({ ...specification, profileSha256: "invalid" }),
  );
});
