"use client";

import React, { useState, useRef } from "react";
import { parseClinicalDocument } from "@/lib/clinicalParser";

const MAX_FILE_SIZE_BYTES = 15 * 1024 * 1024; // 15MB
const ACCEPTED_EXTENSIONS = [".pdf", ".docx", ".txt"];

interface DocumentDropzoneProps {
  onExtracted: (composedText: string) => void;
  disabled?: boolean;
}

type DropzoneState =
  | { status: "idle" }
  | { status: "parsing"; fileName: string }
  | { status: "success"; fileName: string; fileSize: string }
  | { status: "error"; message: string };

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function DocumentDropzone({ onExtracted, disabled = false }: DocumentDropzoneProps) {
  const [state, setState] = useState<DropzoneState>({ status: "idle" });
  const [isDragOver, setIsDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function processFile(file: File) {
    // 1. Validation: Size check
    if (file.size > MAX_FILE_SIZE_BYTES) {
      setState({
        status: "error",
        message: `File exceeds the 15MB limit (${formatFileSize(file.size)}). Please choose a smaller file.`,
      });
      return;
    }

    const lowerName = file.name.toLowerCase();
    const isPdf = lowerName.endsWith(".pdf");
    const isDocx = lowerName.endsWith(".docx");
    const isTxt = lowerName.endsWith(".txt");

    if (!isPdf && !isDocx && !isTxt) {
      setState({
        status: "error",
        message: "Unsupported file type. Please upload a PDF (.pdf), Word document (.docx), or plain text (.txt).",
      });
      return;
    }

    setState({ status: "parsing", fileName: file.name });

    try {
      let rawText = "";

      if (isTxt) {
        rawText = await file.text();
      } else if (isDocx) {
        // Dynamic import so mammoth is excluded from SSR bundle
        const mammoth = await import("mammoth");
        const arrayBuffer = await file.arrayBuffer();
        const result = await mammoth.extractRawText({ arrayBuffer });
        rawText = result.value;
      } else if (isPdf) {
        // Dynamic import so pdfjs-dist is excluded from SSR bundle
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";
        const arrayBuffer = await file.arrayBuffer();
        const loadingTask = pdfjs.getDocument({ data: new Uint8Array(arrayBuffer) });
        const pdfDoc = await loadingTask.promise;
        const pageTexts: string[] = [];

        for (let i = 1; i <= pdfDoc.numPages; i++) {
          const page = await pdfDoc.getPage(i);
          const textContent = await page.getTextContent();
          const pageStr = textContent.items
            .map((item: any) => ("str" in item ? item.str : ""))
            .join(" ");
          pageTexts.push(pageStr);
        }
        rawText = pageTexts.join("\n");
      }

      if (!rawText || rawText.trim().length === 0) {
        setState({
          status: "error",
          message: "No readable text could be found in this document. It may be an image-only scan or empty.",
        });
        return;
      }

      const composed = parseClinicalDocument(rawText);

      if (!composed || composed.trim().length === 0) {
        setState({
          status: "error",
          message: "Could not extract clinical details (e.g. diagnosis, stage, or biomarkers) from this document.",
        });
        return;
      }

      // Populate ProfileForm state (Human-in-the-loop: clinician can review and edit before submitting)
      onExtracted(composed);

      setState({
        status: "success",
        fileName: file.name,
        fileSize: formatFileSize(file.size),
      });
    } catch (err: any) {
      console.error("Document parsing failed:", err);
      const isPassword = err?.name === "PasswordException" || /password/i.test(err?.message || "");
      setState({
        status: "error",
        message: isPassword
          ? "This document is password-protected and cannot be opened."
          : "Unable to read document. The file may be corrupt or unreadable.",
      });
    }
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files;
    if (files && files.length > 0) {
      processFile(files[0]);
    }
    // Reset input so the user can re-select the same file if desired
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  }

  function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setIsDragOver(false);
    if (disabled || state.status === "parsing") return;

    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      processFile(e.dataTransfer.files[0]);
    }
  }

  function handleDragOver(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    if (!disabled && state.status !== "parsing") {
      setIsDragOver(true);
    }
  }

  function handleDragLeave(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setIsDragOver(false);
  }

  function handleClear() {
    setState({ status: "idle" });
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  }

  function handleTriggerUpload() {
    if (disabled || state.status === "parsing") return;
    fileInputRef.current?.click();
  }

  return (
    <div className="mb-4">
      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"
        onChange={handleFileChange}
        disabled={disabled || state.status === "parsing"}
        className="hidden"
        data-testid="document-file-input"
      />

      {state.status === "idle" && (
        <div
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onClick={handleTriggerUpload}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              handleTriggerUpload();
            }
          }}
          aria-label="Upload clinical document"
          className={`flex cursor-pointer flex-col items-center justify-center rounded-sm border-2 border-dashed p-4 text-center transition-colors ${
            isDragOver
              ? "border-accent bg-accent-soft/30"
              : "border-border bg-bg/50 hover:border-accent hover:bg-bg"
          } ${disabled ? "cursor-not-allowed opacity-50" : ""}`}
        >
          <svg
            className="h-6 w-6 text-muted"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
            />
          </svg>
          <p className="mt-2 text-sm font-medium text-ink">
            Drop clinical document here, or{" "}
            <span className="text-accent underline decoration-accent-soft underline-offset-2">browse</span>
          </p>
          <p className="mt-1 text-xs text-muted">Supports PDF, Word (.docx), or TXT (up to 15MB)</p>
        </div>
      )}

      {state.status === "parsing" && (
        <div
          className="flex items-center justify-center gap-3 rounded-sm border border-border bg-surface p-4 text-sm text-ink"
          role="status"
        >
          <svg
            className="h-5 w-5 animate-spin text-accent"
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
          </svg>
          <span>Extracting clinical profile from <strong className="font-semibold">{state.fileName}</strong>…</span>
        </div>
      )}

      {state.status === "success" && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-sm border border-match/30 bg-match-soft/40 p-3 text-sm">
          <div className="flex items-center gap-2">
            <svg
              className="h-4 w-4 text-match shrink-0"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
            <span className="text-ink">
              Extracted from <strong className="font-medium text-ink">{state.fileName}</strong> ({state.fileSize})
            </span>
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={handleTriggerUpload}
              disabled={disabled}
              className="text-xs font-medium text-accent underline decoration-accent-soft underline-offset-2 hover:decoration-accent disabled:opacity-50"
            >
              Re-upload
            </button>
            <button
              type="button"
              onClick={handleClear}
              disabled={disabled}
              className="text-xs text-muted hover:text-ink disabled:opacity-50"
            >
              Clear
            </button>
          </div>
        </div>
      )}

      {state.status === "error" && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-sm border border-nomatch/30 bg-nomatch-soft p-3 text-sm text-nomatch">
          <div className="flex items-center gap-2">
            <svg
              className="h-4 w-4 text-nomatch shrink-0"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <span className="text-ink">{state.message}</span>
          </div>
          <button
            type="button"
            onClick={handleClear}
            className="text-xs font-medium text-nomatch underline underline-offset-2 hover:text-nomatch/80"
          >
            Dismiss
          </button>
        </div>
      )}
    </div>
  );
}

export default DocumentDropzone;
