import { describe, it, expect, vi } from "vitest";
import React from "react";
import "@testing-library/jest-dom/vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ProfileForm, SAMPLE_PROFILE } from "./ProfileForm";

const EXPECTED_SAMPLE_PROFILE = SAMPLE_PROFILE;

describe("ProfileForm Regression & Integration Tests", () => {
  it("disables the submit button initially when textarea is empty", () => {
    render(<ProfileForm onSubmit={vi.fn()} isSubmitting={false} />);
    const submitBtn = screen.getByRole("button", { name: /find matching trials/i });
    expect(submitBtn).toBeDisabled();
  });

  it("updates textarea and enables submit button when typing manually", async () => {
    const user = userEvent.setup();
    const onSubmitMock = vi.fn();
    render(<ProfileForm onSubmit={onSubmitMock} isSubmitting={false} />);

    const textarea = screen.getByLabelText(/describe the patient/i);
    const submitBtn = screen.getByRole("button", { name: /find matching trials/i });

    expect(submitBtn).toBeDisabled();

    await user.type(textarea, "55-year-old male with Stage IV melanoma");

    expect(textarea).toHaveValue("55-year-old male with Stage IV melanoma");
    expect(submitBtn).toBeEnabled();

    await user.click(submitBtn);
    expect(onSubmitMock).toHaveBeenCalledWith("55-year-old male with Stage IV melanoma");
  });

  it("'Use a sample profile' button fills textarea with exact SAMPLE_PROFILE and enables submit button", async () => {
    const user = userEvent.setup();
    const onSubmitMock = vi.fn();
    render(<ProfileForm onSubmit={onSubmitMock} isSubmitting={false} />);

    const sampleBtn = screen.getByRole("button", { name: /use a sample profile/i });
    const submitBtn = screen.getByRole("button", { name: /find matching trials/i });
    const textarea = screen.getByLabelText(/describe the patient/i);

    await user.click(sampleBtn);

    expect(textarea).toHaveValue(EXPECTED_SAMPLE_PROFILE);
    expect(submitBtn).toBeEnabled();

    await user.click(submitBtn);
    expect(onSubmitMock).toHaveBeenCalledWith(EXPECTED_SAMPLE_PROFILE);
  });

  it("populates the same textarea through document upload and enables the submit button", async () => {
    const onSubmitMock = vi.fn();
    render(<ProfileForm onSubmit={onSubmitMock} isSubmitting={false} />);

    const textarea = screen.getByLabelText(/describe the patient/i);
    const submitBtn = screen.getByRole("button", { name: /find matching trials/i });

    expect(textarea).toHaveValue("");
    expect(submitBtn).toBeDisabled();

    // Upload a clinical note via the embedded dropzone
    const clinicalText =
      "Patient is a 58 yo male with Stage II colon adenocarcinoma who received prior chemotherapy.";
    const file = new File([clinicalText], "clinic_note.txt", { type: "text/plain" });

    const fileInput = screen.getByTestId("document-file-input");
    fireEvent.change(fileInput, { target: { files: [file] } });

    // Verify textarea receives extracted text
    await waitFor(() => {
      expect((textarea as HTMLTextAreaElement).value).toContain("58-year-old male");
    });

    expect((textarea as HTMLTextAreaElement).value).toContain("Stage II colon adenocarcinoma");
    expect((textarea as HTMLTextAreaElement).value).toContain("prior chemotherapy");
    expect(submitBtn).toBeEnabled();

    // Clinician can edit the populated text before submitting (human-in-the-loop)
    fireEvent.change(textarea, { target: { value: (textarea as HTMLTextAreaElement).value + " Additional note." } });
    expect((textarea as HTMLTextAreaElement).value).toContain("Additional note.");

    fireEvent.click(submitBtn);
    expect(onSubmitMock).toHaveBeenCalledTimes(1);
    expect(onSubmitMock.mock.calls[0][0]).toContain("Additional note.");
  });

  it("converges all three input methods (typing, sample button, document upload) on the single state variable", async () => {
    const user = userEvent.setup();
    render(<ProfileForm onSubmit={vi.fn()} isSubmitting={false} />);

    const textarea = screen.getByLabelText(/describe the patient/i);
    const sampleBtn = screen.getByRole("button", { name: /use a sample profile/i });

    // 1. First input method: Type
    await user.type(textarea, "Initial typed text.");
    expect(textarea).toHaveValue("Initial typed text.");

    // 2. Second input method: Sample button overwrites
    await user.click(sampleBtn);
    expect(textarea).toHaveValue(EXPECTED_SAMPLE_PROFILE);

    // 3. Third input method: Document upload overwrites
    const uploadText = "45-year-old female, Stage I breast cancer.";
    const file = new File([uploadText], "doc.txt", { type: "text/plain" });
    const fileInput = screen.getByTestId("document-file-input");
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(textarea).toHaveValue("45-year-old female, Stage I breast cancer.");
    });
  });

  it("disables textarea, buttons, and dropzone when isSubmitting is true", () => {
    render(<ProfileForm onSubmit={vi.fn()} isSubmitting={true} />);

    const textarea = screen.getByLabelText(/describe the patient/i);
    const sampleBtn = screen.getByRole("button", { name: /use a sample profile/i });
    const submitBtn = screen.getByRole("button", { name: /finding trials…/i });
    const fileInput = screen.getByTestId("document-file-input");

    expect(textarea).toBeDisabled();
    expect(sampleBtn).toBeDisabled();
    expect(submitBtn).toBeDisabled();
    expect(fileInput).toBeDisabled();
  });
});
