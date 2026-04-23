import { ReactNode } from 'react';

interface ModuleWorkspaceProps {
  title: string;
  subtitle: string;
  children: ReactNode;
}

export function ModuleWorkspace({ title, subtitle, children }: ModuleWorkspaceProps) {
  return (
    <section className="admin-module-workspace">
      <header className="admin-module-header">
        <h1>{title}</h1>
        <p>{subtitle}</p>
      </header>
      <div className="admin-module-body">{children}</div>
    </section>
  );
}
