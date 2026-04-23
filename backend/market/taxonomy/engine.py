# backend/market/taxonomy/engine.py
"""
Taxonomy Auto-Update Engine
============================

Self-evolving skill/career ontology with:
- New skill detection
- Synonym clustering
- Skill merging/splitting
- Obsolete skill detection
- Version migration
- Human-in-the-loop override
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import numpy as np

from .models import (
    CareerNode,
    ChangeType,
    MergeCandidate,
    RelationType,
    SkillCluster,
    SkillNode,
    SkillStatus,
    TaxonomyChange,
    TaxonomyVersion,
)

logger = logging.getLogger("market.taxonomy.engine")


# ═══════════════════════════════════════════════════════════════════════
# Text Normalization
# ═══════════════════════════════════════════════════════════════════════


class SkillNormalizer:
    """Normalize skill text for matching."""
    
    def __init__(self):
        # Common patterns
        self._version_pattern = re.compile(r'\s*\d+(\.\d+)*\s*$')
        self._parens_pattern = re.compile(r'\s*\([^)]*\)\s*')
        
        # Known equivalents
        self._equivalents = {
            "js": "javascript",
            "ts": "typescript",
            "py": "python",
            "c#": "csharp",
            "c++": "cplusplus",
            "react.js": "react",
            "reactjs": "react",
            "vue.js": "vue",
            "vuejs": "vue",
            "node.js": "nodejs",
            "express.js": "expressjs",
            "angular.js": "angular",
            "angularjs": "angular",
            "aws": "amazon web services",
            "gcp": "google cloud platform",
            "k8s": "kubernetes",
            "ml": "machine learning",
            "dl": "deep learning",
            "ai": "artificial intelligence",
            "nlp": "natural language processing",
            "cv": "computer vision",
            "sql server": "microsoft sql server",
            "mssql": "microsoft sql server",
            "postgres": "postgresql",
            "mongo": "mongodb",
        }
    
    def normalize(self, skill: str) -> str:
        """Normalize a skill string."""
        s = skill.lower().strip()
        
        # Remove version numbers
        s = self._version_pattern.sub('', s)
        
        # Remove parenthetical content
        s = self._parens_pattern.sub(' ', s)
        
        # Apply equivalents
        if s in self._equivalents:
            s = self._equivalents[s]
        
        # Clean whitespace
        s = ' '.join(s.split())
        
        return s
    
    def generate_id(self, skill: str) -> str:
        """Generate stable ID for a skill."""
        normalized = self.normalize(skill)
        return hashlib.sha256(normalized.encode()).hexdigest()[:12]


# ═══════════════════════════════════════════════════════════════════════
# Embedding & Similarity
# ═══════════════════════════════════════════════════════════════════════


class SkillEmbedder:
    """Generate embeddings for skills."""
    
    def __init__(self):
        self._cache: Dict[str, List[float]] = {}
        self._char_ngram_n = 3
    
    def embed(self, skill: str) -> List[float]:
        """Generate embedding for a skill."""
        if skill in self._cache:
            return self._cache[skill]
        
        # Simple character n-gram based embedding
        # In production, would use sentence transformers or similar
        embedding = self._char_ngram_embed(skill)
        self._cache[skill] = embedding
        return embedding
    
    def _char_ngram_embed(self, text: str, dim: int = 128) -> List[float]:
        """Character n-gram based embedding."""
        text = text.lower()
        ngrams = []
        
        for i in range(len(text) - self._char_ngram_n + 1):
            ngrams.append(text[i:i + self._char_ngram_n])
        
        # Hash ngrams to fixed dimensions
        vec = [0.0] * dim
        for ngram in ngrams:
            h = hash(ngram)
            idx = h % dim
            vec[idx] += 1
        
        # Normalize
        total = sum(v * v for v in vec)
        if total > 0:
            norm = math.sqrt(total)
            vec = [v / norm for v in vec]
        
        return vec
    
    def similarity(self, skill_a: str, skill_b: str) -> float:
        """Calculate cosine similarity between skills."""
        emb_a = self.embed(skill_a)
        emb_b = self.embed(skill_b)
        
        dot = sum(a * b for a, b in zip(emb_a, emb_b))
        return dot


# ═══════════════════════════════════════════════════════════════════════
# Taxonomy Engine
# ═══════════════════════════════════════════════════════════════════════


class TaxonomyEngine:
    """
    Self-evolving taxonomy engine.
    
    Features:
    - Automatic skill detection from job postings
    - Synonym/variant clustering
    - Skill merging and splitting
    - Obsolete skill detection
    - Versioned migrations
    - Human-in-the-loop approval
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        self._root = Path(__file__).resolve().parents[3]
        self._db_path = db_path or self._root / "storage/market/taxonomy.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._lock = RLock()
        
        # Tools
        self._normalizer = SkillNormalizer()
        self._embedder = SkillEmbedder()
        
        # In-memory graph
        self._skills: Dict[str, SkillNode] = {}
        self._careers: Dict[str, CareerNode] = {}
        
        # Pending changes
        self._pending_changes: List[TaxonomyChange] = []
        
        # Callbacks
        self._on_skill_added: List[Callable[[SkillNode], None]] = []
        self._on_skill_merged: List[Callable[[str, str, str], None]] = []
        self._on_change_proposed: List[Callable[[TaxonomyChange], None]] = []
        
        # Configuration
        self._merge_similarity_threshold = 0.85
        self._new_skill_min_frequency = 5
        self._obsolete_days_threshold = 180
        
        self._init_db()
        self._load_graph()
    
    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS skills (
                    skill_id TEXT PRIMARY KEY,
                    canonical_name TEXT NOT NULL,
                    aliases TEXT,  -- JSON array
                    category TEXT,
                    domain TEXT,
                    status TEXT DEFAULT 'emerging',
                    first_seen TEXT,
                    last_seen TEXT,
                    frequency INTEGER DEFAULT 0,
                    job_count INTEGER DEFAULT 0,
                    avg_salary REAL,
                    growth_rate REAL DEFAULT 0,
                    embedding TEXT,  -- JSON array
                    relations TEXT,  -- JSON object
                    source_count TEXT,  -- JSON object
                    confidence REAL DEFAULT 1.0,
                    human_verified INTEGER DEFAULT 0
                );
                
                CREATE TABLE IF NOT EXISTS careers (
                    career_id TEXT PRIMARY KEY,
                    canonical_name TEXT NOT NULL,
                    aliases TEXT,
                    industry TEXT,
                    level TEXT,
                    required_skills TEXT,  -- JSON object
                    optional_skills TEXT,
                    job_count INTEGER DEFAULT 0,
                    avg_salary_min REAL,
                    avg_salary_max REAL,
                    growth_rate REAL DEFAULT 0,
                    related_careers TEXT,  -- JSON array
                    progression_from TEXT,
                    progression_to TEXT
                );
                
                CREATE TABLE IF NOT EXISTS versions (
                    version_id TEXT PRIMARY KEY,
                    version_number TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    skill_count INTEGER,
                    career_count INTEGER,
                    relation_count INTEGER,
                    changes TEXT,  -- JSON array
                    auto_generated INTEGER DEFAULT 1,
                    human_approved INTEGER DEFAULT 0,
                    approved_by TEXT,
                    notes TEXT
                );
                
                CREATE TABLE IF NOT EXISTS changes (
                    change_id TEXT PRIMARY KEY,
                    change_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    entity_type TEXT,
                    entity_id TEXT,
                    old_value TEXT,
                    new_value TEXT,
                    confidence REAL,
                    evidence TEXT,
                    status TEXT DEFAULT 'proposed',
                    proposed_by TEXT,
                    reviewed_by TEXT,
                    review_notes TEXT
                );
                
                CREATE TABLE IF NOT EXISTS skill_observations (
                    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_text TEXT NOT NULL,
                    normalized TEXT NOT NULL,
                    source TEXT,
                    job_id TEXT,
                    observed_at TEXT,
                    salary_context REAL
                );
                
                CREATE INDEX IF NOT EXISTS idx_observations_normalized ON skill_observations(normalized);
                CREATE INDEX IF NOT EXISTS idx_skills_status ON skills(status);
                CREATE INDEX IF NOT EXISTS idx_changes_status ON changes(status);
            """)
    
    def _load_graph(self) -> None:
        """Load taxonomy graph from database."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            
            # Load skills
            for row in conn.execute("SELECT * FROM skills"):
                skill = SkillNode(
                    skill_id=row["skill_id"],
                    canonical_name=row["canonical_name"],
                    aliases=set(json.loads(row["aliases"] or "[]")),
                    category=row["category"] or "",
                    domain=row["domain"] or "",
                    status=SkillStatus(row["status"]),
                    first_seen=datetime.fromisoformat(row["first_seen"]) if row["first_seen"] else datetime.now(timezone.utc),
                    last_seen=datetime.fromisoformat(row["last_seen"]) if row["last_seen"] else datetime.now(timezone.utc),
                    frequency=row["frequency"],
                    job_count=row["job_count"],
                    avg_salary=row["avg_salary"],
                    growth_rate=row["growth_rate"],
                    embedding=json.loads(row["embedding"]) if row["embedding"] else None,
                    relations={k: RelationType(v) for k, v in json.loads(row["relations"] or "{}").items()},
                    source_count=json.loads(row["source_count"] or "{}"),
                    confidence=row["confidence"],
                    human_verified=bool(row["human_verified"]),
                )
                self._skills[skill.skill_id] = skill
            
            # Load careers
            for row in conn.execute("SELECT * FROM careers"):
                career = CareerNode(
                    career_id=row["career_id"],
                    canonical_name=row["canonical_name"],
                    aliases=set(json.loads(row["aliases"] or "[]")),
                    industry=row["industry"] or "",
                    level=row["level"] or "",
                    required_skills=json.loads(row["required_skills"] or "{}"),
                    optional_skills=json.loads(row["optional_skills"] or "{}"),
                    job_count=row["job_count"],
                    avg_salary_range=(row["avg_salary_min"], row["avg_salary_max"]) if row["avg_salary_min"] else None,
                    growth_rate=row["growth_rate"],
                    related_careers=json.loads(row["related_careers"] or "[]"),
                    progression_from=json.loads(row["progression_from"] or "[]"),
                    progression_to=json.loads(row["progression_to"] or "[]"),
                )
                self._careers[career.career_id] = career
        
        logger.info(f"Loaded taxonomy: {len(self._skills)} skills, {len(self._careers)} careers")
    
    # ═══════════════════════════════════════════════════════════════════
    # Skill Observation & Detection
    # ═══════════════════════════════════════════════════════════════════
    
    def observe_skill(
        self,
        skill_text: str,
        source: str,
        job_id: Optional[str] = None,
        salary_context: Optional[float] = None,
    ) -> None:
        """
        Record skill observation from market data.
        
        Called when processing job postings.
        """
        normalized = self._normalizer.normalize(skill_text)
        
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("""
                INSERT INTO skill_observations
                (skill_text, normalized, source, job_id, observed_at, salary_context)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                skill_text,
                normalized,
                source,
                job_id,
                datetime.now(timezone.utc).isoformat(),
                salary_context,
            ))
    
    def detect_new_skills(self, min_frequency: Optional[int] = None) -> List[SkillNode]:
        """
        Detect new skills from observations.
        
        Returns list of newly detected skills.
        """
        min_freq = min_frequency or self._new_skill_min_frequency
        new_skills = []
        
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            
            # Find skills meeting frequency threshold
            rows = conn.execute("""
                SELECT normalized, COUNT(*) as cnt, AVG(salary_context) as avg_sal
                FROM skill_observations
                WHERE observed_at > ?
                GROUP BY normalized
                HAVING cnt >= ?
            """, (
                (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),
                min_freq,
            )).fetchall()
            
            for row in rows:
                normalized = row["normalized"]
                skill_id = self._normalizer.generate_id(normalized)
                
                if skill_id not in self._skills:
                    # New skill detected
                    skill = SkillNode(
                        skill_id=skill_id,
                        canonical_name=normalized,
                        status=SkillStatus.EMERGING,
                        frequency=row["cnt"],
                        avg_salary=row["avg_sal"],
                    )
                    
                    # Generate embedding
                    skill.embedding = self._embedder.embed(normalized)
                    
                    # Auto-categorize
                    skill.category = self._infer_category(normalized)
                    
                    # Add to graph
                    self._skills[skill_id] = skill
                    self._save_skill(skill)
                    new_skills.append(skill)
                    
                    # Create change record
                    self._propose_change(
                        ChangeType.SKILL_ADDED,
                        "skill",
                        skill_id,
                        None,
                        skill.to_dict(),
                        confidence=0.8,
                        evidence=[f"Frequency: {row['cnt']}", f"Auto-detected from market data"],
                    )
                    
                    # Trigger callbacks
                    for callback in self._on_skill_added:
                        try:
                            callback(skill)
                        except Exception as e:
                            logger.error(f"Skill added callback error: {e}")
        
        logger.info(f"Detected {len(new_skills)} new skills")
        return new_skills
    
    def _infer_category(self, skill_name: str) -> str:
        """Infer skill category from name."""
        name = skill_name.lower()
        
        # Programming languages
        if any(lang in name for lang in ["python", "java", "javascript", "typescript", "c++", "ruby", "go", "rust", "php", "swift", "kotlin"]):
            return "programming_language"
        
        # Frameworks
        if any(fw in name for fw in ["react", "angular", "vue", "django", "flask", "spring", "express", "rails", "laravel"]):
            return "framework"
        
        # Databases
        if any(db in name for db in ["sql", "mysql", "postgresql", "mongodb", "redis", "elasticsearch", "cassandra"]):
            return "database"
        
        # Cloud
        if any(cloud in name for cloud in ["aws", "azure", "gcp", "cloud", "kubernetes", "docker"]):
            return "cloud"
        
        # Data
        if any(data in name for data in ["machine learning", "deep learning", "data science", "analytics", "big data", "spark", "hadoop"]):
            return "data_science"
        
        # Soft skills
        if any(soft in name for soft in ["communication", "leadership", "teamwork", "problem solving", "management"]):
            return "soft_skill"
        
        return "technical"
    
    def _save_skill(self, skill: SkillNode) -> None:
        """Save skill to database."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO skills
                (skill_id, canonical_name, aliases, category, domain, status,
                 first_seen, last_seen, frequency, job_count, avg_salary, growth_rate,
                 embedding, relations, source_count, confidence, human_verified)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                skill.skill_id,
                skill.canonical_name,
                json.dumps(list(skill.aliases)),
                skill.category,
                skill.domain,
                skill.status.value,
                skill.first_seen.isoformat(),
                skill.last_seen.isoformat(),
                skill.frequency,
                skill.job_count,
                skill.avg_salary,
                skill.growth_rate,
                json.dumps(skill.embedding) if skill.embedding else None,
                json.dumps({k: v.value for k, v in skill.relations.items()}),
                json.dumps(skill.source_count),
                skill.confidence,
                1 if skill.human_verified else 0,
            ))
    
    # ═══════════════════════════════════════════════════════════════════
    # Synonym Clustering & Merging
    # ═══════════════════════════════════════════════════════════════════
    
    def find_merge_candidates(
        self,
        similarity_threshold: Optional[float] = None,
    ) -> List[MergeCandidate]:
        """
        Find skills that should potentially be merged.
        """
        threshold = similarity_threshold or self._merge_similarity_threshold
        candidates = []
        
        skills = list(self._skills.values())
        
        for i, skill_a in enumerate(skills):
            for skill_b in skills[i + 1:]:
                # Skip if already related
                if skill_b.skill_id in skill_a.relations:
                    continue
                
                # Calculate similarity
                sim = self._embedder.similarity(
                    skill_a.canonical_name,
                    skill_b.canonical_name,
                )
                
                if sim >= threshold:
                    # Determine canonical name (prefer higher frequency)
                    if skill_a.frequency >= skill_b.frequency:
                        canonical = skill_a.canonical_name
                    else:
                        canonical = skill_b.canonical_name
                    
                    evidence = [
                        f"Embedding similarity: {sim:.3f}",
                        f"{skill_a.canonical_name} frequency: {skill_a.frequency}",
                        f"{skill_b.canonical_name} frequency: {skill_b.frequency}",
                    ]
                    
                    candidates.append(MergeCandidate(
                        skill_a=skill_a.skill_id,
                        skill_b=skill_b.skill_id,
                        similarity=sim,
                        evidence=evidence,
                        recommended_canonical=canonical,
                        confidence=sim,
                    ))
        
        # Sort by similarity
        candidates.sort(key=lambda c: -c.similarity)
        
        return candidates
    
    def merge_skills(
        self,
        primary_id: str,
        secondary_id: str,
        canonical_name: Optional[str] = None,
    ) -> SkillNode:
        """
        Merge two skills into one.
        
        Args:
            primary_id: ID of primary skill (kept)
            secondary_id: ID of secondary skill (merged into primary)
            canonical_name: Optional new canonical name
        
        Returns:
            Updated primary skill
        """
        primary = self._skills.get(primary_id)
        secondary = self._skills.get(secondary_id)
        
        if not primary or not secondary:
            raise ValueError("Skill not found")
        
        # Merge into primary
        primary.aliases.add(secondary.canonical_name)
        primary.aliases.update(secondary.aliases)
        
        if canonical_name:
            primary.canonical_name = canonical_name
        
        # Merge frequencies and stats
        primary.frequency += secondary.frequency
        primary.job_count = max(primary.job_count, secondary.job_count)
        
        if primary.avg_salary and secondary.avg_salary:
            primary.avg_salary = (primary.avg_salary + secondary.avg_salary) / 2
        
        # Merge relations
        for skill_id, rel_type in secondary.relations.items():
            if skill_id not in primary.relations:
                primary.relations[skill_id] = rel_type
        
        # Merge source counts
        for source, count in secondary.source_count.items():
            primary.source_count[source] = primary.source_count.get(source, 0) + count
        
        # Mark secondary as merged
        secondary.status = SkillStatus.MERGED
        secondary.relations[primary_id] = RelationType.SUPERSEDES
        
        # Save changes
        self._save_skill(primary)
        self._save_skill(secondary)
        
        # Create change record
        self._propose_change(
            ChangeType.SKILL_MERGED,
            "skill",
            primary_id,
            {"primary": primary_id, "secondary": secondary_id},
            primary.to_dict(),
            confidence=1.0,
            evidence=[f"Merged {secondary.canonical_name} into {primary.canonical_name}"],
        )
        
        # Trigger callbacks
        for callback in self._on_skill_merged:
            try:
                callback(primary_id, secondary_id, primary.canonical_name)
            except Exception as e:
                logger.error(f"Skill merged callback error: {e}")
        
        logger.info(f"Merged skill {secondary.canonical_name} into {primary.canonical_name}")
        return primary
    
    # ═══════════════════════════════════════════════════════════════════
    # Obsolete Skill Detection
    # ═══════════════════════════════════════════════════════════════════
    
    def detect_obsolete_skills(
        self,
        days_threshold: Optional[int] = None,
    ) -> List[SkillNode]:
        """
        Detect skills that may be obsolete.
        """
        threshold = days_threshold or self._obsolete_days_threshold
        cutoff = datetime.now(timezone.utc) - timedelta(days=threshold)
        
        obsolete = []
        
        for skill in self._skills.values():
            if skill.status in [SkillStatus.MERGED, SkillStatus.OBSOLETE]:
                continue
            
            if skill.last_seen < cutoff and skill.growth_rate < -0.2:
                skill.status = SkillStatus.DECLINING
                self._save_skill(skill)
                obsolete.append(skill)
                
                # Propose deprecation
                self._propose_change(
                    ChangeType.SKILL_DEPRECATED,
                    "skill",
                    skill.skill_id,
                    skill.status.value,
                    SkillStatus.OBSOLETE.value,
                    confidence=0.7,
                    evidence=[
                        f"Last seen: {skill.last_seen.isoformat()}",
                        f"Growth rate: {skill.growth_rate:.2%}",
                    ],
                )
        
        return obsolete
    
    # ═══════════════════════════════════════════════════════════════════
    # Skill Clustering
    # ═══════════════════════════════════════════════════════════════════
    
    def cluster_skills(self, n_clusters: int = 20) -> List[SkillCluster]:
        """
        Cluster skills by embedding similarity.
        
        Uses simple k-means-like clustering.
        """
        skills_with_emb = [s for s in self._skills.values() if s.embedding]
        
        if len(skills_with_emb) < n_clusters:
            n_clusters = max(1, len(skills_with_emb) // 3)
        
        if not skills_with_emb:
            return []
        
        # Simple clustering by iterative refinement
        embeddings = np.array([s.embedding for s in skills_with_emb])
        
        # Initialize centroids randomly
        indices = np.random.choice(len(embeddings), n_clusters, replace=False)
        centroids = embeddings[indices].copy()
        
        # Iterate
        for _ in range(20):
            # Assign to nearest centroid
            assignments = []
            for emb in embeddings:
                distances = [np.linalg.norm(emb - c) for c in centroids]
                assignments.append(np.argmin(distances))
            
            # Update centroids
            new_centroids = []
            for k in range(n_clusters):
                cluster_embs = [embeddings[i] for i, a in enumerate(assignments) if a == k]
                if cluster_embs:
                    new_centroids.append(np.mean(cluster_embs, axis=0))
                else:
                    new_centroids.append(centroids[k])
            centroids = np.array(new_centroids)
        
        # Build clusters
        clusters = []
        for k in range(n_clusters):
            cluster_skills = [
                skills_with_emb[i].skill_id
                for i, a in enumerate(assignments)
                if a == k
            ]
            
            if not cluster_skills:
                continue
            
            # Calculate coherence
            if len(cluster_skills) > 1:
                cluster_embs = [
                    self._skills[sid].embedding
                    for sid in cluster_skills
                    if self._skills[sid].embedding
                ]
                if cluster_embs:
                    mean_emb = np.mean(cluster_embs, axis=0)
                    distances = [np.linalg.norm(e - mean_emb) for e in cluster_embs]
                    coherence = 1.0 / (1.0 + np.mean(distances))
                else:
                    coherence = 0.0
            else:
                coherence = 1.0
            
            # Name cluster by most frequent skill
            name_skill = max(cluster_skills, key=lambda sid: self._skills[sid].frequency)
            
            clusters.append(SkillCluster(
                cluster_id=f"cluster_{k}",
                name=self._skills[name_skill].canonical_name,
                skills=cluster_skills,
                centroid=centroids[k].tolist(),
                coherence=coherence,
            ))
        
        return clusters
    
    # ═══════════════════════════════════════════════════════════════════
    # Change Management
    # ═══════════════════════════════════════════════════════════════════
    
    def _propose_change(
        self,
        change_type: ChangeType,
        entity_type: str,
        entity_id: str,
        old_value: Any,
        new_value: Any,
        confidence: float = 1.0,
        evidence: Optional[List[str]] = None,
    ) -> TaxonomyChange:
        """Create a proposed change."""
        change = TaxonomyChange(
            change_id=f"chg_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{entity_id[:8]}",
            change_type=change_type,
            timestamp=datetime.now(timezone.utc),
            entity_type=entity_type,
            entity_id=entity_id,
            old_value=old_value,
            new_value=new_value,
            confidence=confidence,
            evidence=evidence or [],
            status="proposed",
            proposed_by="auto",
        )
        
        self._pending_changes.append(change)
        self._save_change(change)
        
        # Trigger callbacks
        for callback in self._on_change_proposed:
            try:
                callback(change)
            except Exception as e:
                logger.error(f"Change proposed callback error: {e}")
        
        return change
    
    def _save_change(self, change: TaxonomyChange) -> None:
        """Save change to database."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO changes
                (change_id, change_type, timestamp, entity_type, entity_id,
                 old_value, new_value, confidence, evidence, status,
                 proposed_by, reviewed_by, review_notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                change.change_id,
                change.change_type.value,
                change.timestamp.isoformat(),
                change.entity_type,
                change.entity_id,
                json.dumps(change.old_value) if change.old_value else None,
                json.dumps(change.new_value) if change.new_value else None,
                change.confidence,
                json.dumps(change.evidence),
                change.status,
                change.proposed_by,
                change.reviewed_by,
                change.review_notes,
            ))
    
    def get_pending_changes(self) -> List[TaxonomyChange]:
        """Get all pending changes for review."""
        return [c for c in self._pending_changes if c.status == "proposed"]
    
    def approve_change(
        self,
        change_id: str,
        reviewer: str,
        notes: Optional[str] = None,
    ) -> bool:
        """Approve a proposed change."""
        for change in self._pending_changes:
            if change.change_id == change_id:
                change.status = "approved"
                change.reviewed_by = reviewer
                change.review_notes = notes
                self._save_change(change)
                return True
        return False
    
    def reject_change(
        self,
        change_id: str,
        reviewer: str,
        notes: Optional[str] = None,
    ) -> bool:
        """Reject a proposed change."""
        for change in self._pending_changes:
            if change.change_id == change_id:
                change.status = "rejected"
                change.reviewed_by = reviewer
                change.review_notes = notes
                self._save_change(change)
                return True
        return False
    
    # ═══════════════════════════════════════════════════════════════════
    # Versioning
    # ═══════════════════════════════════════════════════════════════════
    
    def create_version(self, notes: str = "") -> TaxonomyVersion:
        """Create a new taxonomy version snapshot."""
        # Get current version number
        with sqlite3.connect(str(self._db_path)) as conn:
            row = conn.execute("""
                SELECT version_number FROM versions
                ORDER BY created_at DESC LIMIT 1
            """).fetchone()
            
            if row:
                parts = row[0].split(".")
                parts[-1] = str(int(parts[-1]) + 1)
                version_number = ".".join(parts)
            else:
                version_number = "1.0.0"
        
        # Collect changes since last version
        pending = [c.to_dict() for c in self._pending_changes if c.status in ["approved", "applied"]]
        
        # Count relations
        relation_count = sum(len(s.relations) for s in self._skills.values())
        
        version = TaxonomyVersion(
            version_id=f"v_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            version_number=version_number,
            created_at=datetime.now(timezone.utc),
            skill_count=len(self._skills),
            career_count=len(self._careers),
            relation_count=relation_count,
            changes=pending,
            auto_generated=True,
            notes=notes,
        )
        
        # Save version
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("""
                INSERT INTO versions
                (version_id, version_number, created_at, skill_count, career_count,
                 relation_count, changes, auto_generated, human_approved, approved_by, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                version.version_id,
                version.version_number,
                version.created_at.isoformat(),
                version.skill_count,
                version.career_count,
                version.relation_count,
                json.dumps(version.changes),
                1 if version.auto_generated else 0,
                1 if version.human_approved else 0,
                version.approved_by,
                version.notes,
            ))
        
        # Mark changes as applied
        for change in self._pending_changes:
            if change.status == "approved":
                change.status = "applied"
                self._save_change(change)
        
        logger.info(f"Created taxonomy version {version_number}")
        return version
    
    def get_current_version(self) -> Optional[TaxonomyVersion]:
        """Get current taxonomy version."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("""
                SELECT * FROM versions ORDER BY created_at DESC LIMIT 1
            """).fetchone()
            
            if row:
                return TaxonomyVersion(
                    version_id=row["version_id"],
                    version_number=row["version_number"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    skill_count=row["skill_count"],
                    career_count=row["career_count"],
                    relation_count=row["relation_count"],
                    changes=json.loads(row["changes"] or "[]"),
                    auto_generated=bool(row["auto_generated"]),
                    human_approved=bool(row["human_approved"]),
                    approved_by=row["approved_by"],
                    notes=row["notes"] or "",
                )
        return None
    
    # ═══════════════════════════════════════════════════════════════════
    # Query Interface
    # ═══════════════════════════════════════════════════════════════════
    
    def get_skill(self, skill_id: str) -> Optional[SkillNode]:
        """Get skill by ID."""
        return self._skills.get(skill_id)
    
    def find_skill(self, name: str) -> Optional[SkillNode]:
        """Find skill by name or alias."""
        normalized = self._normalizer.normalize(name)
        skill_id = self._normalizer.generate_id(normalized)
        
        if skill_id in self._skills:
            return self._skills[skill_id]
        
        # Search aliases
        for skill in self._skills.values():
            if normalized in [self._normalizer.normalize(a) for a in skill.aliases]:
                return skill
        
        return None
    
    def get_all_skills(
        self,
        status: Optional[SkillStatus] = None,
        category: Optional[str] = None,
    ) -> List[SkillNode]:
        """Get all skills with optional filters."""
        skills = list(self._skills.values())
        
        if status:
            skills = [s for s in skills if s.status == status]
        
        if category:
            skills = [s for s in skills if s.category == category]
        
        return skills
    
    def get_related_skills(self, skill_id: str) -> List[Tuple[SkillNode, RelationType]]:
        """Get skills related to a given skill."""
        skill = self._skills.get(skill_id)
        if not skill:
            return []
        
        related = []
        for rel_id, rel_type in skill.relations.items():
            rel_skill = self._skills.get(rel_id)
            if rel_skill:
                related.append((rel_skill, rel_type))
        
        return related
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get taxonomy statistics."""
        by_status = Counter(s.status.value for s in self._skills.values())
        by_category = Counter(s.category for s in self._skills.values())
        
        return {
            "total_skills": len(self._skills),
            "total_careers": len(self._careers),
            "by_status": dict(by_status),
            "by_category": dict(by_category),
            "pending_changes": len(self.get_pending_changes()),
            "current_version": self.get_current_version().version_number if self.get_current_version() else "0.0.0",
        }


# ═══════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════

_engine: Optional[TaxonomyEngine] = None


def get_taxonomy_engine() -> TaxonomyEngine:
    """Get singleton TaxonomyEngine instance."""
    global _engine
    if _engine is None:
        _engine = TaxonomyEngine()
    return _engine
