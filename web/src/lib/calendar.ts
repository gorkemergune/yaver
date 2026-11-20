/** The secret calendar URL for the iPhone (Takvim aboneliği): https://... and webcal://... */
export function subscriptionUrls(origin: string, path: string): { webcal: string; https: string } {
  const https = `${origin}${path}`;
  return { https, webcal: https.replace(/^https?:\/\//, "webcal://") };
}
