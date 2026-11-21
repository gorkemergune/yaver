import { describe, expect, it } from "vitest";

import { attachableFiles, documentKind, isPdf } from "./uploads";

function file(name: string, type: string): File {
  return new File(["x"], name, { type });
}

describe("attachments", () => {
  it("keeps images, PDFs and ad report CSVs, drops the rest", () => {
    const kept = attachableFiles([
      file("foto.jpg", "image/jpeg"),
      file("IMG_1.HEIC", ""),
      file("syllabus.pdf", "application/pdf"),
      file("Kampanyalar.csv", "text/csv"),
      file("export.CSV", "application/vnd.ms-excel"),
      file("notlar.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ]).map((f) => f.name);

    expect(kept).toEqual(["foto.jpg", "IMG_1.HEIC", "syllabus.pdf", "Kampanyalar.csv", "export.CSV"]);
  });

  it("tells documents from images", () => {
    expect(documentKind("application/pdf")).toBe("PDF");
    expect(documentKind("rapor.csv")).toBe("CSV");
    expect(documentKind("image/png")).toBeNull();
    expect(isPdf("a.PDF")).toBe(true);
    expect(isPdf("a.csv")).toBe(false);
  });
});
