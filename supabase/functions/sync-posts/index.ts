import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const MEDIA_EXT: Record<string, string> = {
  "image/jpeg": "jpg",
  "image/jpg": "jpg",
  "image/png": "png",
  "image/webp": "webp",
  "video/mp4": "mp4",
  "video/quicktime": "mov",
};

function parsePostDate(ts: string): string {
  if (!ts) return new Date().toISOString().slice(0, 10);
  try {
    if (ts.includes("T")) return new Date(ts).toISOString().slice(0, 10);
    if (/^\d+$/.test(ts)) return new Date(parseInt(ts) * 1000).toISOString().slice(0, 10);
    return ts.slice(0, 10);
  } catch {
    return new Date().toISOString().slice(0, 10);
  }
}

function ext(contentType: string, fallback: string): string {
  return MEDIA_EXT[contentType] ?? fallback;
}

async function tryUpload(
  supabase: ReturnType<typeof createClient>,
  bucket: string,
  shortCode: string,
  url: string,
  timeout: number,
  defaultExt: string,
): Promise<{ path: string; publicUrl: string; mediaType: string } | null> {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(timeout) });
    if (!res.ok) return null;
    const contentType = (res.headers.get("Content-Type") ?? "").split(";")[0].trim();
    const fileExt = ext(contentType || `image/${defaultExt}`, defaultExt);
    const ts = new Date().toISOString().replace(/[:.]/g, "").slice(0, 15);
    const path = `posts/${shortCode}_${ts}.${fileExt}`;
    const bytes = await res.arrayBuffer();
    const { error } = await supabase.storage.from(bucket).upload(path, bytes, { contentType });
    if (error) {
      console.warn(`Storage upload failed for ${shortCode}:`, error.message);
      return null;
    }
    const { data: urlData } = supabase.storage.from(bucket).getPublicUrl(path);
    const mediaType = contentType.startsWith("video") ? "video" : "image";
    return { path, publicUrl: urlData.publicUrl, mediaType };
  } catch (err) {
    console.warn(`Media fetch/upload failed for ${shortCode}:`, err);
    return null;
  }
}

Deno.serve(async (_req) => {
  try {
    const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
    const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
    const apifyToken = Deno.env.get("APIFY_TOKEN");
    const bucket = Deno.env.get("SUPABASE_STORAGE_BUCKET") ?? "ffp-posts";

    if (!apifyToken) {
      return json({ ok: false, error: "APIFY_TOKEN secret not set" }, 500);
    }

    const supabase = createClient(supabaseUrl, serviceKey);

    const apifyUrl =
      `https://api.apify.com/v2/actor-tasks/konsihdr~instagram-scraper-task/run-sync-get-dataset-items?token=${apifyToken}`;
    const apifyRes = await fetch(apifyUrl, { signal: AbortSignal.timeout(90_000) });
    if (!apifyRes.ok) throw new Error(`Apify error: ${apifyRes.status}`);

    const data: unknown[] = await apifyRes.json();

    if (!Array.isArray(data) || data.length === 0) {
      return json({ ok: true, message: "No data from Apify" });
    }

    const first = data[0] as Record<string, unknown>;
    if (first?.error === "no_items") {
      return json({ ok: true, message: "No new Instagram items" });
    }

    const { data: existing } = await supabase.from("ffp_posts").select("short_code");
    const knownCodes = new Set((existing ?? []).map((r: Record<string, unknown>) => r.short_code as string));

    let saved = 0, skipped = 0, errors = 0;

    for (const raw of data) {
      const post = raw as Record<string, unknown>;
      const shortCode = ((post.shortCode ?? post.short_code ?? "") as string).trim();
      if (!shortCode) { skipped++; continue; }
      if (knownCodes.has(shortCode)) { skipped++; continue; }

      let mediaUrl = (post.displayUrl ?? post.url ?? "") as string;
      let mediaPath = "";
      let mediaType = "";

      // Prefer video, fall back to image
      const videoUrl = (post.videoUrl ?? "") as string;
      const imageUrl = (post.displayUrl ?? "") as string;

      const uploaded =
        (videoUrl ? await tryUpload(supabase, bucket, shortCode, videoUrl, 60_000, "mp4") : null) ??
        (imageUrl ? await tryUpload(supabase, bucket, shortCode, imageUrl, 30_000, "jpg") : null);

      if (uploaded) {
        mediaUrl = uploaded.publicUrl;
        mediaPath = uploaded.path;
        mediaType = uploaded.mediaType;
      }

      const { error: insertErr } = await supabase.from("ffp_posts").insert({
        short_code: shortCode,
        alt: (post.alt ?? "") as string,
        caption: (post.caption ?? "") as string,
        url: (post.url ?? "") as string,
        display_url: mediaUrl,
        media_url: mediaUrl,
        media_path: mediaPath,
        media_type: mediaType || null,
        post_date: parsePostDate((post.timestamp ?? "") as string),
      });

      if (insertErr) {
        console.error(`Insert failed for ${shortCode}:`, insertErr.message);
        errors++;
      } else {
        knownCodes.add(shortCode);
        saved++;
      }
    }

    console.log(`sync-posts: ${saved} saved, ${skipped} skipped, ${errors} errors`);
    return json({ ok: true, saved, skipped, errors });
  } catch (err) {
    console.error("sync-posts error:", err);
    return json({ ok: false, error: String(err) }, 500);
  }
});

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
