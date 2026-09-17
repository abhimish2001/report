"""
pdf_exporter.py
Generates a polished, multi-page executive PDF report using ReportLab:
- Report Header & KPI Summary
- AI Executive Summary & Key Recommendations
- Work-Type Utilization Table
- Resource-wise Performance & Variance Table
- Overload & Attention Points
"""

from __future__ import annotations
import os
from typing import Any, Dict, List
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def generate_pdf_report(
    aggregates: Dict[str, Any],
    variance_data: Dict[str, Any],
    ai_insights: Dict[str, Any],
    output_path: str
) -> str:
    """
    Renders the executive report to a professional PDF file using ReportLab.
    """
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()

    # Custom typography styles
    title_style = ParagraphStyle(
        'RepTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=colors.HexColor('#0F172A')
    )
    subtitle_style = ParagraphStyle(
        'RepSub',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#64748B')
    )
    section_title = ParagraphStyle(
        'SecTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor('#1E3A8A'),
        spaceBefore=12,
        spaceAfter=6
    )
    body_style = ParagraphStyle(
        'BodyDark',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#1E293B')
    )
    bullet_style = ParagraphStyle(
        'BulletDark',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#1E293B'),
        leftIndent=12,
        spaceAfter=3
    )
    kpi_label = ParagraphStyle(
        'KPILbl',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        alignment=1,
        textColor=colors.HexColor('#64748B')
    )
    kpi_val = ParagraphStyle(
        'KPIVal',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=16,
        leading=18,
        alignment=1,
        textColor=colors.HexColor('#0F172A')
    )

    story: List[Any] = []

    # Title & Metadata
    month_lbl = aggregates.get("month_label", "August 2026")
    period_lbl = aggregates.get("period_label", "August 2026")

    story.append(Paragraph("Team Resource Utilization Report", title_style))
    story.append(Paragraph(f"Reporting Period: <b>{period_lbl}</b> &nbsp;|&nbsp; Generated via Automated Pipeline", subtitle_style))
    story.append(Spacer(1, 10))

    # KPI Banner Cards
    totals = aggregates.get("totals", {})
    t_tasks = totals.get("tasks", 0)
    t_exp = totals.get("expected_hrs", 0.0)
    t_act = totals.get("actual_hrs", 0.0)
    t_var = totals.get("variance", 0.0)
    t_util = totals.get("utilization_pct", 0.0)

    var_color = "#B91C1C" if t_var > 0 else "#15803D"
    var_sign = f"+{t_var}" if t_var > 0 else str(t_var)

    kpi_cells = [
        [
            Paragraph("TOTAL TASKS", kpi_label),
            Paragraph("EXPECTED HRS", kpi_label),
            Paragraph("ACTUAL HRS", kpi_label),
            Paragraph("NET VARIANCE", kpi_label),
            Paragraph("UTILIZATION", kpi_label)
        ],
        [
            Paragraph(f"{t_tasks}", kpi_val),
            Paragraph(f"{t_exp:,.1f}", kpi_val),
            Paragraph(f"{t_act:,.1f}", kpi_val),
            Paragraph(f"<font color='{var_color}'>{var_sign}h</font>", kpi_val),
            Paragraph(f"{t_util}%", kpi_val)
        ]
    ]

    kpi_table = Table(kpi_cells, colWidths=[108, 108, 108, 108, 108])
    kpi_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8FAFC')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#E2E8F0')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(kpi_table)
    story.append(Spacer(1, 12))

    # Executive Summary & AI Insights Box
    story.append(Paragraph("Executive Narrative & AI Insights", section_title))
    exec_p = ai_insights.get("executive_summary", "")
    story.append(Paragraph(exec_p, body_style))
    story.append(Spacer(1, 6))

    findings = ai_insights.get("key_findings", [])
    if findings:
        story.append(Paragraph("<b>Key Governance Findings:</b>", body_style))
        for f in findings:
            story.append(Paragraph(f"• {f}", bullet_style))
        story.append(Spacer(1, 6))

    recs = ai_insights.get("recommendations", [])
    if recs:
        story.append(Paragraph("<b>Strategic Recommendations:</b>", body_style))
        for r in recs:
            story.append(Paragraph(f"• {r}", bullet_style))
        story.append(Spacer(1, 10))

    # Table 1: Work-Type-wise Resource Utilization
    story.append(Paragraph("Work-Type-wise Resource Utilization", section_title))
    wt_data = [["Work Type", "Tasks", "Expected (h)", "Actual (h)", "Share %", "Variance (h)"]]
    for wt in aggregates.get("by_work_type", []):
        wt_data.append([
            wt["work_type"],
            str(wt["tasks"]),
            f"{wt['expected_hrs']:.1f}",
            f"{wt['actual_hrs']:.1f}",
            f"{wt['share_pct']:.1f}%",
            f"{'+' if wt['variance'] > 0 else ''}{wt['variance']:.1f}"
        ])
    # Add Total Row
    wt_data.append([
        "Total",
        str(t_tasks),
        f"{t_exp:.1f}",
        f"{t_act:.1f}",
        "100.0%",
        f"{'+' if t_var > 0 else ''}{t_var:.1f}"
    ])

    wt_table = Table(wt_data, colWidths=[150, 65, 80, 80, 75, 90])
    wt_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E3A8A')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#F8FAFC')]),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#E2E8F0')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(wt_table)
    story.append(Spacer(1, 14))

    # Page Break for clean multi-page presentation
    story.append(PageBreak())

    # Table 2: Resource-wise Utilization
    story.append(Paragraph("Resource-wise Resource Utilization", section_title))
    emp_data = [["Resource Name", "Tasks", "Expected", "Actual", "Variance", "Util %", "Done", "WIP", "Wait"]]
    for emp in aggregates.get("by_employee", []):
        st = emp.get("status_counts", {})
        emp_data.append([
            emp["employee"],
            str(emp["tasks"]),
            f"{emp['expected_hrs']:.1f}",
            f"{emp['actual_hrs']:.1f}",
            f"{'+' if emp['variance'] > 0 else ''}{emp['variance']:.1f}",
            f"{emp['utilization_pct']:.1f}%",
            str(st.get("Completed", 0)),
            str(st.get("In Progress", 0)),
            str(st.get("Pending", 0))
        ])

    emp_table = Table(emp_data, colWidths=[140, 45, 55, 55, 55, 55, 45, 45, 45])
    emp_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#334155')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8.5),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(emp_table)
    story.append(Spacer(1, 14))

    entity_label = aggregates.get("entity_label", "Service")

    # Table 3: Overloaded Work & Governance Highlights
    story.append(Paragraph("Most Overloaded Work & Governance Highlights", section_title))
    ov_data = [["Category", f"{entity_label} / Resource", "Actual Effort", "Utilization", "Governance Highlight"]]
    for ov in variance_data.get("overloaded_work_table", []):
        ov_data.append([
            ov["category"],
            ov["name"],
            ov["actual_effort"],
            ov["utilization_share"],
            Paragraph(ov["governance_highlight"], body_style)
        ])

    ov_table = Table(ov_data, colWidths=[65, 100, 75, 75, 225])
    ov_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E3A8A')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8.5),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),
        ('ALIGN', (2, 1), (3, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(ov_table)

    # Build PDF
    doc.build(story)
    return os.path.abspath(output_path)
