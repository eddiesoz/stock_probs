export type BriefingPrivateOperation = Readonly<{
  isCurrent(): boolean;
  commit(effect: () => void): boolean;
}>;

export declare function createBriefingPrivateLifecycle(): Readonly<{
  capture(): BriefingPrivateOperation;
  invalidate(): void;
  acquireRefresh(): number | null;
  ownsRefresh(owner: number): boolean;
  releaseRefresh(owner: number): boolean;
}>;
