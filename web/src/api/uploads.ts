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
export function imageFiles(list: FileList | File[] | null | undefined): File[] {
  return Array.from(list ?? []).filter(
    (file) => file.type.startsWith("image/") || /\.(heic|heif)$/i.test(file.name),
  );
}
