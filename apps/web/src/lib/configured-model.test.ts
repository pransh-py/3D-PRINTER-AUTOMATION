import assert from "node:assert/strict";
import test from "node:test";
import { Box3, Mesh, MeshBasicMaterial } from "three";
import { STLLoader } from "three/addons/loaders/STLLoader.js";
import { configuredModel } from "./configured-model.ts";

const original = new File(["solid part\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 2 3\nendloop\nendfacet\nendsolid part\n"], "part.stl");

test("unchanged uploads preserve their original bytes and identity", async () => {
  assert.equal(await configuredModel(original, { sourceUnit: "mm", rotationX: 0, rotationY: 0 }), original);
});

test("configured upload matches preview X-then-Y rotation and inch conversion", async () => {
  const result = await configuredModel(original, { sourceUnit: "inch", rotationX: 90, rotationY: 90 });
  assert.equal(result.name, "part-configured.stl");
  const geometry = new STLLoader().parse(await result.arrayBuffer());
  const mesh = new Mesh(geometry, new MeshBasicMaterial());
  const bounds = new Box3().setFromObject(mesh);
  assert.ok(Math.abs(bounds.max.x - 50.8) < 0.0001);
  assert.ok(Math.abs(bounds.min.y + 76.2) < 0.0001);
  assert.ok(Math.abs(bounds.min.z + 25.4) < 0.0001);
  assert.equal(original.name, "part.stl");
  geometry.dispose(); mesh.material.dispose();
});

test("unsupported transformations fail instead of changing only the preview", async () => {
  await assert.rejects(configuredModel(new File(["3mf"], "part.3mf"), { sourceUnit: "inch", rotationX: 0, rotationY: 0 }), /require an STL or OBJ/);
  await assert.rejects(configuredModel(original, { sourceUnit: "mm", rotationX: 90.5, rotationY: 0 }), /whole-degree/);
});
