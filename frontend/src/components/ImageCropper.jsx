import React, { useEffect, useRef, useState } from "react";

/**
 * Minimal, dependency-free cropper: drag to move, slider to zoom, fixed
 * aspect ratio. Returns the crop box in source-image pixels so the server
 * crops the original (EXIF-corrected) upload at full quality.
 */
export default function ImageCropper({ file, aspect = 1, onCancel, onConfirm, title = "Crop image" }) {
  const [img, setImg] = useState(null);
  const [zoom, setZoom] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const drag = useRef(null);
  const frameW = 280;
  const frameH = Math.round(frameW / aspect);

  useEffect(() => {
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => setImg({ url, w: image.naturalWidth, h: image.naturalHeight });
    image.src = url;
    return () => URL.revokeObjectURL(url);
  }, [file]);

  if (!img) return null;
  const base = Math.max(frameW / img.w, frameH / img.h);
  const scale = base * zoom;
  const dispW = img.w * scale;
  const dispH = img.h * scale;
  const clamp = (o) => ({
    x: Math.min(0, Math.max(frameW - dispW, o.x)),
    y: Math.min(0, Math.max(frameH - dispH, o.y)),
  });
  const pos = clamp(offset.x === 0 && offset.y === 0 && !drag.current ? { x: (frameW - dispW) / 2, y: (frameH - dispH) / 2 } : offset);

  function start(e) {
    const p = e.touches ? e.touches[0] : e;
    drag.current = { sx: p.clientX, sy: p.clientY, ox: pos.x, oy: pos.y };
  }
  function moveTo(e) {
    if (!drag.current) return;
    const p = e.touches ? e.touches[0] : e;
    setOffset(clamp({ x: drag.current.ox + p.clientX - drag.current.sx, y: drag.current.oy + p.clientY - drag.current.sy }));
  }
  function nudge(dx, dy) {
    setOffset(clamp({ x: pos.x + dx, y: pos.y + dy }));
  }

  function confirm() {
    onConfirm({
      x: Math.round(-pos.x / scale),
      y: Math.round(-pos.y / scale),
      w: Math.round(frameW / scale),
      h: Math.round(frameH / scale),
    });
  }

  return (
    <div className="qr-modal" role="dialog" aria-modal="true" aria-label={title}>
      <div className="qr-modal-card">
        <h3>{title}</h3>
        <div
          className="qr-crop-frame"
          style={{ width: frameW, height: frameH }}
          onMouseDown={start}
          onMouseMove={moveTo}
          onMouseUp={() => (drag.current = null)}
          onMouseLeave={() => (drag.current = null)}
          onTouchStart={start}
          onTouchMove={moveTo}
          onTouchEnd={() => (drag.current = null)}
          tabIndex={0}
          onKeyDown={(e) => {
            const step = 10;
            if (e.key === "ArrowLeft") nudge(step, 0);
            if (e.key === "ArrowRight") nudge(-step, 0);
            if (e.key === "ArrowUp") nudge(0, step);
            if (e.key === "ArrowDown") nudge(0, -step);
          }}
          aria-label="Drag or use arrow keys to position"
        >
          <img src={img.url} alt="" draggable={false}
            style={{ width: dispW, height: dispH, transform: `translate(${pos.x}px, ${pos.y}px)` }} />
        </div>
        <label htmlFor="crop-zoom" className="small">Zoom</label>
        <input id="crop-zoom" type="range" min="1" max="3" step="0.05" value={zoom} onChange={(e) => setZoom(Number(e.target.value))} />
        <div className="qr-inline-actions">
          <button type="button" className="btn btn-primary" onClick={confirm}>Use image</button>
          <button type="button" className="btn btn-secondary" onClick={() => onConfirm(null)}>Use without cropping</button>
          <button type="button" className="btn-link" onClick={onCancel}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
