import { describe, it, expect } from "vitest";
import { parseClinicalDocument } from "../lib/clinicalParser";

describe("parseClinicalDocument High-Fidelity Parser", () => {
  it("preserves full multi-line biomarkers, metastatic sites, and specific treatment regimens from structured notes", () => {
    const document = `
      PATIENT: 58 yo male
      DIAGNOSIS:
      Non-small cell lung cancer (metastatic lung adenocarcinoma, right upper lobe)
      DISEASE STAGE:
      Stage IVB with pleural dissemination and osseous metastasis
      BIOMARKER PANEL:
      - EGFR: Exon 19 deletion (positive)
      - ALK: Negative
      - KRAS: Wild-type
      - PD-L1: TPS 45%
      PRIOR THERAPIES:
      Previous first-line platinum doublet chemotherapy (cisplatin + pemetrexed) x 4 cycles, followed by surgical wedge resection. No prior immunotherapy or targeted kinase inhibitors.
    `;

    const result = parseClinicalDocument(document);

    // Verify multi-line brief format
    expect(result).toContain("58-year-old male.");
    expect(result).toContain(
      "Diagnosis: Non-small cell lung cancer (metastatic lung adenocarcinoma, right upper lobe)."
    );
    expect(result).toContain(
      "Stage: Stage IVB with pleural dissemination and osseous metastasis."
    );
    expect(result).toContain(
      "Biomarkers: EGFR Exon 19 deletion (positive), ALK Negative, KRAS Wild-type, PD-L1 TPS 45%."
    );
    expect(result).toContain(
      "Prior Therapies: Previous first-line platinum doublet chemotherapy (cisplatin + pemetrexed) x 4 cycles, followed by surgical wedge resection. No prior immunotherapy or targeted kinase inhibitors."
    );

    // Verify critical oncology entities are 100% preserved
    expect(result).toContain("EGFR Exon 19 deletion (positive)");
    expect(result).toContain("PD-L1 TPS 45%");
    expect(result).toContain("ALK Negative");
    expect(result).toContain("KRAS Wild-type");
    expect(result).toContain("pleural dissemination and osseous metastasis");
    expect(result).toContain("cisplatin + pemetrexed");
    expect(result).toContain("x 4 cycles");
    expect(result).toContain("surgical wedge resection");
    expect(result).toContain("No prior immunotherapy or targeted kinase inhibitors");
  });

  it("extracts demographics, diagnosis, stage, treatments, and biomarkers from clinical records", () => {
    const pathologyReport = `
      PATIENT CLINICAL RECORD
      Age: 64
      Sex: Female
      CLINICAL HISTORY & DIAGNOSIS:
      Patient is a 64-year-old female diagnosed with Stage III esophageal squamous cell carcinoma.
      TREATMENT HISTORY:
      Completed neoadjuvant chemoradiation prior to evaluation.
      BIOMARKER ANALYSIS:
      Tumor tissue assessed: PD-L1 positive (CPS >= 10).
      IMAGING FINDINGS:
      PET-CT restaging shows no distant metastasis.
    `;

    const result = parseClinicalDocument(pathologyReport);

    expect(result).toContain("64-year-old female");
    expect(result).toContain("Stage III esophageal squamous cell carcinoma");
    expect(result).toContain("Completed neoadjuvant chemoradiation");
    expect(result).toContain("PD-L1 positive (CPS >= 10)");
    expect(result).toContain("no distant metastasis");
    expect(result.endsWith(".")).toBe(true);
    expect(result).not.toContain("undefined");
    expect(result).not.toContain("null");
  });

  it("preserves complex gynecologic / breast oncology panels with surgical resections and genomic findings", () => {
    const report = `
      DEMOGRAPHICS: 52 yo woman
      PRIMARY DIAGNOSIS: High-grade serous ovarian carcinoma
      DISEASE STAGE: Stage IIIC with peritoneal carcinomatosis and omental caking
      MOLECULAR PROFILE:
      - BRCA1: Pathogenic germline mutation (Exon 11)
      - HRD: Positive (Score 68)
      - HER2: IHC 1+ (Negative)
      PRIOR THERAPIES:
      Neoadjuvant carboplatin + paclitaxel x 6 cycles followed by interval debulking surgery and bilateral salpingo-oophorectomy. Maintenance olaparib initiated.
    `;

    const result = parseClinicalDocument(report);

    expect(result).toContain("52-year-old female.");
    expect(result).toContain("Diagnosis: High-grade serous ovarian carcinoma.");
    expect(result).toContain("Stage: Stage IIIC with peritoneal carcinomatosis and omental caking.");
    expect(result).toContain("BRCA1 Pathogenic germline mutation (Exon 11)");
    expect(result).toContain("HRD Positive (Score 68)");
    expect(result).toContain("HER2 IHC 1+ (Negative)");
    expect(result).toContain("carboplatin + paclitaxel x 6 cycles");
    expect(result).toContain("bilateral salpingo-oophorectomy");
    expect(result).toContain("Maintenance olaparib initiated");
  });

  it("returns empty string for empty or whitespace input", () => {
    expect(parseClinicalDocument("")).toBe("");
    expect(parseClinicalDocument("   \n\t  ")).toBe("");
    expect(parseClinicalDocument(null as any)).toBe("");
    expect(parseClinicalDocument(undefined as any)).toBe("");
  });

  it("returns empty string for garbage / unextractable input without clinical entities", () => {
    const garbage =
      "lorem ipsum dolor sit amet consectetur adipiscing elit random text without medical facts 123456";
    expect(parseClinicalDocument(garbage)).toBe("");
  });

  it("falls back gracefully for unstructured single-line clinical inputs without dropping details", () => {
    const text = "45-year-old female, Stage I breast cancer.";
    const result = parseClinicalDocument(text);

    expect(result).toBe("45-year-old female, Stage I breast cancer.");
    expect(result).not.toContain("undefined");
  });

  it("preserves full sentences in unstructured multi-sentence clinical notes", () => {
    const note =
      "Patient is a 58 yo male with Stage II colon adenocarcinoma who received prior chemotherapy. " +
      "Molecular testing identified KRAS G12C and MSS status. No brain metastases detected.";
    const result = parseClinicalDocument(note);

    expect(result).toContain("58-year-old male");
    expect(result).toContain("Stage II colon adenocarcinoma");
    expect(result).toContain("prior chemotherapy");
    expect(result).toContain("KRAS G12C");
    expect(result).toContain("MSS");
    expect(result).toContain("No brain metastases detected");
  });

  it("truncates output to 4000 characters maximum", () => {
    const text =
      "64 yo female with Stage III esophageal squamous cell carcinoma. " +
      "word ".repeat(2000);
    const result = parseClinicalDocument(text);
    expect(result.length).toBeLessThanOrEqual(4000);
  });
});
