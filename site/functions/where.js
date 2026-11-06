// Answers with the visitor's city and country code, which Cloudflare derives from their IP address.
export const onRequestGet = ({ request }) =>
  Response.json(
    { city: request.cf?.city ?? null, country: request.cf?.country ?? null },
    { headers: { 'cache-control': 'private, no-store' } },
  );
