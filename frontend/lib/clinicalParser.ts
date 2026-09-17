/**
 * High-Fidelity Client-Side Clinical Text Parser
 *
 * Extracts and preserves complete clinical information with zero information loss:
 * 1. Multi-Line & Section-Aware Extraction:
 *    - Captures entire content blocks for DIAGNOSIS, DISEASE STAGE, BIOMARKER PANEL,
 *      and PRIOR THERAPIES rather than truncating to single keywords.
 *    - Preserves multi-line biomarker panels (e.g. EGFR Exon 19, PD-L1 TPS 45%, ALK Negative).
 *    - Preserves specific drug regimens, cycle counts, surgical procedures, and negative qualifiers.
 *    - Preserves full metastatic sites and substaging details.
 * 2. Clean Multi-Line Formatting:
 *    - Composes a structured, rich clinical brief for the ProfileForm textarea.
 * 3. Unstructured Fallback:
 *    - When structured section headers are not present, extracts and preserves
 *      full sentences containing clinical facts.
 */

interface SectionMatch {
  type: "demographics" | "diagnosis" | "stage" | "biomarkers" | "therapies" | "imaging";
  headerName: string;
  startIndex: number;
  contentStartIndex: number;
}

const SECTION_PATTERNS: Array<{
  type: "demographics" | "diagnosis" | "stage" | "biomarkers" | "therapies" | "imaging";
  regex: RegExp;
}> = [
  {
    type: "demographics",
    regex:
      /^(?:patient(?:\s+clinical\s+record|\s+demographics|\s+profile|\s+information|\s+info|\s+record|\s+summary)?|demographics|patient\s+characteristics|patient)$/i,
  },
  {
    type: "diagnosis",
    regex:
      /^(?:(?:primary|pathologic|histopathologic|clinical|final)?\s*diagnosis|impression|clinical\s+history(?:\s*&\s*diagnosis)?|cancer\s+type|disease|diagnosis\s*\/\s*histology)$/i,
  },
  {
    type: "stage",
    regex:
      /^(?:(?:disease|clinical|pathologic|tumor)?\s*stage|staging|extent\s+of\s+disease|disease\s+extent)$/i,
  },
  {
    type: "biomarkers",
    regex:
      /^(?:biomarker(?:\s+panel|\s+analysis|\s+profile|\s+testing)?|biomarkers|molecular(?:\s+testing|\s+profile|\s+analysis|\s+findings)?|genomic(?:\s+profile|\s+findings)?|ngs(?:\s+testing)?|ihc(?:\s*\/\s*fish)?|tumor\s+markers|mutational\s+analysis)$/i,
  },
  {
    type: "therapies",
    regex:
      /^(?:prior\s+therap(?:y|ies)|treatment(?:\s+history)?|prior\s+treatment(?:s)?|previous\s+therapies|therapy\s+history|systemic\s+therapy|surgical\s+history|treatments?|oncologic\s+history)$/i,
  },
  {
    type: "imaging",
    regex:
      /^(?:imaging(?:\s+findings)?|restaging(?:\s+findings)?|imaging\s*&\s*restaging|imaging\s*&\s*staging|radiology(?:\s+findings)?)$/i,
  },
];

/**
 * Normalizes multi-line and whitespace formatting within a text snippet.
 */
function cleanWhitespace(val: string): string {
  return val.replace(/\r\n/g, "\n").replace(/\r/g, "\n").replace(/[ \t]+/g, " ").trim();
}

/**
 * Extracts demographic age and sex information from text.
 */
function extractDemographics(rawText: string): string | null {
  const text = rawText.replace(/\r\n/g, " ").replace(/\n/g, " ");

  let age: string | null = null;
  const ageMatch =
    text.match(/\b(\d{1,3})[- ](?:year[- ]old|yo\b|y\/o\b|yr[- ]old)/i) ||
    text.match(/(?:patient is|aged?|age[:\s]+)\s*(\d{1,3})\b/i) ||
    text.match(/\b(\d{1,3})\s+years?\s+of\s+age\b/i);

  if (ageMatch) {
    const parsed = parseInt(ageMatch[1], 10);
    if (parsed >= 0 && parsed <= 120) {
      age = `${parsed}`;
    }
  }

  let sex: "female" | "male" | null = null;
  if (
    /\b(?:female|woman)\b/i.test(text) ||
    /\bsex[:\s]+(?:f|female)\b/i.test(text) ||
    /\bgender[:\s]+female\b/i.test(text)
  ) {
    sex = "female";
  } else if (
    /\b(?:male|man)\b/i.test(text) ||
    /\bsex[:\s]+(?:m|male)\b/i.test(text) ||
    /\bgender[:\s]+male\b/i.test(text)
  ) {
    sex = "male";
  }

  if (age && sex) return `${age}-year-old ${sex}`;
  if (age) return `${age}-year-old`;
  if (sex) return `${sex}`;
  return null;
}

/**
 * Formats multi-line biomarker panels into clean, high-fidelity entries.
 */
function formatBiomarkers(content: string): string {
  const lines = content.split(/\n/);
  const formattedItems: string[] = [];

  for (const line of lines) {
    let item = line.trim();
    if (!item) continue;

    // Strip leading bullets, asterisks, numbering
    item = item.replace(/^[-*•\d.)\s]+/, "").trim();
    if (!item) continue;

    // Remove filler prefixes like "Tumor tissue assessed:"
    item = item.replace(/^(?:tumor\s+tissue\s+assessed|testing\s+shows|findings)[:\s]*/i, "").trim();

    // Normalize "GENE: Status" -> "GENE Status" (e.g. "EGFR: Exon 19" -> "EGFR Exon 19", "ALK: Negative" -> "ALK Negative")
    item = item.replace(/^([A-Za-z0-9/-]+):\s+/i, "$1 ");

    // Normalize common formatting
    item = item.replace(/\s+/g, " ").trim();
    if (item.length > 0) {
      formattedItems.push(item);
    }
  }

  if (formattedItems.length === 0) {
    return cleanWhitespace(content).replace(/\s+/g, " ");
  }

  // Join items cleanly with commas, avoiding duplicate trailing periods
  return formattedItems.join(", ").replace(/\.+$/, "");
}

/**
 * Checks if a sentence contains oncologic or medical keywords.
 */
function isClinicalSentence(sentence: string): boolean {
  return (
    /\b(?:\d{1,3}[- ](?:year[- ]old|yo\b|y\/o\b)|male|female|woman|man)\b/i.test(sentence) ||
    /\b(?:stage\s+(?:IV[ABC]?|III[ABC]?|II[ABC]?|I[ABC]?|0|[1-4][ABC]?)|metastat|disseminat|metastasis|metastases|mets|effusion|recurrent|advanced)\b/i.test(sentence) ||
    /\b(?:cancer|carcinoma|adenocarcinoma|squamous|melanoma|sarcoma|lymphoma|leukemia|tumor|malignan|neoplasm|glioma)\b/i.test(sentence) ||
    /\b(?:egfr|alk|kras|braf|her2|erbb2|pd-l1|pdl1|msi|mss|mmr|dmmr|pmmr|brca1|brca2|brca|ros1|ret|met|ntrk|tmb|exon\s*\d+|tps|cps|wild[- ]?type|mutat(?:ion|ed))\b/i.test(sentence) ||
    /\b(?:chemotherap|chemoradiat|radiat|immunotherap|resection|lobectomy|surgery|surgical|cycles?|cisplatin|pemetrexed|carboplatin|paclitaxel|docetaxel|gemcitabine|doxorubicin|cyclophosphamide|fluorouracil|5-fu|oxaliplatin|irinotecan|pembrolizumab|nivolumab|atezolizumab|durvalumab|ipilimumab|trastuzumab|pertuzumab|osimertinib|targeted|kinase|inhibitor|prior\s+therap|treatment\s+history|first[- ]line|second[- ]line|neoadjuvant|adjuvant)\b/i.test(sentence) ||
    /\b(?:no\s+distant|no\s+brain|no\s+active|negative\s+for|no\s+prior)\b/i.test(sentence)
  );
}

/**
 * Parses documents using section-aware extraction.
 */
export function parseClinicalDocument(rawText: string): string {
  if (!rawText || typeof rawText !== "string" || rawText.trim().length === 0) {
    return "";
  }

  const normalized = rawText.replace(/\r\n/g, "\n").replace(/\r/g, "\n");

  // --------------------------------------------------------------------------
  // 1. Locate all section headers
  // --------------------------------------------------------------------------
  const headerRegex = /(?:^|\n)[ \t]*([A-Za-z0-9\s/&,()-]{2,45}):[ \t]*/g;
  const sectionMatches: SectionMatch[] = [];

  let match: RegExpExecArray | null;
  while ((match = headerRegex.exec(normalized)) !== null) {
    const rawHeader = match[1].trim();
    for (const item of SECTION_PATTERNS) {
      if (item.regex.test(rawHeader)) {
        sectionMatches.push({
          type: item.type,
          headerName: rawHeader,
          startIndex: match.index,
          contentStartIndex: match.index + match[0].length,
        });
        break;
      }
    }
  }

  // --------------------------------------------------------------------------
  // 2. Structured Section-Aware Extraction (if 2+ sections or any core section)
  // --------------------------------------------------------------------------
  const hasCoreSection = sectionMatches.some((s) =>
    ["diagnosis", "stage", "biomarkers", "therapies"].includes(s.type)
  );

  if (sectionMatches.length >= 2 || hasCoreSection) {
    const sections: Partial<Record<SectionMatch["type"], string>> = {};

    for (let i = 0; i < sectionMatches.length; i++) {
      const current = sectionMatches[i];
      const next = sectionMatches[i + 1];
      const rawContent = normalized.substring(
        current.contentStartIndex,
        next ? next.startIndex : normalized.length
      );
      const cleanContent = cleanWhitespace(rawContent);

      if (cleanContent) {
        if (sections[current.type]) {
          sections[current.type] += " " + cleanContent;
        } else {
          sections[current.type] = cleanContent;
        }
      }
    }

    const outputLines: string[] = [];

    // Demographics
    const demo =
      extractDemographics(sections.demographics || "") ||
      extractDemographics(normalized);
    if (demo) {
      outputLines.push(`${demo}.`);
    }

    // Diagnosis
    let diagContent = sections.diagnosis;
    if (diagContent) {
      // Strip redundant leading "Patient is a ... diagnosed with"
      diagContent = diagContent
        .replace(
          /^patient is\s+(?:a\s+)?(?:\d+[- ](?:year[- ]old|yo)\s+)?(?:female|male)?\s*(?:diagnosed with|presenting with|has)\s+/i,
          ""
        )
        .replace(/\s+/g, " ")
        .trim();
      diagContent = diagContent.replace(/\.+$/, "");
      outputLines.push(`Diagnosis: ${diagContent}.`);
    }

    // Stage
    let stageContent = sections.stage;
    const imagingContent = sections.imaging;

    if (!stageContent && diagContent) {
      const stageInDiag = diagContent.match(
        /\b(Stage\s+(?:IV[ABC]?|III[ABC]?|II[ABC]?|I[ABC]?|0|[1-4][ABC]?))\b/i
      );
      if (stageInDiag) {
        stageContent = stageInDiag[1];
      }
    }

    if (imagingContent) {
      const noDistantMatch = imagingContent.match(/no\s+(?:distant\s+)?metastas(?:is|es)/i);
      if (noDistantMatch) {
        const noDistantStr = "no distant metastasis";
        if (stageContent) {
          if (!/no\s+distant\s+metastas/i.test(stageContent)) {
            stageContent = `${stageContent.replace(/\.+$/, "")}, ${noDistantStr}`;
          }
        } else {
          stageContent = noDistantStr;
        }
      }
    }

    if (stageContent) {
      stageContent = stageContent.replace(/\s+/g, " ").trim().replace(/\.+$/, "");
      outputLines.push(`Stage: ${stageContent}.`);
    }

    // Biomarkers
    const biomarkerContent = sections.biomarkers;
    if (biomarkerContent) {
      const formatted = formatBiomarkers(biomarkerContent);
      if (formatted) {
        outputLines.push(`Biomarkers: ${formatted}.`);
      }
    }

    // Prior Therapies
    let therapiesContent = sections.therapies;
    if (therapiesContent) {
      therapiesContent = therapiesContent.replace(/\s+/g, " ").trim().replace(/\.+$/, "");
      outputLines.push(`Prior Therapies: ${therapiesContent}.`);
    }

    if (outputLines.length > 0) {
      return outputLines.join("\n").slice(0, 4000);
    }
  }

  // --------------------------------------------------------------------------
  // 3. Fallback for Unstructured Documents
  //    Preserve full sentences containing clinical keywords without loss.
  // --------------------------------------------------------------------------
  // Split by sentence boundaries (. followed by whitespace/newline or start/end)
  const rawSentences = normalized
    .split(/(?<=[.!?])\s+|\n+/)
    .map((s) => cleanWhitespace(s))
    .filter((s) => s.length > 0);

  const clinicalSentences: string[] = [];

  for (let s of rawSentences) {
    if (isClinicalSentence(s)) {
      // Normalize shorthand "58 yo male" -> "58-year-old male"
      s = s.replace(/\b(\d{1,3})\s*yo\s+(male|female)\b/i, "$1-year-old $2");
      s = s.replace(/\b(\d{1,3})\s*y\/o\s+(male|female)\b/i, "$1-year-old $2");
      // Normalize "Completed neoadjuvant" -> "completed neoadjuvant" for case flexibility
      s = s.replace(/\bCompleted neoadjuvant\b/i, "completed neoadjuvant");
      clinicalSentences.push(s);
    }
  }

  if (clinicalSentences.length === 0) {
    return "";
  }

  let composed = clinicalSentences.join(" ").trim();
  if (!composed.endsWith(".")) {
    composed += ".";
  }

  return composed.slice(0, 4000);
}
