export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL;

export async function uploadImage(file: File) {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${API_BASE_URL}/upload`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) throw new Error("Upload failed");
  return res.json();
}
