import { type MouseEvent, type PointerEvent, useCallback, useLayoutEffect, useRef, useState } from "react";

// The text layer's container also covers blank paper: only its text spans opt out.
const selectionTargets =
  ".textLayer span, .textLayer br, button, a, input, textarea, select, [contenteditable], [role='button'], [tabindex]";

/** Mouse-only panning for the document preview; native selection and other input stay intact. */
export function useDocumentPan(enabled: boolean, sourceKey: string) {
  const ref = useRef<HTMLElement>(null);
  const drag = useRef<{ pointerId: number; x: number; y: number; left: number; top: number } | null>(null);
  const suppressPanMouseUp = useRef(false);
  const [canPan, setCanPan] = useState(false);
  const [dragging, setDragging] = useState(false);
  const stop = useCallback(() => {
    const pointerId = drag.current?.pointerId;
    drag.current = null;
    setDragging(false);
    if (pointerId !== undefined && ref.current?.hasPointerCapture(pointerId)) {
      ref.current.releasePointerCapture(pointerId);
    }
  }, []);

  useLayoutEffect(() => {
    const element = ref.current;
    suppressPanMouseUp.current = false;
    if (!element) return;
    const measure = () =>
      setCanPan(enabled && (element.scrollWidth > element.clientWidth || element.scrollHeight > element.clientHeight));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    if (element.firstElementChild) observer.observe(element.firstElementChild);
    window.addEventListener("blur", stop);
    return () => {
      observer.disconnect();
      window.removeEventListener("blur", stop);
      stop();
    };
  }, [enabled, sourceKey, stop]);

  const onPointerDown = (event: PointerEvent<HTMLElement>) => {
    if (!drag.current) suppressPanMouseUp.current = false;
    if (!enabled || !canPan || event.pointerType !== "mouse" || event.button !== 0 || drag.current) return;
    const target = event.target instanceof Element ? event.target.closest(selectionTargets) : null;
    if (target && target !== event.currentTarget) return;
    const element = event.currentTarget;
    const bounds = element.getBoundingClientRect();
    // Leave native scrollbar interaction alone.
    if (event.clientX >= bounds.left + element.clientWidth || event.clientY >= bounds.top + element.clientHeight)
      return;
    event.preventDefault();
    suppressPanMouseUp.current = true;
    drag.current = {
      pointerId: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      left: element.scrollLeft,
      top: element.scrollTop,
    };
    element.setPointerCapture(event.pointerId);
    setDragging(true);
  };
  const onPointerMove = (event: PointerEvent<HTMLElement>) => {
    const active = drag.current;
    if (!active || active.pointerId !== event.pointerId) return;
    if (!(event.buttons & 1)) return stop();
    event.preventDefault();
    event.currentTarget.scrollLeft = active.left + active.x - event.clientX;
    event.currentTarget.scrollTop = active.top + active.y - event.clientY;
  };
  const onPointerEnd = (event: PointerEvent<HTMLElement>) => {
    if (drag.current?.pointerId === event.pointerId) stop();
  };

  return {
    ref,
    canPan,
    dragging,
    handlers: {
      onPointerDown,
      onPointerMove,
      onPointerUp: onPointerEnd,
      onPointerCancel: onPointerEnd,
      onLostPointerCapture: onPointerEnd,
      onMouseUpCapture: (event: MouseEvent<HTMLElement>) => {
        // Do not recapture an older PDF text selection through the pane's global
        // mouseup listener. The next real text pointerdown clears this guard.
        if (suppressPanMouseUp.current) {
          suppressPanMouseUp.current = false;
          event.stopPropagation();
        }
      },
    },
  };
}
