# backend/kb/migration.py
"""
KB Migration Utilities

- Export KB data to JSON for backups
- Import KB data from JSON for restore/migration
- Generate migration reports
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

from backend.kb.database import get_db_context, init_db
from backend.kb.service import KnowledgeBaseService
from backend.kb import schemas


# ============================
# LOGGING
# ============================

logger = logging.getLogger("kb-migration")


# ============================
# EXPORT
# ============================

def export_kb_to_json(output_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Export entire KB to JSON format.
    
    Returns:
        Dict with all KB entities
    """
    logger.info("Starting KB export...")
    
    with get_db_context() as db:
        kb = KnowledgeBaseService(db)
        
        # Export all entities
        export_data = {
            "metadata": {
                "exported_at": datetime.utcnow().isoformat(),
                "version": "2.0",
            },
            "domains": [],
            "education_levels": [],
            "skills": [],
            "careers": [],
            "templates": [],
            "ontology_nodes": [],
        }
        
        # Domains
        domains = kb.list_domains(limit=10000)
        for d in domains:
            export_data["domains"].append({
                "id": d.id,
                "name": d.name,
                "slug": d.slug,
                "description": d.description,
                "icon": d.icon,
                "interests": d.interests or [],
                "is_active": d.is_active,
            })
        
        # Education levels
        edu_levels = kb.list_education_levels()
        for e in edu_levels:
            export_data["education_levels"].append({
                "id": e.id,
                "name": e.name,
                "hierarchy_level": e.hierarchy_level,
                "description": e.description,
            })
        
        # Skills
        skills = kb.list_skills(limit=10000)
        for s in skills:
            export_data["skills"].append({
                "id": s.id,
                "name": s.name,
                "code": getattr(s, "code", None),
                "category": s.category,
                "description": s.description,
                "version": getattr(s, "version", 1),
                "level_map": getattr(s, "level_map", None),
                "related_skills": getattr(s, "related_skills", None),
            })
        
        # Careers
        careers = kb.list_careers(limit=10000)
        for c in careers:
            career_data = {
                "id": c.id,
                "name": c.name,
                "slug": c.slug,
                "code": getattr(c, "code", None),
                "level": getattr(c, "level", None),
                "domain_id": c.domain_id,
                "description": c.description,
                "icon": c.icon,
                "education_min": c.education_min,
                "ai_relevance": c.ai_relevance,
                "competition": c.competition,
                "growth_rate": c.growth_rate,
                "market_tags": getattr(c, "market_tags", None),
                "version": getattr(c, "version", 1),
                "is_active": c.is_active,
                "skills": [],
                "roadmaps": [],
            }
            
            # Career skills
            if hasattr(c, "skills"):
                for cs in c.skills:
                    career_data["skills"].append({
                        "skill_id": cs.skill_id,
                        "requirement_type": cs.requirement_type.value if hasattr(cs.requirement_type, "value") else cs.requirement_type,
                        "proficiency_level": cs.proficiency_level.value if hasattr(cs.proficiency_level, "value") else cs.proficiency_level,
                    })
            
            # Roadmaps
            if hasattr(c, "roadmaps"):
                for r in c.roadmaps:
                    career_data["roadmaps"].append({
                        "title": r.title,
                        "description": r.description,
                        "level": r.level,
                        "step_order": r.step_order,
                        "duration_months": r.duration_months,
                    })
            
            export_data["careers"].append(career_data)
        
        # Templates (if exist)
        try:
            templates = kb.list_templates(limit=10000)
            for t in templates:
                export_data["templates"].append({
                    "id": t.id,
                    "code": t.code,
                    "type": t.type.value if hasattr(t.type, "value") else t.type,
                    "name": t.name,
                    "content": t.content,
                    "variables": t.variables or [],
                    "version": getattr(t, "version", 1),
                })
        except Exception as e:
            logger.warning("Templates export skipped: %s", e)
        
        # Ontology nodes (if exist)
        try:
            nodes = kb.list_ontology_nodes(limit=10000)
            for n in nodes:
                export_data["ontology_nodes"].append({
                    "node_id": n.node_id,
                    "code": n.code,
                    "type": n.type.value if hasattr(n.type, "value") else n.type,
                    "label": n.label,
                    "parent_id": n.parent_id,
                    "relations": n.relations or {},
                    "metadata": n.metadata or {},
                    "version": getattr(n, "version", 1),
                })
        except Exception as e:
            logger.warning("Ontology export skipped: %s", e)
        
        # Summary
        export_data["metadata"]["counts"] = {
            "domains": len(export_data["domains"]),
            "education_levels": len(export_data["education_levels"]),
            "skills": len(export_data["skills"]),
            "careers": len(export_data["careers"]),
            "templates": len(export_data["templates"]),
            "ontology_nodes": len(export_data["ontology_nodes"]),
        }
        
        # Save to file if path provided
        if output_path:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            logger.info("Exported to: %s", path)
        
        logger.info("Export complete: %s", export_data["metadata"]["counts"])
        return export_data


# ============================
# IMPORT
# ============================

def import_kb_from_json(
    input_path: str,
    dry_run: bool = True,
    skip_existing: bool = True
) -> Dict[str, Any]:
    """
    Import KB data from JSON file.
    
    Args:
        input_path: Path to JSON file
        dry_run: If True, validate only without saving
        skip_existing: If True, skip entities that already exist
    
    Returns:
        Import result summary
    """
    logger.info("Starting KB import from: %s (dry_run=%s)", input_path, dry_run)
    
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    result = {
        "dry_run": dry_run,
        "source_file": input_path,
        "imported_at": datetime.utcnow().isoformat(),
        "domains": {"success": 0, "skipped": 0, "errors": []},
        "education_levels": {"success": 0, "skipped": 0, "errors": []},
        "skills": {"success": 0, "skipped": 0, "errors": []},
        "careers": {"success": 0, "skipped": 0, "errors": []},
        "templates": {"success": 0, "skipped": 0, "errors": []},
        "ontology_nodes": {"success": 0, "skipped": 0, "errors": []},
    }
    
    with get_db_context() as db:
        kb = KnowledgeBaseService(db)
        
        # Import domains
        for d in data.get("domains", []):
            try:
                existing = kb.get_domain_by_name(d["name"])
                if existing and skip_existing:
                    result["domains"]["skipped"] += 1
                    continue
                
                if not dry_run:
                    domain = schemas.DomainCreate(
                        name=d["name"],
                        description=d.get("description"),
                        icon=d.get("icon"),
                        interests=d.get("interests", []),
                    )
                    kb.create_domain(domain)
                result["domains"]["success"] += 1
            except Exception as e:
                result["domains"]["errors"].append({"name": d.get("name"), "error": str(e)})
        
        # Import education levels
        for e in data.get("education_levels", []):
            try:
                existing = kb.get_education_by_name(e["name"])
                if existing and skip_existing:
                    result["education_levels"]["skipped"] += 1
                    continue
                
                if not dry_run:
                    edu = schemas.EducationLevelCreate(
                        name=e["name"],
                        hierarchy_level=e["hierarchy_level"],
                        description=e.get("description"),
                    )
                    kb.create_education_level(edu)
                result["education_levels"]["success"] += 1
            except Exception as e:
                result["education_levels"]["errors"].append({"name": e.get("name"), "error": str(e)})
        
        # Import skills
        for s in data.get("skills", []):
            try:
                existing = kb.get_skill_by_name(s["name"])
                if existing and skip_existing:
                    result["skills"]["skipped"] += 1
                    continue
                
                if not dry_run:
                    skill = schemas.SkillCreate(
                        name=s["name"],
                        code=s.get("code"),
                        category=s.get("category", "technical"),
                        description=s.get("description"),
                    )
                    kb.create_skill(skill)
                result["skills"]["success"] += 1
            except Exception as e:
                result["skills"]["errors"].append({"name": s.get("name"), "error": str(e)})
        
        # Import careers (more complex due to relationships)
        for c in data.get("careers", []):
            try:
                existing = kb.get_career_by_name(c["name"])
                if existing and skip_existing:
                    result["careers"]["skipped"] += 1
                    continue
                
                if not dry_run:
                    # Build skills
                    career_skills = []
                    for cs in c.get("skills", []):
                        career_skills.append(schemas.CareerSkillCreate(
                            skill_id=cs["skill_id"],
                            requirement_type=cs["requirement_type"],
                            proficiency_level=cs.get("proficiency_level", "intermediate"),
                        ))
                    
                    # Build roadmaps
                    roadmaps = []
                    for r in c.get("roadmaps", []):
                        roadmaps.append(schemas.RoadmapCreate(
                            title=r["title"],
                            description=r.get("description"),
                            level=r.get("level"),
                            step_order=r.get("step_order", 1),
                            duration_months=r.get("duration_months"),
                        ))
                    
                    career = schemas.CareerCreate(
                        name=c["name"],
                        slug=c.get("slug"),
                        domain_id=c["domain_id"],
                        description=c.get("description"),
                        icon=c.get("icon"),
                        education_min=c.get("education_min"),
                        ai_relevance=c.get("ai_relevance", 0.5),
                        competition=c.get("competition", 0.5),
                        growth_rate=c.get("growth_rate", 0.5),
                        skills=career_skills,
                        roadmaps=roadmaps,
                    )
                    kb.create_career(career)
                result["careers"]["success"] += 1
            except Exception as e:
                result["careers"]["errors"].append({"name": c.get("name"), "error": str(e)})
        
        # Import templates
        for t in data.get("templates", []):
            try:
                existing = kb.get_template_by_code(t["code"]) if hasattr(kb, "get_template_by_code") else None
                if existing and skip_existing:
                    result["templates"]["skipped"] += 1
                    continue
                
                if not dry_run and hasattr(kb, "create_template"):
                    template = schemas.TemplateCreate(
                        code=t["code"],
                        type=t["type"],
                        name=t["name"],
                        content=t["content"],
                        variables=t.get("variables", []),
                    )
                    kb.create_template(template)
                result["templates"]["success"] += 1
            except Exception as e:
                result["templates"]["errors"].append({"code": t.get("code"), "error": str(e)})
        
        # Import ontology nodes
        for n in data.get("ontology_nodes", []):
            try:
                existing = kb.get_ontology_by_code(n["code"]) if hasattr(kb, "get_ontology_by_code") else None
                if existing and skip_existing:
                    result["ontology_nodes"]["skipped"] += 1
                    continue
                
                if not dry_run and hasattr(kb, "create_ontology_node"):
                    node = schemas.OntologyNodeCreate(
                        code=n["code"],
                        type=n["type"],
                        label=n["label"],
                        parent_id=n.get("parent_id"),
                        relations=n.get("relations", {}),
                        metadata=n.get("metadata", {}),
                    )
                    kb.create_ontology_node(node)
                result["ontology_nodes"]["success"] += 1
            except Exception as e:
                result["ontology_nodes"]["errors"].append({"code": n.get("code"), "error": str(e)})
    
    # Summary
    total_success = sum(r["success"] for r in result.values() if isinstance(r, dict) and "success" in r)
    total_errors = sum(len(r.get("errors", [])) for r in result.values() if isinstance(r, dict))
    
    logger.info("Import complete: %d success, %d errors", total_success, total_errors)
    
    return result


# ============================
# MIGRATION REPORT
# ============================

def generate_migration_report(output_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Generate a report of current KB state for migration planning.
    """
    logger.info("Generating migration report...")
    
    with get_db_context() as db:
        kb = KnowledgeBaseService(db)
        
        report = {
            "generated_at": datetime.utcnow().isoformat(),
            "summary": {},
            "entity_details": {},
            "version_stats": {},
            "recommendations": [],
        }
        
        # Counts
        report["summary"] = {
            "total_domains": len(kb.list_domains(limit=10000)),
            "total_education_levels": len(kb.list_education_levels()),
            "total_skills": len(kb.list_skills(limit=10000)),
            "total_careers": len(kb.list_careers(limit=10000)),
        }
        
        # Templates & Ontology (if available)
        try:
            report["summary"]["total_templates"] = len(kb.list_templates(limit=10000))
        except:
            report["summary"]["total_templates"] = 0
        
        try:
            report["summary"]["total_ontology_nodes"] = len(kb.list_ontology_nodes(limit=10000))
        except:
            report["summary"]["total_ontology_nodes"] = 0
        
        # Skill categories
        skills = kb.list_skills(limit=10000)
        categories = {}
        for s in skills:
            cat = s.category or "uncategorized"
            categories[cat] = categories.get(cat, 0) + 1
        report["entity_details"]["skill_categories"] = categories
        
        # Careers by domain
        careers = kb.list_careers(limit=10000)
        domains = kb.list_domains(limit=10000)
        domain_map = {d.id: d.name for d in domains}
        careers_by_domain = {}
        for c in careers:
            domain_name = domain_map.get(c.domain_id, "Unknown")
            careers_by_domain[domain_name] = careers_by_domain.get(domain_name, 0) + 1
        report["entity_details"]["careers_by_domain"] = careers_by_domain
        
        # Recommendations
        if report["summary"]["total_templates"] == 0:
            report["recommendations"].append("No templates found - consider adding templates for dynamic content")
        
        if report["summary"]["total_ontology_nodes"] == 0:
            report["recommendations"].append("No ontology nodes found - consider building taxonomy structure")
        
        total = sum(report["summary"].values())
        report["summary"]["total_entities"] = total
        
        # Save if path provided
        if output_path:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            logger.info("Report saved to: %s", path)
        
        return report


# ============================
# CLI
# ============================

if __name__ == "__main__":
    import sys
    
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python -m backend.kb.migration export [output.json]")
        print("  python -m backend.kb.migration import <input.json> [--dry-run]")
        print("  python -m backend.kb.migration report [output.json]")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "export":
        output = sys.argv[2] if len(sys.argv) > 2 else f"kb_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        export_kb_to_json(output)
    
    elif command == "import":
        if len(sys.argv) < 3:
            print("Error: input file required")
            sys.exit(1)
        input_file = sys.argv[2]
        dry_run = "--dry-run" in sys.argv
        result = import_kb_from_json(input_file, dry_run=dry_run)
        print(json.dumps(result, indent=2))
    
    elif command == "report":
        output = sys.argv[2] if len(sys.argv) > 2 else f"kb_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        generate_migration_report(output)
    
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
