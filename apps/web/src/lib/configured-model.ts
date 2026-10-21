import type { ModelOptions } from "./model-options.ts";

export function canOrientModel(file: File): boolean {
  return /\.(stl|obj)$/i.test(file.name) && file.size <= 16 * 1024 * 1024;
}

/** Submit the geometry shown in the preview through the normal private upload pipeline. */
export async function configuredModel(file: File, options: ModelOptions): Promise<File> {
  if (options.sourceUnit === "mm" && options.rotationX === 0 && options.rotationY === 0) return file;
  if (!canOrientModel(file)) throw new Error("Units and orientation require an STL or OBJ up to 16 MiB.");
  if (!["mm", "inch"].includes(options.sourceUnit) ||
    ![options.rotationX, options.rotationY].every(value => Number.isInteger(value) && value >= -180 && value <= 180)) {
    throw new Error("Use whole-degree rotations between −180 and 180.");
  }
  const [{ Matrix4, MathUtils, Mesh, MeshBasicMaterial }, { STLLoader }, { OBJLoader }, { STLExporter }] = await Promise.all([
    import("three"), import("three/addons/loaders/STLLoader.js"),
    import("three/addons/loaders/OBJLoader.js"), import("three/addons/exporters/STLExporter.js"),
  ]);
  const bytes = await file.arrayBuffer();
  const object = /\.stl$/i.test(file.name)
    ? new Mesh(new STLLoader().parse(bytes), new MeshBasicMaterial())
    : new OBJLoader().parse(new TextDecoder().decode(bytes));
  try {
    const scale = options.sourceUnit === "inch" ? 25.4 : 1;
    object.applyMatrix4(new Matrix4().makeRotationY(MathUtils.degToRad(options.rotationY))
      .multiply(new Matrix4().makeRotationX(MathUtils.degToRad(options.rotationX)))
      .multiply(new Matrix4().makeScale(scale, scale, scale)));
    object.updateMatrixWorld(true);
    const result = new STLExporter().parse(object, { binary: true });
    if (result.byteLength <= 84 || result.byteLength > 100 * 1024 * 1024) {
      throw new Error("The configured model is empty or exceeds the upload limit.");
    }
    const copy = new Uint8Array(result.byteLength);
    copy.set(new Uint8Array(result.buffer, result.byteOffset, result.byteLength));
    return new File([copy.buffer], file.name.replace(/\.(stl|obj)$/i, "-configured.stl"), {
      type: "application/octet-stream", lastModified: file.lastModified,
    });
  } finally {
    object.traverse(child => {
      if (child instanceof Mesh) {
        child.geometry.dispose();
        const materials = Array.isArray(child.material) ? child.material : [child.material];
        materials.forEach(material => material.dispose());
      }
    });
  }
}
