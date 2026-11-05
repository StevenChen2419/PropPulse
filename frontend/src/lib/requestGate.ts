/** Each request owns a generation. Cancellation alone is insufficient when a
 * transport ignores AbortSignal or JSON parsing finishes after navigation. */
export function createRequestGate() {
  let generation = 0;
  let controller: AbortController | undefined;
  const cancel = () => { generation++; controller?.abort(); };
  return {
    cancel,
    start() {
      cancel();
      controller = new AbortController();
      const current = generation;
      const signal = controller.signal;
      return { signal, isCurrent: () => current === generation && !signal.aborted };
    },
  };
}
