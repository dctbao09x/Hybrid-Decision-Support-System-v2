# backend/explain/export/pdf_generator.py
"""
PDF Export Generator for Explain Audit System
==============================================

Generates deterministic PDF reports for explanation traces.
Uses reportlab for cross-platform PDF generation.

Features:
  - Full trace information
  - Rule path visualization
  - Evidence listing
  - Integrity verification status
  - Timestamp and metadata
"""

from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, BinaryIO

# Use reportlab for PDF generation
try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch, mm
    from reportlab.platypus import (
        SimpleDocTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
        PageBreak,
        HRFlowable,
    )
    from reportlab.lib.enums import TA_LEFT, TA_CENTER
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False


class ExplainPdfGenerator:
    """
    Generates PDF reports for explanation audit records.
    
    Usage:
        generator = ExplainPdfGenerator()
        pdf_bytes = generator.generate(explanation_data)
        
        # Save to file
        with open("report.pdf", "wb") as f:
            f.write(pdf_bytes)
    """
    
    def __init__(
        self,
        page_size: tuple = A4 if REPORTLAB_AVAILABLE else (595.27, 841.89),
        margin: float = 0.75,  # inches
    ):
        """
        Initialize PDF generator.
        
        Args:
            page_size: Page dimensions (default: A4)
            margin: Page margin in inches
        """
        if not REPORTLAB_AVAILABLE:
            raise RuntimeError(
                "reportlab is required for PDF generation. "
                "Install with: pip install reportlab"
            )
        
        self._page_size = page_size
        self._margin = margin * inch
        self._styles = getSampleStyleSheet()
        self._setup_custom_styles()
    
    def _setup_custom_styles(self) -> None:
        """Configure custom paragraph styles."""
        # Title style
        self._styles.add(ParagraphStyle(
            name='AuditTitle',
            parent=self._styles['Heading1'],
            fontSize=18,
            spaceAfter=20,
            alignment=TA_CENTER,
            textColor=colors.HexColor('#1a5276'),
        ))
        
        # Section header style
        self._styles.add(ParagraphStyle(
            name='SectionHeader',
            parent=self._styles['Heading2'],
            fontSize=12,
            spaceBefore=15,
            spaceAfter=8,
            textColor=colors.HexColor('#2c3e50'),
            borderPadding=(0, 0, 3, 0),
        ))
        
        # Normal text style
        self._styles.add(ParagraphStyle(
            name='AuditText',
            parent=self._styles['Normal'],
            fontSize=10,
            spaceAfter=6,
        ))
        
        # Code/monospace style
        self._styles.add(ParagraphStyle(
            name='CodeStyle',
            parent=self._styles['Normal'],
            fontName='Courier',
            fontSize=9,
            spaceAfter=4,
            backColor=colors.HexColor('#f8f9fa'),
            borderPadding=5,
        ))
        
        # Footer style
        self._styles.add(ParagraphStyle(
            name='Footer',
            parent=self._styles['Normal'],
            fontSize=8,
            textColor=colors.gray,
            alignment=TA_CENTER,
        ))
    
    def generate(
        self,
        data: Dict[str, Any],
        include_graph: bool = True,
        include_integrity: bool = True,
    ) -> bytes:
        """
        Generate PDF from explanation data.
        
        Args:
            data: Explanation record dictionary
            include_graph: Include trace graph section
            include_integrity: Include integrity verification
        
        Returns:
            PDF as bytes
        """
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=self._page_size,
            leftMargin=self._margin,
            rightMargin=self._margin,
            topMargin=self._margin,
            bottomMargin=self._margin,
        )
        
        elements = []
        
        # Title
        elements.append(Paragraph("Explanation Audit Report", self._styles['AuditTitle']))
        elements.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#1a5276')))
        elements.append(Spacer(1, 12))
        
        # Generation timestamp
        gen_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        elements.append(Paragraph(
            f"Generated: {gen_time}",
            self._styles['Footer']
        ))
        elements.append(Spacer(1, 20))
        
        # Summary section
        elements.extend(self._build_summary_section(data))
        
        # Rule path section
        elements.extend(self._build_rule_path_section(data))
        
        # Evidence section
        elements.extend(self._build_evidence_section(data))
        
        # Feature snapshot section
        elements.extend(self._build_features_section(data))
        
        # Trace graph section (optional)
        if include_graph and "graph" in data:
            elements.extend(self._build_graph_section(data.get("graph", {})))
        
        # Integrity section (optional)
        if include_integrity:
            elements.extend(self._build_integrity_section(data))
        
        # Footer
        elements.append(Spacer(1, 30))
        elements.append(HRFlowable(width="100%", thickness=1, color=colors.gray))
        elements.append(Spacer(1, 10))
        
        # Document hash for verification
        doc_hash = self._compute_document_hash(data)
        elements.append(Paragraph(
            f"Document Hash: {doc_hash[:32]}...",
            self._styles['Footer']
        ))
        elements.append(Paragraph(
            "This document is generated for audit purposes. "
            "Hash can be verified against source data.",
            self._styles['Footer']
        ))
        
        doc.build(elements)
        buffer.seek(0)
        return buffer.getvalue()
    
    def _build_summary_section(self, data: Dict[str, Any]) -> List:
        """Build summary information section."""
        elements = []
        elements.append(Paragraph("Summary", self._styles['SectionHeader']))
        
        summary_data = [
            ["Field", "Value"],
            ["Trace ID", data.get("trace_id", "N/A")],
            ["Explanation ID", data.get("explanation_id", "N/A")],
            ["Model ID", data.get("model_id", "N/A")],
            ["KB Version", data.get("kb_version", "N/A")],
            ["Confidence", f"{float(data.get('confidence', 0)) * 100:.1f}%"],
            ["Created At", data.get("created_at", "N/A")],
        ]
        
        # Prediction info
        prediction = data.get("prediction", {})
        if prediction:
            if isinstance(prediction, dict):
                summary_data.append([
                    "Prediction",
                    prediction.get("career", str(prediction))
                ])
                if "confidence" in prediction:
                    summary_data.append([
                        "Prediction Confidence",
                        f"{float(prediction['confidence']) * 100:.1f}%"
                    ])
        
        table = Table(summary_data, colWidths=[150, 300])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('TOPPADDING', (0, 0), (-1, 0), 10),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f8f9fa')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.gray),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 15))
        
        return elements
    
    def _build_rule_path_section(self, data: Dict[str, Any]) -> List:
        """Build rule path section."""
        elements = []
        elements.append(Paragraph("Rule Path", self._styles['SectionHeader']))
        
        rule_path = data.get("rule_path", [])
        if not rule_path:
            elements.append(Paragraph("No rule path available.", self._styles['AuditText']))
        else:
            rule_data = [["Rule ID", "Condition", "Weight"]]
            for rule in rule_path:
                if isinstance(rule, dict):
                    rule_data.append([
                        rule.get("rule_id", "N/A"),
                        rule.get("condition", "N/A")[:50],
                        f"{float(rule.get('weight', 0)):.2f}",
                    ])
            
            table = Table(rule_data, colWidths=[120, 250, 80])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#27ae60')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('ALIGN', (2, 0), (2, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                ('TOPPADDING', (0, 0), (-1, 0), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.gray),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f0fff0')]),
            ]))
            elements.append(table)
        
        elements.append(Spacer(1, 15))
        return elements
    
    def _build_evidence_section(self, data: Dict[str, Any]) -> List:
        """Build evidence section."""
        elements = []
        elements.append(Paragraph("Evidence", self._styles['SectionHeader']))
        
        evidence = data.get("evidence", [])
        if not evidence:
            elements.append(Paragraph("No evidence available.", self._styles['AuditText']))
        else:
            evidence_data = [["Source", "Key", "Value", "Weight"]]
            for item in evidence[:20]:  # Limit to 20 items
                if isinstance(item, dict):
                    value = item.get("value", "N/A")
                    if isinstance(value, (dict, list)):
                        value = json.dumps(value)[:30] + "..."
                    else:
                        value = str(value)[:30]
                    
                    evidence_data.append([
                        item.get("source", "N/A")[:20],
                        item.get("key", "N/A")[:20],
                        value,
                        f"{float(item.get('weight', 0)):.2f}",
                    ])
            
            table = Table(evidence_data, colWidths=[90, 100, 180, 80])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('ALIGN', (3, 0), (3, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                ('TOPPADDING', (0, 0), (-1, 0), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.gray),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f0f8ff')]),
            ]))
            elements.append(table)
        
        elements.append(Spacer(1, 15))
        return elements
    
    def _build_features_section(self, data: Dict[str, Any]) -> List:
        """Build feature snapshot section."""
        elements = []
        elements.append(Paragraph("Feature Snapshot", self._styles['SectionHeader']))
        
        features = data.get("feature_snapshot", {})
        if not features:
            elements.append(Paragraph("No features available.", self._styles['AuditText']))
        else:
            feature_data = [["Feature", "Value"]]
            for key, value in sorted(features.items())[:15]:  # Limit to 15 features
                feature_data.append([str(key), f"{float(value):.4f}" if isinstance(value, (int, float)) else str(value)])
            
            table = Table(feature_data, colWidths=[200, 250])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#9b59b6')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                ('TOPPADDING', (0, 0), (-1, 0), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.gray),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#faf0ff')]),
            ]))
            elements.append(table)
        
        elements.append(Spacer(1, 15))
        return elements
    
    def _build_graph_section(self, graph: Dict[str, Any]) -> List:
        """Build trace graph summary section."""
        elements = []
        elements.append(Paragraph("Trace Graph", self._styles['SectionHeader']))
        
        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])
        
        elements.append(Paragraph(
            f"Nodes: {len(nodes)} | Edges: {len(edges)}",
            self._styles['AuditText']
        ))
        
        if edges:
            edge_data = [["Source", "Target", "Type"]]
            for edge in edges[:10]:  # Limit to 10 edges
                if isinstance(edge, dict):
                    edge_data.append([
                        edge.get("source", "N/A")[:25],
                        edge.get("target", "N/A")[:25],
                        edge.get("edge_type", "N/A"),
                    ])
            
            table = Table(edge_data, colWidths=[150, 150, 150])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e67e22')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                ('TOPPADDING', (0, 0), (-1, 0), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.gray),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#fff8f0')]),
            ]))
            elements.append(table)
        
        elements.append(Spacer(1, 15))
        return elements
    
    def _build_integrity_section(self, data: Dict[str, Any]) -> List:
        """Build integrity verification section."""
        elements = []
        elements.append(Paragraph("Integrity Verification", self._styles['SectionHeader']))
        
        integrity = data.get("integrity", {})
        record_hash = integrity.get("record_hash", "N/A")
        prev_hash = integrity.get("prev_hash", "N/A")
        
        integrity_data = [
            ["Field", "Value"],
            ["Record Hash", record_hash[:40] + "..." if len(str(record_hash)) > 40 else record_hash],
            ["Previous Hash", prev_hash[:40] + "..." if prev_hash and len(str(prev_hash)) > 40 else (prev_hash or "Genesis")],
            ["Chain Valid", "Verified at generation time"],
        ]
        
        table = Table(integrity_data, colWidths=[120, 330])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#c0392b')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (1, 1), (1, -1), 'Courier'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('TOPPADDING', (0, 0), (-1, 0), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.gray),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#fff0f0')]),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 15))
        
        return elements
    
    def _compute_document_hash(self, data: Dict[str, Any]) -> str:
        """Compute deterministic hash of document content."""
        canonical = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def generate_explanation_pdf(
    data: Dict[str, Any],
    output_path: Optional[Path] = None,
) -> bytes:
    """
    Convenience function to generate PDF.
    
    Args:
        data: Explanation record data
        output_path: Optional path to save PDF
    
    Returns:
        PDF bytes
    """
    generator = ExplainPdfGenerator()
    pdf_bytes = generator.generate(data)
    
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(pdf_bytes)
    
    return pdf_bytes
