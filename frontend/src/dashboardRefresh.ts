export function createRefreshGate() {
  let active: Promise<void> | null = null;
  return {
    async run(work: () => Promise<void>, wait = true): Promise<boolean> {
      while (active) {
        if (!wait) return false;
        await active.catch(() => {});
      }
      const task = Promise.resolve().then(work);
      active = task;
      try {
        await task;
        return true;
      } finally {
        if (active === task) active = null;
      }
    }
  };
}
