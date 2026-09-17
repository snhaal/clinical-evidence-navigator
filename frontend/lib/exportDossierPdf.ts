import jsPDF from 'jspdf';
import autoTable, { RowInput } from 'jspdf-autotable';
import { MatchResponse } from './types';

export type DossierData = MatchResponse;

export function cleanClinicalText(input: string | null | undefined): string {
  if (!input) return '';
  let text = String(input);

  // 1. Strip LaTeX delimiters
  text = text.replace(/\$\$([\s\S]*?)\$\$/g, '$1');
  text = text.replace(/\$([^\$]+)\$/g, '$1');

  // 2. Normalize LaTeX commands
  text = text
    .replace(/\\times(?![a-zA-Z])/gi, ' x ')
    .replace(/\\ge(?![a-zA-Z])/gi, ' >= ')
    .replace(/\\le(?![a-zA-Z])/gi, ' <= ')
    .replace(/\\pm(?![a-zA-Z])/gi, ' +/- ')
    .replace(/\\neq(?![a-zA-Z])/gi, ' != ')
    .replace(/\\>/g, '>')
    .replace(/\\</g, '<')
    .replace(/\\%/g, '%')
    .replace(/\\_/g, '_')
    .replace(/\\&/g, '&')
    .replace(/\\#/g, '#')
    .replace(/~/g, ' ')
    .replace(/\^\{\s*([a-zA-Z0-9]+)\s*\}/g, '^$1')
    .replace(/10\^\{\s*n\s*\}\s*(\d+)/gi, '10^$1')
    .replace(/10\^n\s*(\d+)/gi, '10^$1');

  // 3. Normalize Unicode math & superscripts
  text = text
    .replace(/[≥⩾]/g, '>= ')
    .replace(/[≤⩽]/g, ' <= ')
    .replace(/[≠]/g, ' != ')
    .replace(/[±]/g, ' +/- ')
    .replace(/[×✕]/g, ' x ')
    .replace(/[÷]/g, ' / ')
    .replace(/[°]/g, ' deg ')
    .replace(/10[⁹9]/g, '10^9')
    .replace(/10[⁶6]/g, '10^6')
    .replace(/10[³3]/g, '10^3')
    .replace(/[⁰¹²³⁴⁵⁶⁷⁸⁹]/g, (m) => {
      const map: Record<string, string> = { '⁰':'0','¹':'1','²':'2','³':'3','⁴':'4','⁵':'5','⁶':'6','⁷':'7','⁸':'8','⁹':'9' };
      return map[m] || m;
    });

  // 4. Quotes, dashes, hidden characters
  text = text
    .replace(/[\u2018\u2019\u201A\u201B`']/g, "'")
    .replace(/[\u201C\u201D\u201E\u201F\u2033\u2036"«»]/g, '"')
    .replace(/[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]/g, '-')
    .replace(/[\u2022\u2023\u25E6\u2043\u2219]/g, '-')
    .replace(/[\u00A0\u1680\u180E\u2000-\u200A\u202F\u205F\u3000]/g, ' ')
    .replace(/[\u200B-\u200D\uFEFF]/g, '');

  // 5. Enforce space after punctuation for clean line-wrapping
  text = text.replace(/([,;])([^\s0-9])/g, '$1 $2');

  // 6. Guarantee pure printable ASCII
  text = text.replace(/[^\x20-\x7E\n\r\t]/g, '');

  return text.replace(/\s+/g, ' ').trim();
}

export const cleanPdfText = cleanClinicalText;

export function generateClinicalDossier(data: DossierData): void {
  const doc = new jsPDF({
    orientation: 'portrait',
    unit: 'pt',
    format: 'a4',
  });

  const pageWidth = doc.internal.pageSize.getWidth();
  const pageHeight = doc.internal.pageSize.getHeight();
  const margin = 40;
  const contentWidth = pageWidth - margin * 2;

  // Header
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(15);
  doc.setTextColor(24, 43, 73);
  doc.text('Clinical Evidence Dossier', margin, 42);

  doc.setFont('helvetica', 'normal');
  doc.setFontSize(8);
  doc.setTextColor(100);
  const timestamp = new Date().toLocaleString('en-US', {
    dateStyle: 'medium',
    timeStyle: 'short',
  });
  doc.text(`Generated: ${timestamp} | Patient-to-Trial Match & Criterion Verification Report`, margin, 54);

  doc.setDrawColor(215, 222, 232);
  doc.setLineWidth(0.75);
  doc.line(margin, 60, pageWidth - margin, 60);

  // Patient Summary Table
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(10.5);
  doc.setTextColor(30);
  doc.text('Patient Summary', margin, 78);

  const patient = (data as any).patient || {};
  const sq = (data as any).structured_query || {};

  const patientId = data.patient_profile_id || patient.patient_id || patient.id || 'N/A';
  const age = patient.age ?? sq.age;
  const sex = patient.sex || patient.gender || sq.sex;
  const demographicsStr = (age != null ? `${age} yo` : 'N/A') + ', ' + (sex || 'N/A');

  const condition = patient.condition || patient.primary_condition || sq.condition || 'N/A';
  const biomarkers =
    patient.biomarkers ||
    (Array.isArray(sq.biomarkers) ? sq.biomarkers.join(', ') : sq.biomarkers) ||
    'None reported';
  const stage = patient.stage || patient.disease_stage || sq.stage || 'Not specified';
  const priorTherapies =
    patient.prior_therapies ||
    (Array.isArray(sq.prior_therapy) ? sq.prior_therapy.join(', ') : sq.prior_therapy) ||
    'None reported';

  const patientRows: RowInput[] = [
    [
      { content: 'Patient ID:', styles: { fontStyle: 'bold', textColor: 90 } },
      { content: cleanClinicalText(patientId) },
      { content: 'Demographics:', styles: { fontStyle: 'bold', textColor: 90 } },
      { content: cleanClinicalText(demographicsStr) },
    ],
    [
      { content: 'Primary Condition:', styles: { fontStyle: 'bold', textColor: 90 } },
      { content: cleanClinicalText(condition) },
      { content: 'Key Biomarkers:', styles: { fontStyle: 'bold', textColor: 90 } },
      { content: cleanClinicalText(biomarkers) },
    ],
    [
      { content: 'Disease Stage:', styles: { fontStyle: 'bold', textColor: 90 } },
      { content: cleanClinicalText(stage) },
      { content: 'Prior Therapies:', styles: { fontStyle: 'bold', textColor: 90 } },
      { content: cleanClinicalText(priorTherapies) },
    ],
  ];

  autoTable(doc, {
    startY: 84,
    margin: { top: 45, bottom: 65, left: margin, right: margin },
    body: patientRows,
    theme: 'plain',
    styles: { font: 'helvetica', fontSize: 8, cellPadding: 3.5, overflow: 'linebreak' },
    columnStyles: { 0: { cellWidth: 90 }, 1: { cellWidth: 164 }, 2: { cellWidth: 85 }, 3: { cellWidth: 174 } },
  });

  // Candidate Trial Rankings Overview
  let currentY = (doc as any).lastAutoTable.finalY + 16;
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(10.5);
  doc.setTextColor(30);
  doc.text('Candidate Trial Rankings', margin, currentY);

  const trials = data.trials || (data as any).matches || [];
  const rankingRows: RowInput[] = trials.map((t: any, idx: number) => {
    let score = 'N/A';
    if (t.match_score !== undefined) {
      score = `${Math.round(t.match_score * 100)}%`;
    } else if (t.matchScore !== undefined) {
      score = `${Math.round(t.matchScore * 100)}%`;
    } else if (t.satisfied_count !== undefined && (t.criterion_verdicts?.length || t.criteria?.length)) {
      const count = t.criterion_verdicts?.length || t.criteria?.length;
      score = `${Math.round((t.satisfied_count / count) * 100)}%`;
    }

    let status = t.status || t.verdict_summary;
    if (!status && t.overall_verdict) {
      status =
        t.overall_verdict === 'match'
          ? 'Match'
          : t.overall_verdict === 'no_match'
          ? t.hard_exclusion_hit
            ? 'Excluded'
            : 'No match'
          : 'Unclear';
    }

    return [
      cleanClinicalText(t.nct_id || t.nctId || `#${idx + 1}`),
      cleanClinicalText(t.title || 'Untitled Protocol'),
      cleanClinicalText(Array.isArray(t.phase) ? t.phase.join(', ') : t.phase || 'N/A'),
      cleanClinicalText(score),
      cleanClinicalText(status || 'Evaluated'),
    ];
  });

  autoTable(doc, {
    startY: currentY + 6,
    margin: { top: 45, bottom: 65, left: margin, right: margin },
    head: [['NCT ID', 'Title', 'Phase', 'Match Score %', 'Status']],
    body: rankingRows.length > 0 ? rankingRows : [['-', 'No trials found', '-', '-', '-']],
    theme: 'striped',
    headStyles: { fillColor: [35, 55, 85], textColor: 255, fontSize: 8, fontStyle: 'bold', cellPadding: 4 },
    styles: { font: 'helvetica', fontSize: 7.5, cellPadding: 4, overflow: 'linebreak' },
    columnStyles: {
      0: { cellWidth: 70, fontStyle: 'bold' },
      1: { cellWidth: 258 },
      2: { cellWidth: 50, halign: 'center' },
      3: { cellWidth: 65, halign: 'center' },
      4: { cellWidth: 70, halign: 'center' },
    },
  });

  // Per-Criterion Breakdown & Citations
  currentY = (doc as any).lastAutoTable.finalY + 20;

  trials.forEach((trial: any, tIdx: number) => {
    // Avoid orphan headers: ensure 170pt available before drawing header & starting table
    if (currentY > pageHeight - 65 - 170) {
      doc.addPage();
      currentY = 45;
    }

    doc.setFont('helvetica', 'bold');
    doc.setFontSize(9.5);
    doc.setTextColor(24, 43, 73);
    const trialHeader = `Study ${tIdx + 1}: ${trial.nct_id || trial.nctId || ''} - ${trial.title || ''}`;
    const wrappedHeader = doc.splitTextToSize(cleanClinicalText(trialHeader), contentWidth);
    doc.text(wrappedHeader, margin, currentY);
    currentY += wrappedHeader.length * 11 + 4;

    const criteriaList = trial.criteria || trial.criterion_results || trial.criterion_verdicts || [];
    const criteriaRows: RowInput[] = criteriaList.map((c: any) => {
      let rawVerdict = cleanClinicalText((c.verdict || 'UNCLEAR').toUpperCase());
      if (rawVerdict === 'MATCH') rawVerdict = 'MET';
      if (rawVerdict === 'NO_MATCH' || rawVerdict === 'NO MATCH') rawVerdict = 'NOT MET';

      let textCol: [number, number, number] = [147, 112, 30]; // Amber
      let bgCol: [number, number, number] = [245, 238, 221];
      if (rawVerdict === 'MET') {
        textCol = [47, 111, 98]; // Green
        bgCol = [230, 238, 236];
      } else if (rawVerdict === 'NOT MET' || rawVerdict === 'NOT_MET') {
        textCol = [162, 59, 59]; // Red
        bgCol = [245, 233, 233];
      }

      let critName = c.criterion || c.name;
      if (!critName && c.criterion_type) {
        critName = `${c.criterion_type === 'inclusion' ? 'Inclusion' : 'Exclusion'} #${(c.criterion_index ?? 0) + 1}`;
      }
      critName = cleanClinicalText(critName || 'Criterion');
      const rationale = cleanClinicalText(c.rationale || '');
      const criterionCell = rationale ? `${critName}\n\nRationale:\n${rationale}` : critName;
      const citationText = cleanClinicalText(c.citation || c.cited_text || '');

      return [
        { content: criterionCell, styles: { fontStyle: 'normal' } },
        {
          content: rawVerdict.replace('_', ' '),
          styles: { halign: 'center', valign: 'middle', fontStyle: 'bold', textColor: textCol, fillColor: bgCol },
        },
        {
          content: citationText ? `"${citationText}"` : 'No explicit citation recorded.',
          styles: { fontStyle: 'normal', textColor: [60, 65, 75] },
        },
      ];
    });

    autoTable(doc, {
      startY: currentY,
      margin: { top: 45, bottom: 65, left: margin, right: margin },
      rowPageBreak: 'avoid',
      showHead: 'everyPage',
      head: [['Criterion & Clinical Rationale', 'Verdict', 'Verbatim Evidence Citation']],
      body: criteriaRows.length > 0 ? criteriaRows : [['No individual criteria evaluated', 'UNCLEAR', 'N/A']],
      theme: 'grid',
      headStyles: { fillColor: [240, 243, 248], textColor: 40, fontSize: 7.5, fontStyle: 'bold', cellPadding: 4 },
      styles: {
        font: 'helvetica',
        fontSize: 7,
        cellPadding: 4.5,
        overflow: 'linebreak',
        valign: 'top',
        lineColor: [225, 230, 238],
        lineWidth: 0.5,
      },
      columnStyles: {
        0: { cellWidth: 165 },
        1: { cellWidth: 60 },
        2: { cellWidth: 288 },
      },
    });

    currentY = (doc as any).lastAutoTable.finalY + 18;
  });

  // Running Footers
  const totalPages = doc.getNumberOfPages();
  for (let i = 1; i <= totalPages; i++) {
    doc.setPage(i);
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(7);
    doc.setTextColor(130);

    doc.setDrawColor(225, 230, 238);
    doc.setLineWidth(0.5);
    doc.line(margin, pageHeight - 26, pageWidth - margin, pageHeight - 26);

    doc.text(
      'CONFIDENTIAL - FOR RESEARCH USE ONLY - NOT A SUBSTITUTE FOR CLINICAL JUDGMENT',
      margin,
      pageHeight - 16
    );
    doc.text(`Page ${i} of ${totalPages}`, pageWidth - margin, pageHeight - 16, { align: 'right' });
  }

  const patientIdSaved = (data as any).patient?.patient_id || (data as any).patient?.id || data.patient_profile_id || 'dossier';
  const fileTimestamp = new Date().toISOString().split('T')[0];
  if (typeof window !== 'undefined') {
    doc.save(`clinical-dossier-${cleanClinicalText(patientIdSaved)}-${fileTimestamp}.pdf`);
  }
  return doc as any;
}
