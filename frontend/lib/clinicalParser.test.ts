import { describe, it, expect } from "vitest";
import { parseClinicalDocument } from "./clinicalParser";

describe("parseClinicalDocument", () => {
  it("extracts age, sex, condition, stage, therapy, and biomarker from realistic clinical report", () => {
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
    expect(result).toContain("completed neoadjuvant chemoradiation");
    expect(result).toContain("PD-L1 positive");
    expect(result).toContain("no distant metastasis");
    expect(result.endsWith(".")).toBe(true);
    expect(result).not.toContain("undefined");
    expect(result).not.toContain("null");
    expect(result).not.toContain(", ,");
  });

  it("returns empty string for empty or whitespace input", () => {
    expect(parseClinicalDocument("")).toBe("");
    expect(parseClinicalDocument("   \n\t  ")).toBe("");
    expect(parseClinicalDocument(null as any)).toBe("");
    expect(parseClinicalDocument(undefined as any)).toBe("");
  });

  it("returns empty string for garbage / unextractable input", () => {
    const garbage = "lorem ipsum dolor sit amet consectetur adipiscing elit random text without medical facts 123456";
    expect(parseClinicalDocument(garbage)).toBe("");
  });

  it("omits missing fields cleanly without dangling commas or placeholders", () => {
    // Only condition and age provided
    const text = "Patient is 45-year-old diagnosed with non-small cell lung cancer.";
    const result = parseClinicalDocument(text);

    expect(result).toBe("45-year-old, non-small cell lung cancer.");
    expect(result).not.toContain("undefined");
    expect(result).not.toContain(",,");
    expect(result.startsWith(",")).toBe(false);
    expect(result.endsWith(".")).toBe(true);
  });

  it("extracts various biomarkers accurately (HER2, EGFR, KRAS, BRAF, MSI-H)", () => {
    const text = "72 yo male with Stage IV colorectal cancer. Molecular testing reveals KRAS G12C mutation, BRAF wild-type, and MSS status. No distant metastasis noted.";
    const result = parseClinicalDocument(text);

    expect(result).toContain("72-year-old male");
    expect(result).toContain("Stage IV colorectal cancer");
    expect(result).toContain("KRAS G12C");
    expect(result).toContain("BRAF wild-type");
    expect(result).toContain("MSS");
    expect(result).toContain("no distant metastasis");
  });

  it("handles HER2 and breast cancer with clean composition", () => {
    const text = "52 yo female with Stage II invasive ductal carcinoma, HER2-positive, received prior chemotherapy.";
    const result = parseClinicalDocument(text);

    expect(result).toContain("52-year-old female");
    expect(result).toContain("Stage II invasive ductal carcinoma");
    expect(result).toContain("HER2-positive");
    expect(result).toContain("prior chemotherapy");
  });

  it("truncates output to 4000 characters maximum", () => {
    const text = "64 yo female with Stage III esophageal squamous cell carcinoma. " + "word ".repeat(2000);
    const result = parseClinicalDocument(text);
    expect(result.length).toBeLessThanOrEqual(4000);
  });
});
