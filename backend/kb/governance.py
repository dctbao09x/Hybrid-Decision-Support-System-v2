# backend/kb/governance.py
"""
KB Governance & Validation Rules

Enforces data quality, consistency, and business rules
for Knowledge Base entities.
"""

import re
import logging
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass
from enum import Enum

from backend.kb import schemas


# ============================
# LOGGING
# ============================

logger = logging.getLogger("kb-governance")


# ============================
# ENUMS
# ============================

class ValidationSeverity(str, Enum):
    ERROR = "error"       # Blocks operation
    WARNING = "warning"   # Allows but flags
    INFO = "info"         # Informational only


class GovernanceAction(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    BULK_IMPORT = "bulk_import"


# ============================
# VALIDATION RESULT
# ============================

@dataclass
class ValidationResult:
    """Result of validation check"""
    valid: bool
    severity: ValidationSeverity
    rule_name: str
    message: str
    field: Optional[str] = None
    suggestion: Optional[str] = None


@dataclass
class GovernanceResult:
    """Overall governance check result"""
    passed: bool
    errors: List[ValidationResult]
    warnings: List[ValidationResult]
    info: List[ValidationResult]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "errors": [r.__dict__ for r in self.errors],
            "warnings": [r.__dict__ for r in self.warnings],
            "info": [r.__dict__ for r in self.info],
        }


# ============================
# VALIDATION RULES
# ============================

class ValidationRule:
    """Base class for validation rules"""
    
    name: str = "base_rule"
    severity: ValidationSeverity = ValidationSeverity.ERROR
    entity_types: List[str] = []  # Empty = all
    actions: List[GovernanceAction] = []  # Empty = all
    
    def validate(self, entity_type: str, data: Dict[str, Any], action: GovernanceAction) -> Optional[ValidationResult]:
        """Override in subclass"""
        raise NotImplementedError


# ============================
# CAREER RULES
# ============================

class CareerNameRule(ValidationRule):
    """Career name must be unique and descriptive"""
    
    name = "career_name_format"
    severity = ValidationSeverity.ERROR
    entity_types = ["career"]
    
    def validate(self, entity_type: str, data: Dict, action: GovernanceAction) -> Optional[ValidationResult]:
        name = data.get("name", "")
        
        if not name or len(name) < 3:
            return ValidationResult(
                valid=False,
                severity=self.severity,
                rule_name=self.name,
                message="Career name must be at least 3 characters",
                field="name",
                suggestion="Provide a descriptive career title"
            )
        
        if len(name) > 100:
            return ValidationResult(
                valid=False,
                severity=self.severity,
                rule_name=self.name,
                message="Career name must be under 100 characters",
                field="name"
            )
        
        return None


class CareerCodeRule(ValidationRule):
    """Career code must follow pattern"""
    
    name = "career_code_format"
    severity = ValidationSeverity.WARNING
    entity_types = ["career"]
    
    CODE_PATTERN = re.compile(r"^[A-Z]{2,4}[0-9]{3,4}$")
    
    def validate(self, entity_type: str, data: Dict, action: GovernanceAction) -> Optional[ValidationResult]:
        code = data.get("code")
        
        if code and not self.CODE_PATTERN.match(code):
            return ValidationResult(
                valid=False,
                severity=self.severity,
                rule_name=self.name,
                message=f"Career code '{code}' doesn't match pattern (e.g., DEV001, AI0023)",
                field="code",
                suggestion="Use format: 2-4 uppercase letters + 3-4 digits"
            )
        
        return None


class CareerMetricsRule(ValidationRule):
    """Career metrics must be in valid range"""
    
    name = "career_metrics_range"
    severity = ValidationSeverity.ERROR
    entity_types = ["career"]
    
    METRIC_FIELDS = ["ai_relevance", "competition", "growth_rate"]
    
    def validate(self, entity_type: str, data: Dict, action: GovernanceAction) -> Optional[ValidationResult]:
        for field in self.METRIC_FIELDS:
            value = data.get(field)
            if value is not None:
                if not isinstance(value, (int, float)) or value < 0 or value > 1:
                    return ValidationResult(
                        valid=False,
                        severity=self.severity,
                        rule_name=self.name,
                        message=f"{field} must be between 0.0 and 1.0",
                        field=field,
                        suggestion="Use decimal value like 0.75"
                    )
        return None


class CareerDomainRule(ValidationRule):
    """Career must have valid domain"""
    
    name = "career_domain_required"
    severity = ValidationSeverity.ERROR
    entity_types = ["career"]
    actions = [GovernanceAction.CREATE]
    
    def validate(self, entity_type: str, data: Dict, action: GovernanceAction) -> Optional[ValidationResult]:
        domain_id = data.get("domain_id")
        
        if not domain_id:
            return ValidationResult(
                valid=False,
                severity=self.severity,
                rule_name=self.name,
                message="Career must have a domain_id",
                field="domain_id"
            )
        
        return None


# ============================
# SKILL RULES
# ============================

class SkillNameRule(ValidationRule):
    """Skill name validation"""
    
    name = "skill_name_format"
    severity = ValidationSeverity.ERROR
    entity_types = ["skill"]
    
    def validate(self, entity_type: str, data: Dict, action: GovernanceAction) -> Optional[ValidationResult]:
        name = data.get("name", "")
        
        if not name or len(name) < 2:
            return ValidationResult(
                valid=False,
                severity=self.severity,
                rule_name=self.name,
                message="Skill name must be at least 2 characters",
                field="name"
            )
        
        return None


class SkillCategoryRule(ValidationRule):
    """Skill must have valid category"""
    
    name = "skill_category_valid"
    severity = ValidationSeverity.WARNING
    entity_types = ["skill"]
    
    VALID_CATEGORIES = ["technical", "soft", "domain", "tool", "language", "framework", "other"]
    
    def validate(self, entity_type: str, data: Dict, action: GovernanceAction) -> Optional[ValidationResult]:
        category = data.get("category")
        
        if category and category not in self.VALID_CATEGORIES:
            return ValidationResult(
                valid=False,
                severity=self.severity,
                rule_name=self.name,
                message=f"Unknown skill category: {category}",
                field="category",
                suggestion=f"Use one of: {', '.join(self.VALID_CATEGORIES)}"
            )
        
        return None


# ============================
# TEMPLATE RULES
# ============================

class TemplateCodeRule(ValidationRule):
    """Template code must be unique and follow format"""
    
    name = "template_code_format"
    severity = ValidationSeverity.ERROR
    entity_types = ["template"]
    
    CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,30}$")
    
    def validate(self, entity_type: str, data: Dict, action: GovernanceAction) -> Optional[ValidationResult]:
        code = data.get("code", "")
        
        if not code:
            return ValidationResult(
                valid=False,
                severity=self.severity,
                rule_name=self.name,
                message="Template code is required",
                field="code"
            )
        
        if not self.CODE_PATTERN.match(code):
            return ValidationResult(
                valid=False,
                severity=self.severity,
                rule_name=self.name,
                message="Template code must start with letter, contain only lowercase/numbers/underscores, 3-31 chars",
                field="code",
                suggestion="Example: career_prompt_v1"
            )
        
        return None


class TemplateVariablesRule(ValidationRule):
    """Template variables must be used in content"""
    
    name = "template_variables_usage"
    severity = ValidationSeverity.WARNING
    entity_types = ["template"]
    
    def validate(self, entity_type: str, data: Dict, action: GovernanceAction) -> Optional[ValidationResult]:
        content = data.get("content", "")
        variables = data.get("variables", [])
        
        if not variables:
            return None
        
        unused = []
        for var in variables:
            if f"{{{{{var}}}}}" not in content and f"{{{{ {var} }}}}" not in content:
                # Check common template syntaxes
                patterns = [f"{{{var}}}", f"${{{var}}}", f"<{var}>"]
                if not any(p in content for p in patterns):
                    unused.append(var)
        
        if unused:
            return ValidationResult(
                valid=False,
                severity=self.severity,
                rule_name=self.name,
                message=f"Declared variables not found in content: {', '.join(unused)}",
                field="variables",
                suggestion="Use variables in content as {{variable_name}}"
            )
        
        return None


# ============================
# ONTOLOGY RULES
# ============================

class OntologyCodeRule(ValidationRule):
    """Ontology node code validation"""
    
    name = "ontology_code_format"
    severity = ValidationSeverity.ERROR
    entity_types = ["ontology"]
    
    CODE_PATTERN = re.compile(r"^[A-Z]{2,6}_[A-Z0-9]{2,20}$")
    
    def validate(self, entity_type: str, data: Dict, action: GovernanceAction) -> Optional[ValidationResult]:
        code = data.get("code", "")
        
        if not code:
            return ValidationResult(
                valid=False,
                severity=self.severity,
                rule_name=self.name,
                message="Ontology code is required",
                field="code"
            )
        
        if not self.CODE_PATTERN.match(code):
            return ValidationResult(
                valid=False,
                severity=self.severity,
                rule_name=self.name,
                message="Ontology code must follow pattern: PREFIX_CODE (e.g., DOM_IT, CAT_DEV)",
                field="code"
            )
        
        return None


class OntologyCircularRule(ValidationRule):
    """Prevent circular parent relationships"""
    
    name = "ontology_no_circular"
    severity = ValidationSeverity.ERROR
    entity_types = ["ontology"]
    actions = [GovernanceAction.CREATE, GovernanceAction.UPDATE]
    
    def validate(self, entity_type: str, data: Dict, action: GovernanceAction) -> Optional[ValidationResult]:
        node_id = data.get("node_id")
        parent_id = data.get("parent_id")
        
        if parent_id and node_id and parent_id == node_id:
            return ValidationResult(
                valid=False,
                severity=self.severity,
                rule_name=self.name,
                message="Node cannot be its own parent",
                field="parent_id"
            )
        
        return None


# ============================
# GENERAL RULES
# ============================

class NoEmptyStringsRule(ValidationRule):
    """String fields should not be empty whitespace"""
    
    name = "no_empty_strings"
    severity = ValidationSeverity.WARNING
    
    STRING_FIELDS = ["name", "description", "label", "content"]
    
    def validate(self, entity_type: str, data: Dict, action: GovernanceAction) -> Optional[ValidationResult]:
        for field in self.STRING_FIELDS:
            value = data.get(field)
            if value is not None and isinstance(value, str):
                if value.strip() == "" and value != "":
                    return ValidationResult(
                        valid=False,
                        severity=self.severity,
                        rule_name=self.name,
                        message=f"Field '{field}' contains only whitespace",
                        field=field
                    )
        return None


class DeleteProtectionRule(ValidationRule):
    """Protect critical entities from deletion"""
    
    name = "delete_protection"
    severity = ValidationSeverity.ERROR
    actions = [GovernanceAction.DELETE]
    
    PROTECTED_CODES = ["DEFAULT", "SYSTEM", "ROOT"]
    
    def validate(self, entity_type: str, data: Dict, action: GovernanceAction) -> Optional[ValidationResult]:
        code = data.get("code", "")
        name = data.get("name", "")
        
        if code in self.PROTECTED_CODES or name in self.PROTECTED_CODES:
            return ValidationResult(
                valid=False,
                severity=self.severity,
                rule_name=self.name,
                message=f"Cannot delete protected entity: {code or name}",
                field="code"
            )
        
        return None


# ============================
# GOVERNANCE ENGINE
# ============================

class GovernanceEngine:
    """
    Central governance engine that applies all validation rules.
    """
    
    def __init__(self):
        self.rules: List[ValidationRule] = []
        self._load_default_rules()
    
    def _load_default_rules(self):
        """Load all default validation rules"""
        self.rules = [
            # Career rules
            CareerNameRule(),
            CareerCodeRule(),
            CareerMetricsRule(),
            CareerDomainRule(),
            
            # Skill rules
            SkillNameRule(),
            SkillCategoryRule(),
            
            # Template rules
            TemplateCodeRule(),
            TemplateVariablesRule(),
            
            # Ontology rules
            OntologyCodeRule(),
            OntologyCircularRule(),
            
            # General rules
            NoEmptyStringsRule(),
            DeleteProtectionRule(),
        ]
        logger.info("Loaded %d governance rules", len(self.rules))
    
    def add_rule(self, rule: ValidationRule):
        """Add custom rule"""
        self.rules.append(rule)
    
    def remove_rule(self, rule_name: str):
        """Remove rule by name"""
        self.rules = [r for r in self.rules if r.name != rule_name]
    
    def validate(
        self, 
        entity_type: str, 
        data: Dict[str, Any], 
        action: GovernanceAction
    ) -> GovernanceResult:
        """
        Run all applicable rules against entity data.
        
        Args:
            entity_type: Type of entity (career, skill, template, ontology)
            data: Entity data dict
            action: The action being performed
        
        Returns:
            GovernanceResult with all validation results
        """
        errors = []
        warnings = []
        info = []
        
        for rule in self.rules:
            # Check if rule applies to this entity type
            if rule.entity_types and entity_type not in rule.entity_types:
                continue
            
            # Check if rule applies to this action
            if rule.actions and action not in rule.actions:
                continue
            
            try:
                result = rule.validate(entity_type, data, action)
                
                if result:
                    if result.severity == ValidationSeverity.ERROR:
                        errors.append(result)
                    elif result.severity == ValidationSeverity.WARNING:
                        warnings.append(result)
                    else:
                        info.append(result)
                        
            except Exception as e:
                logger.error("Rule '%s' failed: %s", rule.name, e)
        
        passed = len(errors) == 0
        
        return GovernanceResult(
            passed=passed,
            errors=errors,
            warnings=warnings,
            info=info
        )
    
    def validate_bulk(
        self, 
        entity_type: str, 
        items: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Validate bulk import items.
        
        Returns:
            Dict with validation summary per row
        """
        results = {
            "valid_count": 0,
            "invalid_count": 0,
            "items": []
        }
        
        for idx, item in enumerate(items):
            result = self.validate(entity_type, item, GovernanceAction.BULK_IMPORT)
            
            results["items"].append({
                "row": idx + 1,
                "passed": result.passed,
                "errors": [e.message for e in result.errors],
                "warnings": [w.message for w in result.warnings],
            })
            
            if result.passed:
                results["valid_count"] += 1
            else:
                results["invalid_count"] += 1
        
        return results


# ============================
# SINGLETON INSTANCE
# ============================

governance_engine = GovernanceEngine()


# ============================
# CONVENIENCE FUNCTIONS
# ============================

def validate_career(data: Dict, action: GovernanceAction = GovernanceAction.CREATE) -> GovernanceResult:
    return governance_engine.validate("career", data, action)


def validate_skill(data: Dict, action: GovernanceAction = GovernanceAction.CREATE) -> GovernanceResult:
    return governance_engine.validate("skill", data, action)


def validate_template(data: Dict, action: GovernanceAction = GovernanceAction.CREATE) -> GovernanceResult:
    return governance_engine.validate("template", data, action)


def validate_ontology(data: Dict, action: GovernanceAction = GovernanceAction.CREATE) -> GovernanceResult:
    return governance_engine.validate("ontology", data, action)
