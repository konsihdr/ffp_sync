import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

interface CalendarEvent {
  summary: string;
  start: string;
  end: string;
  source_uid: string;
  is_youth_event: boolean;
}

function normalizeICSDate(raw: string): string {
  const value = raw.includes(":") ? raw.split(":").pop()! : raw;
  const v = value.trim();
  if (/^\d{8}T\d{6}Z$/.test(v)) {
    return `${v.slice(0,4)}-${v.slice(4,6)}-${v.slice(6,8)}T${v.slice(9,11)}:${v.slice(11,13)}:${v.slice(13,15)}+00:00`;
  }
  if (/^\d{8}T\d{6}$/.test(v)) {
    return `${v.slice(0,4)}-${v.slice(4,6)}-${v.slice(6,8)}T${v.slice(9,11)}:${v.slice(11,13)}:${v.slice(13,15)}`;
  }
  if (/^\d{8}$/.test(v)) {
    return `${v.slice(0,4)}-${v.slice(4,6)}-${v.slice(6,8)}`;
  }
  return v;
}

function extractProp(block: string, name: string): string {
  for (const line of block.split("\n")) {
    const t = line.trimEnd();
    if (t.startsWith(`${name}:`) || t.startsWith(`${name};`)) {
      return t.replace(/^[^:]+:/, "").trim();
    }
  }
  return "";
}

function parseICS(icsText: string): CalendarEvent[] {
  const unfolded = icsText.replace(/\r?\n[ \t]/g, "");
  const events: CalendarEvent[] = [];
  const re = /BEGIN:VEVENT([\s\S]*?)END:VEVENT/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(unfolded)) !== null) {
    const block = m[1];
    const summary = extractProp(block, "SUMMARY");
    const start = extractProp(block, "DTSTART");
    const end = extractProp(block, "DTEND");
    const uid = extractProp(block, "UID");
    const recId = extractProp(block, "RECURRENCE-ID");
    if (!summary || !start || !end) continue;
    const source_uid = recId ? `${uid}__${recId}` : uid;
    events.push({
      summary,
      start: normalizeICSDate(start),
      end: normalizeICSDate(end),
      source_uid,
      is_youth_event: summary.includes("Jugend"),
    });
  }
  return events;
}

Deno.serve(async (_req) => {
  try {
    const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
    const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
    const calendarUrl = Deno.env.get("CALENDAR_URL");

    if (!calendarUrl) {
      return json({ ok: false, error: "CALENDAR_URL secret not set" }, 500);
    }

    const supabase = createClient(supabaseUrl, serviceKey);

    const icsRes = await fetch(calendarUrl, { signal: AbortSignal.timeout(30_000) });
    if (!icsRes.ok) {
      throw new Error(`Calendar fetch failed: ${icsRes.status}`);
    }
    const icsText = await icsRes.text();
    const incoming = parseICS(icsText);

    const { data: existing, error: fetchErr } = await supabase
      .from("ffp_events")
      .select("id,source_uid,summary,start,end,is_youth_event");
    if (fetchErr) throw fetchErr;

    const byUid = new Map<string, Record<string, unknown>>();
    const byKey = new Map<string, Record<string, unknown>>();
    for (const row of existing ?? []) {
      if (row.source_uid) byUid.set(row.source_uid as string, row);
      byKey.set(`${row.summary}__${row.start}__${row.end}`, row);
    }

    let created = 0, updated = 0;

    for (const event of incoming) {
      const { source_uid, summary, start, end, is_youth_event } = event;
      const key = `${summary}__${start}__${end}`;
      const existing = source_uid ? byUid.get(source_uid) : undefined;

      if (existing) {
        if (
          existing.summary !== summary ||
          existing.start !== start ||
          existing.end !== end ||
          existing.is_youth_event !== is_youth_event
        ) {
          await supabase.from("ffp_events")
            .update({ summary, start, end, is_youth_event, source_uid })
            .eq("id", existing.id);
          updated++;
        }
      } else {
        const keyMatch = byKey.get(key);
        if (keyMatch && !keyMatch.source_uid) {
          await supabase.from("ffp_events")
            .update({ source_uid, is_youth_event })
            .eq("id", keyMatch.id);
          keyMatch.source_uid = source_uid;
          if (source_uid) byUid.set(source_uid, keyMatch);
          updated++;
        } else if (!keyMatch) {
          const { data: newRow } = await supabase.from("ffp_events")
            .insert(event).select().single();
          if (newRow) {
            byKey.set(key, newRow);
            if (source_uid) byUid.set(source_uid, newRow);
          }
          created++;
        }
      }
    }

    console.log(`sync-calendar: ${created} created, ${updated} updated`);
    return json({ ok: true, created, updated });
  } catch (err) {
    console.error("sync-calendar error:", err);
    return json({ ok: false, error: String(err) }, 500);
  }
});

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
