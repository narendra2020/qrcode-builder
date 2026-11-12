import { useEffect, useRef } from "react";
import client from "../../api/client";

/** Polls the latest extraction job while it is queued/running (backs off to 5s). */
export default function useJobPolling(store, setStore) {
  const active = store?.job && ["queued", "running"].includes(store.job.status);
  const delay = useRef(1500);
  useEffect(() => {
    if (!active) {
      delay.current = 1500;
      return undefined;
    }
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const { data } = await client.get(`/qr/stores/${store.id}/analysis`);
        if (!cancelled) {
          delay.current = Math.min(delay.current * 1.3, 5000);
          setStore((s) => ({ ...s, job: data.job }));
        }
      } catch {
        /* retried on next tick */
      }
    }, delay.current);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [active, store?.job, store?.id, setStore]);
  return active;
}
