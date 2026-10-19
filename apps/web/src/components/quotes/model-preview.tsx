"use client";

import { useEffect, useRef, useState } from "react";
import {
  AmbientLight,
  Box3,
  DirectionalLight,
  DoubleSide,
  Mesh,
  Matrix4,
  GridHelper,
  MathUtils,
  MeshStandardMaterial,
  PerspectiveCamera,
  Scene,
  Vector3,
  WebGLRenderer,
  type Object3D,
} from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { OBJLoader } from "three/addons/loaders/OBJLoader.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";

import styles from "./quote-request.module.css";
import {
  DEFAULT_MODEL_OPTIONS,
  type ModelOptions,
  type ModelStats,
} from "@/lib/model-options";

const MAX_PREVIEW_BYTES = 16 * 1024 * 1024;

export default function ModelPreview({
  file,
  options = DEFAULT_MODEL_OPTIONS,
  colour = "#d65a33",
  onStats,
}: {
  file: File;
  options?: ModelOptions;
  colour?: string;
  onStats?: (stats: ModelStats | null) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const materialRef = useRef<MeshStandardMaterial | null>(null);
  const renderRef = useRef<(() => void) | null>(null);
  const [message, setMessage] = useState("Preparing your model preview…");

  useEffect(() => {
    materialRef.current?.color.set(colour);
    renderRef.current?.();
  }, [colour]);

  useEffect(() => {
    const container = host.current;
    if (!container) return;
    let active = true;
    let cleanup = () => {};
    onStats?.(null);

    async function load() {
      const extension = file.name.split(".").pop()?.toLowerCase();
      if (
        !["stl", "obj"].includes(extension ?? "") ||
        file.size > MAX_PREVIEW_BYTES
      ) {
        setMessage(
          "Interactive preview supports STL and OBJ up to 16 MiB. Your file can still be uploaded for analysis.",
        );
        return;
      }
      let object: Object3D | null = null;
      let renderer: WebGLRenderer | null = null;
      let controls: OrbitControls | null = null;
      let observer: ResizeObserver | null = null;
      const material = new MeshStandardMaterial({
        color: colour,
        roughness: 0.65,
        side: DoubleSide,
      });
      materialRef.current = material;
      const dispose = () => {
        observer?.disconnect();
        controls?.dispose();
        object?.traverse((child) => {
          if (child instanceof Mesh) child.geometry.dispose();
        });
        material.dispose();
        renderer?.dispose();
        renderer?.domElement.remove();
        materialRef.current = null;
        renderRef.current = null;
      };
      cleanup = dispose;
      try {
        const bytes = await file.arrayBuffer();
        if (!active) {
          dispose();
          return;
        }
        object =
          extension === "stl"
            ? new Mesh(new STLLoader().parse(bytes), material)
            : new OBJLoader().parse(new TextDecoder().decode(bytes));
        let vertices = 0;
        let signedVolume = 0;
        const scale = options.sourceUnit === "inch" ? 25.4 : 1;
        const transform = new Matrix4()
          .makeRotationY(MathUtils.degToRad(options.rotationY))
          .multiply(
            new Matrix4().makeRotationX(MathUtils.degToRad(options.rotationX)),
          )
          .multiply(new Matrix4().makeScale(scale, scale, scale));
        object.traverse((child) => {
          if (!(child instanceof Mesh)) return;
          vertices += child.geometry.getAttribute("position")?.count ?? 0;
          child.geometry.applyMatrix4(transform);
          const position = child.geometry.getAttribute("position");
          const indices = child.geometry.getIndex();
          const count = indices?.count ?? position.count;
          const a = new Vector3(),
            b = new Vector3(),
            c = new Vector3();
          for (let i = 0; i + 2 < count; i += 3) {
            a.fromBufferAttribute(position, indices ? indices.getX(i) : i);
            b.fromBufferAttribute(
              position,
              indices ? indices.getX(i + 1) : i + 1,
            );
            c.fromBufferAttribute(
              position,
              indices ? indices.getX(i + 2) : i + 2,
            );
            signedVolume += a.dot(b.cross(c)) / 6;
          }
          // STL facet normals can be missing or zero; derive lighting from geometry.
          child.geometry.computeVertexNormals();
          const old = Array.isArray(child.material)
            ? child.material
            : [child.material];
          old.forEach((value) => {
            if (value !== material) value.dispose();
          });
          child.material = material;
        });
        const box = new Box3().setFromObject(object);
        const size = box.getSize(new Vector3());
        const longest = Math.max(size.x, size.y, size.z);
        if (
          vertices === 0 ||
          vertices > 1_500_000 ||
          !size.toArray().every(Number.isFinite) ||
          longest <= 0
        )
          throw new Error("Invalid or too complex for browser preview");
        object.position.sub(box.getCenter(new Vector3()));
        onStats?.({
          dimensionsMm: [size.x, size.y, size.z],
          volumeCm3: Math.abs(signedVolume) / 1000,
        });
        const scene = new Scene();
        scene.add(object, new AmbientLight(0xffffff, 1.6));
        const grid = new GridHelper(
          Math.max(longest * 2, 20),
          20,
          0x788b93,
          0xaebbc0,
        );
        grid.rotation.x = Math.PI / 2;
        grid.position.z = -size.z / 2 - longest / 1000;
        scene.add(grid);
        const previousCleanup = cleanup;
        cleanup = () => {
          grid.geometry.dispose();
          grid.material.dispose();
          previousCleanup();
        };
        const light = new DirectionalLight(0xffffff, 3);
        light.position.set(longest, longest * 2, longest * 3);
        scene.add(light);
        const camera = new PerspectiveCamera(
          35,
          1,
          longest / 1000,
          longest * 30,
        );
        camera.up.set(0, 0, 1);
        camera.position.set(longest * 1.6, -longest * 1.8, longest * 1.2);
        renderer = new WebGLRenderer({ antialias: true, alpha: true });
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        renderer.domElement.setAttribute(
          "aria-label",
          "Interactive 3D model view",
        );
        renderer.domElement.setAttribute("role", "img");
        renderer.domElement.tabIndex = 0;
        container!.appendChild(renderer.domElement);
        controls = new OrbitControls(camera, renderer.domElement);
        controls.enablePan = false;
        controls.minDistance = longest * 0.5;
        controls.maxDistance = longest * 10;
        controls.update();
        const render = () => renderer?.render(scene, camera);
        renderRef.current = render;
        controls.addEventListener("change", render);
        controls.listenToKeyEvents(renderer.domElement);
        observer = new ResizeObserver(() => {
          if (!renderer || !container) return;
          const width = container.clientWidth;
          const height = container.clientHeight || 360;
          renderer.setSize(width, height);
          camera.aspect = width / height;
          camera.updateProjectionMatrix();
          render();
        });
        observer.observe(container!);
        setMessage(
          `${size.x.toFixed(2)} × ${size.y.toFixed(2)} × ${size.z.toFixed(2)} mm. Drag to orbit; scroll to zoom. Units and applied X/Y rotation are included in this view. Orbiting does not alter the print.`,
        );
      } catch {
        cleanup();
        if (active)
          setMessage(
            "A browser preview is unavailable for this model. You can still submit it for server-side validation.",
          );
      }
    }
    void load();
    return () => {
      active = false;
      cleanup();
    };
  }, [
    file,
    options.sourceUnit,
    options.rotationX,
    options.rotationY,
    onStats,
    colour,
  ]);

  return (
    <figure className={styles.modelPreview}>
      <div ref={host} className={styles.previewCanvas} />
      <figcaption aria-live="polite">
        {file.name}: {message}
      </figcaption>
    </figure>
  );
}
