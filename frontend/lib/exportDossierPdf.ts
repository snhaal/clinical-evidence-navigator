import { jsPDF } from "jspdf";
import autoTable from "jspdf-autotable";
import type { DossierData, TrialMatchSummary, Verdict } from "./types";

export type { DossierData };

// Color constants matching the application's Tailwind design tokens
const COLOR_INK = [27, 31, 29] as const; // #1B1F1D
const COLOR_MUTED = [91, 102, 96] as const; // #5B6660
const COLOR_BORDER = [226, 229, 226] as const; // #E2E5E2
const COLOR_ACCENT = [47, 111, 98] as const; // #2F6F62
const COLOR_BG_SOFT = [247, 248, 247] as const; // #F7F8F7

// Verdict color coding (text and soft background fill)
const VERDICT_COLORS = {
  match: {
    text: [47, 111, 98] as [number, number, number], // #2F6F62 (MET / green)
    fill: [230, 238, 236] as [number, number, number], // #E6EEEC
    label: "MET",
  },
  no_match: {
    text: [162, 59, 59] as [number, number, number], // #A23B3B (NOT MET / red)
    fill: [245, 233, 233] as [number, number, number], // #F5E9E9
    label: "NOT MET",
  },
  unclear: {
    text: [147, 112, 30] as [number, number, number], // #93701E (UNCLEAR / amber)
    fill: [245, 238, 221] as [number, number, number], // #F5EEDD
    label: "UNCLEAR",
  },
} as const;

/**
 * Normalizes and sanitizes text for jsPDF standard font rendering.
 * Replaces non-Latin1 / problematic Unicode characters before rendering:
 * - >=, <=, +/-, x, superscripts (e.g. 10^9), standard quotes, dashes,
 * and strips zero-width spaces.
 */
export function cleanPdfText(text: string | null | undefined): string {
  if (!text) return "";

  return (
    text
      // Zero-width spaces (\u200B-\u200D, \uFEFF) -> stripped
      .replace(/[\u200B-\u200D\uFEFF]/g, "")
      // Comparison & Math symbols
      .replace(/≥/g, ">=")
      .replace(/≤/g, "<=")
      .replace(/±/g, "+/-")
      .replace(/×/g, "x")
      .replace(/÷/g, "/")
      .replace(/≠/g, "!=")
      .replace(/≈/g, "~")
      // Superscripts (e.g., 10⁹ -> 10^9, 109 superscripts, etc.)
      .replace(/10[⁹9]/g, "10^9")
      .replace(/⁰/g, "^0")
      .replace(/¹/g, "^1")
      .replace(/²/g, "^2")
      .replace(/³/g, "^3")
      .replace(/⁴/g, "^4")
      .replace(/⁵/g, "^5")
      .replace(/⁶/g, "^6")
      .replace(/⁷/g, "^7")
      .replace(/⁸/g, "^8")
      .replace(/⁹/g, "^9")
      // Micro / units
      .replace(/[μµ]/g, "u")
      // Curly quotes “”‘’ -> standard quotes "'
      .replace(/[“”„‟]/g, '"')
      .replace(/[‘’‚‛]/g, "'")
      // En/em dashes –— -> -
      .replace(/[–—―‒]/g, "-")
      // Ellipsis
      .replace(/…/g, "...")
      // Middle dots or bullet points if any
      .replace(/[•·]/g, "-")
  );
}

function formatVerdictLabel(verdict: Verdict): string {
  return VERDICT_COLORS[verdict]?.label ?? verdict.toUpperCase();
}

function formatStatus(trial: TrialMatchSummary): string {
  if (trial.status) return cleanPdfText(trial.status.replace(/_/g, " "));
  if (trial.overall_verdict === "match") return "Match";
  if (trial.overall_verdict === "no_match") {
    return trial.hard_exclusion_hit ? "Excluded" : "No match";
  }
  return "Unclear";
}

function formatPhase(phase?: string[] | string): string {
  if (!phase) return "N/A";
  if (Array.isArray(phase)) return phase.length > 0 ? phase.join(", ") : "N/A";
  return cleanPdfText(phase);
}

/**
 * Generates a clean, multi-page clinical trial dossier PDF report.
 * Includes header, patient summary block, rankings overview table,
 * detailed per-trial criterion verdicts with verbatim citations,
 * and running footers with confidentiality notice and page numbers.
 */
export async function generateClinicalDossier(data: DossierData): Promise<jsPDF> {
  const doc = new jsPDF({
    orientation: "portrait",
    unit: "mm",
    format: "a4",
  });

  const pageWidth = doc.internal.pageSize.getWidth();
  const pageHeight = doc.internal.pageSize.getHeight();
  const marginX = 14;
  const contentWidth = pageWidth - marginX * 2; // 182mm

  // Explicit table margins for every autoTable invocation to prevent footer collisions
  const tableMargin = { top: 40, bottom: 50, left: marginX, right: marginX };

  // --------------------------------------------------------------------------
  // 1. Header
  // --------------------------------------------------------------------------
  let currentY = 18;

  doc.setFont("helvetica", "bold");
  doc.setFontSize(18);
  doc.setTextColor(...COLOR_INK);
  doc.text("Clinical Evidence Dossier", marginX, currentY);

  currentY += 5;
  doc.setFont("helvetica", "normal");
  doc.setFontSize(9);
  doc.setTextColor(...COLOR_MUTED);
  doc.text("Patient-to-Trial Match & Criterion Verification Report", marginX, currentY);

  const timestamp = new Date().toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
  doc.text(`Generated: ${cleanPdfText(timestamp)}`, pageWidth - marginX, currentY, { align: "right" });

  currentY += 4;
  doc.setDrawColor(...COLOR_BORDER);
  doc.setLineWidth(0.5);
  doc.line(marginX, currentY, pageWidth - marginX, currentY);

  currentY += 6;

  // --------------------------------------------------------------------------
  // 2. Patient Summary (Two-column metadata block)
  // --------------------------------------------------------------------------
  doc.setFont("helvetica", "bold");
  doc.setFontSize(11);
  doc.setTextColor(...COLOR_INK);
  doc.text("Patient Summary", marginX, currentY);
  currentY += 2;

  const sq = data.structured_query;
  const demographicsParts: string[] = [];
  if (sq?.age != null) demographicsParts.push(`${sq.age} yo`);
  if (sq?.sex) demographicsParts.push(sq.sex);
  const demographicsStr = demographicsParts.length > 0 ? demographicsParts.join(", ") : "Not specified";

  const patientSummaryBody = [
    [
      "Patient ID",
      cleanPdfText(data.patient_profile_id || "N/A"),
      "Demographics",
      cleanPdfText(demographicsStr),
    ],
    [
      "Primary Condition",
      cleanPdfText(sq?.condition || "Not specified"),
      "Key Biomarkers",
      cleanPdfText(sq?.biomarkers?.length ? sq.biomarkers.join(", ") : "None reported"),
    ],
    [
      "Disease Stage",
      cleanPdfText(sq?.stage || "Not specified"),
      "Prior Therapies",
      cleanPdfText(sq?.prior_therapy?.length ? sq.prior_therapy.join(", ") : "None reported"),
    ],
  ];

  if (sq?.exclusions?.length) {
    patientSummaryBody.push([
      "Status Filter",
      cleanPdfText(sq.status_filter || "RECRUITING"),
      "Stated Exclusions",
      cleanPdfText(sq.exclusions.join(", ")),
    ]);
  }

  autoTable(doc, {
    startY: currentY,
    theme: "plain",
    styles: {
      font: "helvetica",
      fontSize: 8.5,
      cellPadding: 2.5,
      textColor: [...COLOR_INK],
      valign: "top",
    },
    columnStyles: {
      0: { fontStyle: "bold", cellWidth: 32, textColor: [...COLOR_MUTED], valign: "top" },
      1: { cellWidth: 59, valign: "top" },
      2: { fontStyle: "bold", cellWidth: 32, textColor: [...COLOR_MUTED], valign: "top" },
      3: { cellWidth: 59, valign: "top" },
    },
    body: patientSummaryBody,
    margin: tableMargin,
    tableLineColor: [...COLOR_BORDER],
    tableLineWidth: 0.2,
  });

  // --------------------------------------------------------------------------
  // 3. Candidate Rankings Table
  // --------------------------------------------------------------------------
  const prevTable = (doc as unknown as { lastAutoTable?: { finalY: number } }).lastAutoTable;
  currentY = (prevTable?.finalY ?? currentY) + 8;

  doc.setFont("helvetica", "bold");
  doc.setFontSize(11);
  doc.setTextColor(...COLOR_INK);
  doc.text("Candidate Trial Rankings", marginX, currentY);

  const rankingsBody = (data.trials ?? []).map((trial) => {
    const totalCriteria = trial.criterion_verdicts?.length ?? 0;
    const scorePct =
      totalCriteria > 0
        ? `${Math.round((trial.satisfied_count / totalCriteria) * 100)}%`
        : "N/A";
    const scoreFormatted =
      totalCriteria > 0
        ? `${scorePct} (${trial.satisfied_count}/${totalCriteria})`
        : "N/A";

    return [
      cleanPdfText(trial.nct_id),
      cleanPdfText(trial.title),
      formatPhase(trial.phase),
      cleanPdfText(scoreFormatted),
      formatStatus(trial),
    ];
  });

  autoTable(doc, {
    startY: currentY + 3,
    head: [["NCT ID", "Title", "Phase", "Match Score %", "Status"]],
    body: rankingsBody.length > 0 ? rankingsBody : [["-", "No trials found", "-", "-", "-"]],
    theme: "grid",
    headStyles: {
      fillColor: [...COLOR_ACCENT],
      textColor: [255, 255, 255],
      fontStyle: "bold",
      fontSize: 8.5,
    },
    styles: {
      font: "helvetica",
      fontSize: 8,
      cellPadding: 3,
      textColor: [...COLOR_INK],
      lineColor: [...COLOR_BORDER],
      lineWidth: 0.2,
      valign: "top",
    },
    columnStyles: {
      0: { cellWidth: 26, fontStyle: "bold", valign: "top" },
      1: { cellWidth: 80, valign: "top" },
      2: { cellWidth: 20, halign: "center", valign: "top" },
      3: { cellWidth: 28, halign: "center", valign: "top" },
      4: { cellWidth: 28, halign: "center", valign: "top" },
    },
    margin: tableMargin,
  });

  // --------------------------------------------------------------------------
  // 4. Detailed Verdicts & Citations
  // --------------------------------------------------------------------------
  const trialsList = data.trials ?? [];
  if (trialsList.length > 0) {
    const rankingsTable = (doc as unknown as { lastAutoTable?: { finalY: number } }).lastAutoTable;
    currentY = (rankingsTable?.finalY ?? currentY) + 10;

    // Check if we need a page break before starting detailed verdicts
    if (currentY > pageHeight - 130) {
      doc.addPage();
      currentY = 45;
    }

    doc.setFont("helvetica", "bold");
    doc.setFontSize(12);
    doc.setTextColor(...COLOR_INK);
    doc.text("Detailed Criterion Verdicts & Verbatim Citations", marginX, currentY);

    currentY += 7;

    trialsList.forEach((trial, trialIndex) => {
      if (trialIndex > 0) {
        const lastTable = (doc as unknown as { lastAutoTable?: { finalY: number } }).lastAutoTable;
        currentY = (lastTable?.finalY ?? currentY) + 8;
      }

      // Orphan study header prevention: evaluate remaining vertical height against pageHeight - 130
      if (currentY > pageHeight - 130) {
        doc.addPage();
        currentY = 45;
      }

      // Trial Section Subheader
      doc.setFont("helvetica", "bold");
      doc.setFontSize(9.5);
      doc.setTextColor(...COLOR_ACCENT);
      const trialHeading = cleanPdfText(`Study ${trialIndex + 1}: ${trial.nct_id} - ${trial.title}`);
      const splitTitle = doc.splitTextToSize(trialHeading, contentWidth);
      doc.text(splitTitle, marginX, currentY);

      currentY += splitTitle.length * 4.5 + 2.5;

      // Detailed criteria table rows with clean Column 0 formatting and top alignment
      const criteriaRows = (trial.criterion_verdicts ?? []).map((crit) => {
        const typeLabel =
          crit.criterion_type === "inclusion" ? "Inclusion" : "Exclusion";
        const rationaleText = cleanPdfText(crit.rationale || "None");
        const criterionCol = `${typeLabel} #${crit.criterion_index + 1}\n\nRationale:\n${rationaleText}`;
        const verdictCol = cleanPdfText(formatVerdictLabel(crit.verdict));
        let citationCol = `"${cleanPdfText(crit.cited_text || "No quote provided")}"`;
        if (!crit.citation_validated) {
          citationCol += "\n\n[Warning: Unverified against trial protocol]";
        }
        return [criterionCol, verdictCol, citationCol];
      });

      autoTable(doc, {
        startY: currentY,
        head: [["Criterion", "Verdict", "Verbatim Evidence Citation"]],
        body:
          criteriaRows.length > 0
            ? criteriaRows
            : [["No individual criteria evaluated", "UNCLEAR", "N/A"]],
        theme: "grid",
        showHead: "everyPage",
        rowPageBreak: "avoid",
        headStyles: {
          fillColor: [...COLOR_BG_SOFT],
          textColor: [...COLOR_INK],
          fontStyle: "bold",
          fontSize: 8,
          lineWidth: 0.2,
          lineColor: [...COLOR_BORDER],
        },
        styles: {
          font: "helvetica",
          fontSize: 7.5,
          cellPadding: 3,
          overflow: "linebreak",
          textColor: [...COLOR_INK],
          lineColor: [...COLOR_BORDER],
          lineWidth: 0.2,
          valign: "top",
        },
        columnStyles: {
          0: { cellWidth: 48, valign: "top" },
          1: { cellWidth: 24, halign: "center", valign: "top" },
          2: { cellWidth: 110, valign: "top" },
        },
        didParseCell: (hookData) => {
          if (hookData.section === "body" && hookData.column.index === 1) {
            const raw = String(hookData.cell.raw).toUpperCase();
            if (raw.includes("NOT") || raw.includes("NO_MATCH")) {
              hookData.cell.styles.fillColor = [...VERDICT_COLORS.no_match.fill];
              hookData.cell.styles.textColor = [...VERDICT_COLORS.no_match.text];
              hookData.cell.styles.fontStyle = "bold";
            } else if (raw.includes("MET") || raw.includes("MATCH")) {
              hookData.cell.styles.fillColor = [...VERDICT_COLORS.match.fill];
              hookData.cell.styles.textColor = [...VERDICT_COLORS.match.text];
              hookData.cell.styles.fontStyle = "bold";
            } else {
              hookData.cell.styles.fillColor = [...VERDICT_COLORS.unclear.fill];
              hookData.cell.styles.textColor = [...VERDICT_COLORS.unclear.text];
              hookData.cell.styles.fontStyle = "bold";
            }
          }
        },
        margin: tableMargin,
      });
    });
  }

  // --------------------------------------------------------------------------
  // 5. Running Footer Across All Pages
  // --------------------------------------------------------------------------
  const totalPages = doc.getNumberOfPages();
  for (let i = 1; i <= totalPages; i++) {
    doc.setPage(i);

    // Divider line above footer
    doc.setDrawColor(...COLOR_BORDER);
    doc.setLineWidth(0.3);
    doc.line(marginX, pageHeight - 14, pageWidth - marginX, pageHeight - 14);

    // Footer text
    doc.setFont("helvetica", "normal");
    doc.setFontSize(7.5);
    doc.setTextColor(...COLOR_MUTED);

    const disclaimerText =
      "CONFIDENTIAL - FOR RESEARCH USE ONLY - NOT A SUBSTITUTE FOR CLINICAL JUDGMENT";
    doc.text(disclaimerText, marginX, pageHeight - 9);
    doc.text(`Page ${i} of ${totalPages}`, pageWidth - marginX, pageHeight - 9, {
      align: "right",
    });
  }

  // Save the document client-side if running in the browser
  const filename = `clinical-dossier-${(data.patient_profile_id || "report").slice(0, 8)}-${new Date().toISOString().slice(0, 10)}.pdf`;
  if (typeof window !== "undefined") {
    doc.save(filename);
  }

  return doc;
}
