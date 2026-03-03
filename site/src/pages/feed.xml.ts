import { getCollection } from 'astro:content';

export async function GET() {
  const posts = (await getCollection('blog'))
    .filter(post => !post.data.draft)
    .sort((a, b) => b.data.date.getTime() - a.data.date.getTime());

  const site = 'https://bubblestone.ai';
  const now = new Date().toUTCString();

  const items = posts.map(post => `
    <item>
      <title><![CDATA[${post.data.title}]]></title>
      <link>${site}/blog/${post.slug}/</link>
      <guid isPermaLink="true">${site}/blog/${post.slug}/</guid>
      <description><![CDATA[${post.data.description}]]></description>
      <pubDate>${post.data.date.toUTCString()}</pubDate>
      <author>florent.coulon@bubblestone.ai (Florent Coulon)</author>
      ${post.data.tags.map(tag => `<category>${tag}</category>`).join('\n      ')}
    </item>`).join('');

  const rss = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>BubbleStone AI — Blog</title>
    <link>${site}/blog/</link>
    <description>Articles, analyses et études de cas sur l'intégration de l'IA en entreprise. Automatisation, agents IA, infrastructure cloud.</description>
    <language>fr-FR</language>
    <lastBuildDate>${now}</lastBuildDate>
    <atom:link href="${site}/feed.xml" rel="self" type="application/rss+xml" />
    <image>
      <url>${site}/logo.png</url>
      <title>BubbleStone AI</title>
      <link>${site}</link>
    </image>
    ${items}
  </channel>
</rss>`;

  return new Response(rss.trim(), {
    headers: { 'Content-Type': 'application/xml; charset=utf-8' }
  });
}
