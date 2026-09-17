import { describe, it, expect, vi } from "vitest";
import React from "react";
import "@testing-library/jest-dom/vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { DocumentDropzone } from "./DocumentDropzone";

describe("DocumentDropzone Component", () => {
  it("extracts clinical text from a valid .txt file and fires onExtracted", async () => {
    const onExtractedMock = vi.fn();
    render(<DocumentDropzone onExtracted={onExtractedMock} />);

    const sampleContent =
      "64-year-old female diagnosed with Stage III esophageal squamous cell carcinoma. " +
      "Completed neoadjuvant chemoradiation. PD-L1 positive. No distant metastasis.";

    const file = new File([sampleContent], "pathology_report.txt", { type: "text/plain" });
    const fileInput = screen.getByTestId("document-file-input");

    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(onExtractedMock).toHaveBeenCalledTimes(1);
    });

    const extractedText = onExtractedMock.mock.calls[0][0];
    expect(extractedText).toContain("64-year-old female");
    expect(extractedText).toContain("Stage III esophageal squamous cell carcinoma");
    expect(extractedText).toContain("completed neoadjuvant chemoradiation");

    // Success UI is displayed with filename
    expect(await screen.findByText(/Extracted from/i)).toBeInTheDocument();
    expect(screen.getByText("pathology_report.txt")).toBeInTheDocument();
  });

  it("rejects an oversized file (>15MB), displays an error, and does NOT call onExtracted", async () => {
    const onExtractedMock = vi.fn();
    render(<DocumentDropzone onExtracted={onExtractedMock} />);

    const file = new File(["tiny payload"], "large_archive.pdf", { type: "application/pdf" });
    // Mock file size to 16MB (exceeding 15MB limit)
    Object.defineProperty(file, "size", { value: 16 * 1024 * 1024, configurable: true });

    const fileInput = screen.getByTestId("document-file-input");
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText(/File exceeds the 15MB limit/i)).toBeInTheDocument();
    });

    expect(onExtractedMock).not.toHaveBeenCalled();
  });

  it("handles empty / unextractable file gracefully with error banner and no crash", async () => {
    const onExtractedMock = vi.fn();
    render(<DocumentDropzone onExtracted={onExtractedMock} />);

    const file = new File(["This is just random text with no clinical terms whatsoever."], "random.txt", {
      type: "text/plain",
    });

    const fileInput = screen.getByTestId("document-file-input");
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(
        screen.getByText(/Could not extract clinical details/i)
      ).toBeInTheDocument();
    });

    expect(onExtractedMock).not.toHaveBeenCalled();
  });

  it("handles corrupt / failing file reading gracefully without throwing an uncaught exception", async () => {
    const onExtractedMock = vi.fn();
    render(<DocumentDropzone onExtracted={onExtractedMock} />);

    const file = new File(["test"], "corrupt.txt", { type: "text/plain" });
    vi.spyOn(file, "text").mockRejectedValue(new Error("Simulated I/O failure"));

    const fileInput = screen.getByTestId("document-file-input");
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText(/Unable to read document/i)).toBeInTheDocument();
    });

    expect(onExtractedMock).not.toHaveBeenCalled();
  });

  it("rejects unsupported file formats gracefully", async () => {
    const onExtractedMock = vi.fn();
    render(<DocumentDropzone onExtracted={onExtractedMock} />);

    const file = new File(["data"], "scan.jpg", { type: "image/jpeg" });
    const fileInput = screen.getByTestId("document-file-input");
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText(/Unsupported file type/i)).toBeInTheDocument();
    });

    expect(onExtractedMock).not.toHaveBeenCalled();
  });

  it("disables file input and dropzone when disabled prop is true", () => {
    render(<DocumentDropzone onExtracted={vi.fn()} disabled={true} />);
    const fileInput = screen.getByTestId("document-file-input") as HTMLInputElement;
    expect(fileInput.disabled).toBe(true);
  });
});
