interface ContextHelpProps {
  title: string;
  content: string;
}

export function ContextHelp({ title, content }: ContextHelpProps) {
  return (
    <aside className="admin-context-help">
      <h3>{title}</h3>
      <p>{content}</p>
    </aside>
  );
}
