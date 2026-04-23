import { ModuleWorkspace } from '../../shared/ModuleWorkspace';

export function KnowledgeBaseWorkspace() {
  return (
    <ModuleWorkspace title="Knowledge Base" subtitle="Control ingestion, indexing and retrieval assets">
      <div className="admin-grid-cards">
        <article className="admin-card"><h3>Corpus Overview</h3><p>Indexed sources and growth metrics.</p></article>
        <article className="admin-card"><h3>Document Health</h3><p>Chunk quality and embedding coverage.</p></article>
        <article className="admin-card"><h3>Sync Queue</h3><p>Pending re-index and source sync tasks.</p></article>
      </div>
    </ModuleWorkspace>
  );
}
