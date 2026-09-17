/**
 * Deterministic Clinical Text Composer
 *
 * Extracts age, sex, condition/diagnosis, disease stage, biomarkers,
 * prior therapies, and relevant clinical status from raw clinical notes
 * and pathology reports using deterministic regex and keyword heuristics.
 *
 * Composes the extracted facts into ONE natural sentence matching the style
 * of ProfileForm's SAMPLE_PROFILE constant:
 * "64-year-old female, Stage III esophageal squamous cell carcinoma, completed neoadjuvant chemoradiation, no distant metastasis."
 */

export function parseClinicalDocument(text: string): string {
  if (!text || typeof text !== "string" || text.trim().length === 0) {
    return "";
  }

  const cleanText = text.replace(/\r\n/g, " ").replace(/\n/g, " ").replace(/\s+/g, " ");

  // --------------------------------------------------------------------------
  // 1. Demographics: Age and Sex
  // --------------------------------------------------------------------------
  let age: string | null = null;
  const ageMatch =
    cleanText.match(/\b(\d{1,3})[- ](?:year[- ]old|yo\b|y\/o\b|yr[- ]old)/i) ||
    cleanText.match(/(?:patient is|aged?|age[:\s]+)\s*(\d{1,3})\b/i) ||
    cleanText.match(/\b(\d{1,3})\s+years?\s+of\s+age\b/i);

  if (ageMatch) {
    const parsedAge = parseInt(ageMatch[1], 10);
    if (parsedAge >= 0 && parsedAge <= 120) {
      age = `${parsedAge}`;
    }
  }

  let sex: "female" | "male" | null = null;
  // Match female first to prevent 'male' substring collision
  if (/\b(?:female|woman)\b/i.test(cleanText) || /\bsex[:\s]+(?:f|female)\b/i.test(cleanText) || /\bgender[:\s]+female\b/i.test(cleanText)) {
    sex = "female";
  } else if (/\b(?:male|man)\b/i.test(cleanText) || /\bsex[:\s]+(?:m|male)\b/i.test(cleanText) || /\bgender[:\s]+male\b/i.test(cleanText)) {
    sex = "male";
  }

  let demographicsPhrase: string | null = null;
  if (age && sex) {
    demographicsPhrase = `${age}-year-old ${sex}`;
  } else if (age) {
    demographicsPhrase = `${age}-year-old`;
  } else if (sex) {
    demographicsPhrase = `${sex}`;
  }

  // --------------------------------------------------------------------------
  // 2. Disease Stage
  // --------------------------------------------------------------------------
  let stage: string | null = null;
  const stageMatch =
    cleanText.match(/\b(Stage\s+(?:IV[ABC]?|III[ABC]?|II[ABC]?|I[ABC]?|0|[1-4][ABC]?))\b/i) ||
    cleanText.match(/\b(metastatic|recurrent|advanced)\b/i);

  if (stageMatch) {
    // Normalize Roman numerals capitalization: e.g. "stage iii" -> "Stage III"
    const rawStage = stageMatch[1];
    if (/^stage/i.test(rawStage)) {
      stage = rawStage.replace(/^stage\s+/i, "Stage ");
      // Capitalize letters in stage: e.g. Stage iiia -> Stage IIIA
      stage = stage.replace(/([ivx0-9]+[abc]?)/i, (m) => m.toUpperCase());
    } else {
      stage = rawStage.charAt(0).toUpperCase() + rawStage.slice(1).toLowerCase();
    }
  }

  // --------------------------------------------------------------------------
  // 3. Condition / Diagnosis
  // --------------------------------------------------------------------------
  let condition: string | null = null;

  // Check for common specific oncologic conditions
  const KNOWN_CONDITIONS: Array<{ pattern: RegExp; label: string }> = [
    { pattern: /\besophageal\s+squamous\s+cell\s+carcinoma\b/i, label: "esophageal squamous cell carcinoma" },
    { pattern: /\besophageal\s+adenocarcinoma\b/i, label: "esophageal adenocarcinoma" },
    { pattern: /\besophageal\s+cancer\b/i, label: "esophageal cancer" },
    { pattern: /\bnon[- ]small\s+cell\s+lung\s+cancer\b/i, label: "non-small cell lung cancer" },
    { pattern: /\bsmall\s+cell\s+lung\s+cancer\b/i, label: "small cell lung cancer" },
    { pattern: /\blung\s+adenocarcinoma\b/i, label: "lung adenocarcinoma" },
    { pattern: /\blung\s+squamous\s+cell\s+carcinoma\b/i, label: "lung squamous cell carcinoma" },
    { pattern: /\blung\s+cancer\b/i, label: "lung cancer" },
    { pattern: /\btriple[- ]negative\s+breast\s+cancer\b/i, label: "triple-negative breast cancer" },
    { pattern: /\binvasive\s+ductal\s+carcinoma\b/i, label: "invasive ductal carcinoma" },
    { pattern: /\bbreast\s+adenocarcinoma\b/i, label: "breast adenocarcinoma" },
    { pattern: /\bbreast\s+cancer\b/i, label: "breast cancer" },
    { pattern: /\bcolorectal\s+cancer\b/i, label: "colorectal cancer" },
    { pattern: /\bcolon\s+adenocarcinoma\b/i, label: "colon adenocarcinoma" },
    { pattern: /\brectal\s+adenocarcinoma\b/i, label: "rectal adenocarcinoma" },
    { pattern: /\bpancreatic\s+ductal\s+adenocarcinoma\b/i, label: "pancreatic ductal adenocarcinoma" },
    { pattern: /\bpancreatic\s+adenocarcinoma\b/i, label: "pancreatic adenocarcinoma" },
    { pattern: /\bpancreatic\s+cancer\b/i, label: "pancreatic cancer" },
    { pattern: /\bgastric\s+adenocarcinoma\b/i, label: "gastric adenocarcinoma" },
    { pattern: /\bgastric\s+cancer\b/i, label: "gastric cancer" },
    { pattern: /\bhepatocellular\s+carcinoma\b/i, label: "hepatocellular carcinoma" },
    { pattern: /\brenal\s+cell\s+carcinoma\b/i, label: "renal cell carcinoma" },
    { pattern: /\bprostate\s+adenocarcinoma\b/i, label: "prostate adenocarcinoma" },
    { pattern: /\bprostate\s+cancer\b/i, label: "prostate cancer" },
    { pattern: /\bcutaneous\s+melanoma\b/i, label: "cutaneous melanoma" },
    { pattern: /\bmelanoma\b/i, label: "melanoma" },
    { pattern: /\bhigh[- ]grade\s+serous\s+ovarian\s+carcinoma\b/i, label: "high-grade serous ovarian carcinoma" },
    { pattern: /\bovarian\s+carcinoma\b/i, label: "ovarian carcinoma" },
    { pattern: /\bovarian\s+cancer\b/i, label: "ovarian cancer" },
    { pattern: /\bhead\s+and\s+neck\s+squamous\s+cell\s+carcinoma\b/i, label: "head and neck squamous cell carcinoma" },
    { pattern: /\burothelial\s+carcinoma\b/i, label: "urothelial carcinoma" },
    { pattern: /\bbladder\s+cancer\b/i, label: "bladder cancer" },
    { pattern: /\bglioblastoma\b/i, label: "glioblastoma" },
  ];

  for (const cond of KNOWN_CONDITIONS) {
    if (cond.pattern.test(cleanText)) {
      condition = cond.label;
      break;
    }
  }

  // If no known condition matched, attempt diagnosis header or generic histology heuristic
  if (!condition) {
    const diagMatch =
      cleanText.match(/(?:primary diagnosis|pathologic diagnosis|diagnosis|impression|cancer type)[:\s]+([A-Za-z0-9\s-]+?)(?=[,.;\n]|\bstage\b|\bgrade\b|$)/i) ||
      cleanText.match(/\b([A-Za-z\s-]+(?:squamous cell carcinoma|adenocarcinoma|carcinoma|melanoma|sarcoma|lymphoma|cancer|malignancy|tumor|leukemia|myeloma))\b/i);

    if (diagMatch && diagMatch[1]) {
      const candidate = diagMatch[1].trim().toLowerCase();
      // Avoid false positive matches on common metadata words
      if (candidate.length > 3 && !/^(unknown|none|n\/a|pending|sample|report)$/i.test(candidate)) {
        condition = candidate;
      }
    }
  }

  // Combine stage and condition if both present
  let diseasePhrase: string | null = null;
  if (stage && condition) {
    // If condition already starts with stage, don't duplicate
    if (condition.toLowerCase().startsWith(stage.toLowerCase())) {
      diseasePhrase = condition;
    } else {
      diseasePhrase = `${stage} ${condition}`;
    }
  } else if (stage) {
    diseasePhrase = stage;
  } else if (condition) {
    diseasePhrase = condition;
  }

  // --------------------------------------------------------------------------
  // 4. Biomarkers (HER2, PD-L1, EGFR, KRAS, BRAF, MSI-H, MSS, dMMR, BRCA1/2)
  // --------------------------------------------------------------------------
  const biomarkers: string[] = [];

  // HER2
  const her2Match = cleanText.match(/\bHER2[- ]?(positive|negative|\+|\-|amplified|overexpressed|3\+|2\+|1\+|0)\b/i);
  if (her2Match) {
    const val = her2Match[1].toLowerCase();
    if (val === "positive" || val === "+" || val === "amplified" || val === "overexpressed" || val === "3+") {
      biomarkers.push("HER2-positive");
    } else if (val === "negative" || val === "-" || val === "0" || val === "1+") {
      biomarkers.push("HER2-negative");
    } else {
      biomarkers.push(`HER2 ${val}`);
    }
  }

  // PD-L1
  const pdl1Match =
    cleanText.match(/\bPD-L1\s*(?:expression\s*)?((?:CPS|TPS)\s*[>=<]?\s*\d+%?|positive|negative|\+|-)\b/i) ||
    cleanText.match(/\bPD-L1[:\s]+(positive|negative)\b/i);
  if (pdl1Match) {
    const val = pdl1Match[1];
    if (/^positive|\+$/i.test(val)) {
      biomarkers.push("PD-L1 positive");
    } else if (/^negative|\-$/i.test(val)) {
      biomarkers.push("PD-L1 negative");
    } else {
      biomarkers.push(`PD-L1 ${val.toUpperCase()}`);
    }
  }

  // EGFR
  const egfrMatch = cleanText.match(/\bEGFR\s*(mutat(?:ion|ed)|wild[- ]?type|positive|negative|exon\s*\d+|T790M|L858R)\b/i);
  if (egfrMatch) {
    const val = egfrMatch[1].toLowerCase();
    if (/wild/i.test(val)) biomarkers.push("EGFR wild-type");
    else if (/mutat|pos/i.test(val)) biomarkers.push("EGFR-mutated");
    else if (/neg/i.test(val)) biomarkers.push("EGFR-negative");
    else biomarkers.push(`EGFR ${egfrMatch[1]}`);
  }

  // KRAS
  const krasMatch = cleanText.match(/\bKRAS\s*(mutat(?:ion|ed)|wild[- ]?type|positive|negative|G12[C|D|V]|exon\s*\d+)\b/i);
  if (krasMatch) {
    const val = krasMatch[1].toLowerCase();
    if (/wild/i.test(val)) biomarkers.push("KRAS wild-type");
    else if (/g12/i.test(val)) biomarkers.push(`KRAS ${krasMatch[1].toUpperCase()}`);
    else if (/mutat|pos/i.test(val)) biomarkers.push("KRAS-mutated");
    else if (/neg/i.test(val)) biomarkers.push("KRAS-negative");
    else biomarkers.push(`KRAS ${krasMatch[1]}`);
  }

  // BRAF
  const brafMatch = cleanText.match(/\bBRAF\s*(mutat(?:ion|ed)|wild[- ]?type|positive|negative|V600E)\b/i);
  if (brafMatch) {
    const val = brafMatch[1].toLowerCase();
    if (/v600e/i.test(val)) biomarkers.push("BRAF V600E");
    else if (/wild/i.test(val)) biomarkers.push("BRAF wild-type");
    else if (/mutat|pos/i.test(val)) biomarkers.push("BRAF-mutated");
    else if (/neg/i.test(val)) biomarkers.push("BRAF-negative");
    else biomarkers.push(`BRAF ${brafMatch[1]}`);
  }

  // MSI / MMR
  if (/\bMSI[- ]?H\b|microsatellite\s+instability[- ]high/i.test(cleanText)) {
    biomarkers.push("MSI-H");
  } else if (/\bMSS\b|microsatellite\s+stable/i.test(cleanText)) {
    biomarkers.push("MSS");
  }

  if (/\bdMMR\b|mismatch\s+repair[- ]deficient/i.test(cleanText)) {
    biomarkers.push("dMMR");
  } else if (/\bpMMR\b|mismatch\s+repair[- ]proficient/i.test(cleanText)) {
    biomarkers.push("pMMR");
  }

  // BRCA1/2
  const brcaMatch = cleanText.match(/\b(BRCA1\/2|BRCA1|BRCA2|BRCA)\s*(mutat(?:ion|ed)|positive|negative|wild[- ]?type)?\b/i);
  if (brcaMatch) {
    const gene = brcaMatch[1].toUpperCase();
    const status = brcaMatch[2] ? brcaMatch[2].toLowerCase() : "";
    if (/mutat|pos/i.test(status)) biomarkers.push(`${gene}-mutated`);
    else if (/wild|neg/i.test(status)) biomarkers.push(`${gene} wild-type`);
    else biomarkers.push(`${gene} mutation`);
  }

  // --------------------------------------------------------------------------
  // 5. Prior Therapies
  // --------------------------------------------------------------------------
  const therapies: string[] = [];
  if (/\b(?:completed|received|underwent)\s+neoadjuvant\s+chemoradiation\b/i.test(cleanText) || /\bneoadjuvant\s+chemoradiation\b/i.test(cleanText)) {
    therapies.push("completed neoadjuvant chemoradiation");
  } else if (/\bneoadjuvant\s+chemotherapy\b/i.test(cleanText)) {
    therapies.push("completed neoadjuvant chemotherapy");
  } else if (/\bchemoradiotherapy\b|\bchemoradiation\b/i.test(cleanText)) {
    therapies.push("chemoradiation");
  } else if (/\bchemotherapy\b/i.test(cleanText)) {
    therapies.push("prior chemotherapy");
  } else if (/\bradiation\b|\bradiotherapy\b/i.test(cleanText)) {
    therapies.push("prior radiation");
  }

  if (/\b(?:prior|post)\s+(?:surgical\s+)?resection\b/i.test(cleanText) || /\bradical\s+resection\b/i.test(cleanText)) {
    if (!therapies.some((t) => t.includes("resection"))) {
      therapies.push("prior resection");
    }
  }

  // Specific drug regimens if mentioned
  if (/\bpembrolizumab\b/i.test(cleanText) && !therapies.some((t) => t.includes("pembrolizumab"))) {
    therapies.push("pembrolizumab");
  }

  // --------------------------------------------------------------------------
  // 6. Clinical Status / Exclusions (e.g. distant metastasis)
  // --------------------------------------------------------------------------
  let exclusionStatus: string | null = null;
  if (/\b(?:no|without|negative\s+for)\s+(?:distant\s+)?metastas(?:is|es)\b/i.test(cleanText) || /\bno\s+distant\s+mets\b/i.test(cleanText)) {
    exclusionStatus = "no distant metastasis";
  } else if (/\bno\s+(?:active\s+)?(?:brain|cns)\s+metastas(?:is|es)\b/i.test(cleanText)) {
    exclusionStatus = "no brain metastases";
  }

  // --------------------------------------------------------------------------
  // 7. Compose into ONE natural sentence in the SAMPLE_PROFILE style
  // --------------------------------------------------------------------------
  const clauses: string[] = [];

  if (demographicsPhrase) {
    clauses.push(demographicsPhrase);
  }

  if (diseasePhrase) {
    clauses.push(diseasePhrase);
  }

  if (biomarkers.length > 0) {
    clauses.push(biomarkers.join(", "));
  }

  if (therapies.length > 0) {
    clauses.push(therapies.join(", "));
  }

  if (exclusionStatus) {
    clauses.push(exclusionStatus);
  }

  if (clauses.length === 0) {
    return "";
  }

  let composed = clauses.join(", ").trim();

  // Ensure it ends with a single period
  if (!composed.endsWith(".")) {
    composed += ".";
  }

  // Capitalize the first letter if not already
  composed = composed.charAt(0).toUpperCase() + composed.slice(1);

  // Truncate to existing maxLength 4000
  return composed.slice(0, 4000);
}
