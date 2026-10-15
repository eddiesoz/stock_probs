export function createBriefingPrivateLifecycle() {
  let generation = 0;
  let refreshSequence = 0;
  let refreshOwner = null;

  return Object.freeze({
    capture() {
      const captured = generation;
      return Object.freeze({
        isCurrent: () => captured === generation,
        commit(effect) {
          if (captured !== generation) return false;
          effect();
          return true;
        },
      });
    },
    invalidate() {
      generation += 1;
      refreshOwner = null;
    },
    acquireRefresh() {
      if (refreshOwner !== null) return null;
      refreshOwner = ++refreshSequence;
      return refreshOwner;
    },
    ownsRefresh(owner) {
      return owner === refreshOwner;
    },
    releaseRefresh(owner) {
      if (owner !== refreshOwner) return false;
      refreshOwner = null;
      return true;
    },
  });
}
