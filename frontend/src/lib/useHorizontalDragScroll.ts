import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEventHandler,
  type RefObject,
} from "react";

const DRAG_THRESHOLD_PX = 8;

type DragGesture = {
  pointerId: number;
  startX: number;
  startScrollLeft: number;
};

/** Pointer-driven horizontal scroll for overflow-x regions (mouse + touch). */
export function useHorizontalDragScroll<T extends HTMLElement>(): {
  ref: RefObject<T | null>;
  dragging: boolean;
  onPointerDown: PointerEventHandler<T>;
  consumeClickSuppression: () => boolean;
} {
  const ref = useRef<T>(null);
  const gesture = useRef<DragGesture | null>(null);
  const dragged = useRef(false);
  const [dragging, setDragging] = useState(false);

  const windowMoveRef = useRef<(e: PointerEvent) => void>(() => {});
  const windowUpRef = useRef<(e: PointerEvent) => void>(() => {});

  const clearWindowListeners = useCallback(() => {
    window.removeEventListener("pointermove", windowMoveRef.current);
    window.removeEventListener("pointerup", windowUpRef.current);
    window.removeEventListener("pointercancel", windowUpRef.current);
  }, []);

  useEffect(() => clearWindowListeners, [clearWindowListeners]);

  windowMoveRef.current = (e: PointerEvent) => {
    const g = gesture.current;
    const el = ref.current;
    if (!g || !el || e.pointerId !== g.pointerId) return;

    const dx = e.clientX - g.startX;
    if (!dragged.current && Math.abs(dx) >= DRAG_THRESHOLD_PX) {
      dragged.current = true;
      setDragging(true);
    }
    if (!dragged.current) return;

    e.preventDefault();
    el.scrollLeft = g.startScrollLeft - dx;
  };

  windowUpRef.current = (e: PointerEvent) => {
    if (gesture.current?.pointerId !== e.pointerId) return;
    clearWindowListeners();
    gesture.current = null;
    setDragging(false);
  };

  const onPointerDown = useCallback<PointerEventHandler<T>>(
    (e) => {
      if (e.button !== 0) return;
      const el = ref.current;
      if (!el || !el.contains(e.target as Node)) return;

      dragged.current = false;
      gesture.current = {
        pointerId: e.pointerId,
        startX: e.clientX,
        startScrollLeft: el.scrollLeft,
      };

      window.addEventListener("pointermove", windowMoveRef.current);
      window.addEventListener("pointerup", windowUpRef.current);
      window.addEventListener("pointercancel", windowUpRef.current);
    },
    [clearWindowListeners],
  );

  const consumeClickSuppression = useCallback(() => {
    if (!dragged.current) return false;
    dragged.current = false;
    return true;
  }, []);

  return {
    ref,
    dragging,
    onPointerDown,
    consumeClickSuppression,
  };
}
