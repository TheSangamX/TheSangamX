// Keeps two README sections in step with sangamgupta.in, so the profile never goes stale:
//   <!-- WRITING:START --> ... <!-- WRITING:END -->  newest posts from https://www.sangamgupta.in/feed.xml
//   <!-- SKILLS:START -->  ... <!-- SKILLS:END -->   my skills from https://www.sangamgupta.in/resume.json
// Run by .github/workflows/sync-site.yml once a day. Exits 0 without changes if the site can't be reached.
import { readFileSync, writeFileSync } from "node:fs";

const SITE = process.env.SITE ?? "https://www.sangamgupta.in"; // SITE overrides the host for local tests
const readme = readFileSync("README.md", "utf8");

const get = async (path) => {
  const res = await fetch(`${SITE}${path}`, { headers: { "user-agent": "TheSangamX-profile-sync" }, signal: AbortSignal.timeout(20000) });
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return res.text();
};
const decode = (s) => s.replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;|&#x27;/g, "'").trim();
const replace = (text, name, body) => {
  const re = new RegExp(`(<!-- ${name}:START -->)[\\s\\S]*?(<!-- ${name}:END -->)`);
  if (!re.test(text)) throw new Error(`README has no ${name} markers`);
  return text.replace(re, `$1\n${body}\n$2`);
};

async function writing() {
  const xml = await get("/feed.xml");
  const items = [...xml.matchAll(/<item>([\s\S]*?)<\/item>/g)].slice(0, 5).map(([, item]) => {
    const tag = (t) => decode(item.match(new RegExp(`<${t}>([\\s\\S]*?)</${t}>`))?.[1] ?? "");
    const date = new Date(tag("pubDate"));
    return { title: tag("title"), link: tag("link"), summary: tag("description"), date: isNaN(date) ? "" : date.toISOString().slice(0, 10) };
  });
  if (!items.length) throw new Error("feed has no posts");
  return items.map((p) => `- **[${p.title}](${p.link})**${p.date ? ` <sub>${p.date}</sub>` : ""}<br/>${p.summary}`).join("\n");
}

async function skills() {
  const resume = JSON.parse(await get("/resume.json"));
  const groups = (resume.skills ?? []).filter((g) => g.name && g.keywords?.length);
  if (!groups.length) throw new Error("resume.json has no skills");
  const yaml = groups.map((g) => `${g.name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "")}:\n${g.keywords.map((k) => `  - ${k}`).join("\n")}`).join("\n\n");
  return "```yaml\n" + yaml + "\n```";
}

let next = readme;
for (const [name, build] of [["WRITING", writing], ["SKILLS", skills]]) {
  try {
    next = replace(next, name, await build());
  } catch (e) {
    console.log(`::warning::${name} not updated: ${e.message}`);
  }
}
if (next !== readme) {
  writeFileSync("README.md", next);
  console.log("README updated from sangamgupta.in");
} else {
  console.log("README already in step with sangamgupta.in");
}
