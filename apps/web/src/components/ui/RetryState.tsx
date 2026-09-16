type RetryStateProps = {
  title?: string;
  message: string;
  onRetry: () => void;
};

export function RetryState({
  title = "Something went wrong",
  message,
  onRetry,
}: RetryStateProps) {
  return (
    <div className="state state-retry" role="alert">
      <h2>{title}</h2>
      <p>{message}</p>
      <button type="button" onClick={onRetry}>
        Retry
      </button>
    </div>
  );
}
