type EmptyStateProps = {
  title: string;
  description: string;
  action?: React.ReactNode;
};

export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div className="state state-empty">
      <h2>{title}</h2>
      <p>{description}</p>
      {action}
    </div>
  );
}
