import type { Attachment } from "./types";

export const MAX_IMAGES = 6;

/** Thrown with the backend's code (too_large, unsupported, not_an_image...) or "network". */
export class UploadError extends Error {
  readonly code: string;

  constructor(code: string) {
    super(code);
    this.name = "UploadError";
    this.code = code;
  }
}

/** POST /api/uploads: the server strips EXIF/location, converts HEIC and scales down. */
export async function uploadImages(files: File[], signal?: AbortSignal): Promise<Attachment[]> {
  const form = new FormData();
  for (const file of files) form.append("files", file, file.name || "image");
  let response: Response;
  try {
    response = await fetch("/api/uploads", { method: "POST", body: form, signal });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new UploadError("network");
  }
  if (!response.ok) {
    let code = "upload_failed";
    try {
      const body = (await response.json()) as { detail?: { code?: string } };
      code = body.detail?.code ?? code;
    } catch {
      // not JSON: keep the generic code
    }
    throw new UploadError(code);
  }
  return ((await response.json()) as { attachments: Attachment[] }).attachments;
}

/** Image files out of a paste / drop / file picker (HEIC included: browsers often leave
 * its type empty, so the extension decides). */
/** Images (HEIC too), PDFs (syllabi, lecture notes) and CSVs (Meta Ads Manager exports,
 * for Metrics); anything else is ignored. */
export function attachableFiles(list: FileList | File[] | null | undefined): File[] {
  return Array.from(list ?? []).filter(
    (file) =>
      file.type.startsWith("image/") ||
      /\.(heic|heif)$/i.test(file.name) ||
      documentKind(file.type) !== null ||
      documentKind(file.name) !== null,
  );
}

export function isPdf(mimeOrName: string): boolean {
  return documentKind(mimeOrName) === "PDF";
}

/** "PDF" / "CSV" for a document attachment (by type or file name), null for an image. */
export function documentKind(mimeOrName: string): "PDF" | "CSV" | null {
  if (mimeOrName === "application/pdf" || /\.pdf$/i.test(mimeOrName)) return "PDF";
  if (mimeOrName === "text/csv" || /\.csv$/i.test(mimeOrName)) return "CSV";
  return null;
}
