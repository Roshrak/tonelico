---
name: scrapegraph
description: "Scrape and extract structured data (prices, specs, articles, tables) from any URL using ScrapeGraphAI."
version: 1.0.0
author: Antigravity & Hermes
platforms: [linux]
metadata:
  hermes:
    tags: [scraping, web, extraction, scrapegraphai, crawler]
---

# ScrapeGraphAI Web Extraction Skill

Use this skill whenever:
1. The user shares a URL to scrape, extract, or parse (e.g., "cào link này", "scrape this link", "trích xuất thông tin từ URL", "lấy giá sản phẩm...").
2. The user sends a raw URL asking questions about its contents, prices, specs, or summaries.

## Execution Command:
Invoke the scraper using the `terminal` tool:

```bash
/home/aesc/.hermes/bin/scrape_link "<URL>" "<EXTRACTION_PROMPT>"
```

### Parameters:
- `<URL>`: The full web link provided by the user.
- `<EXTRACTION_PROMPT>`: Clear description of what needs to be extracted (e.g., "Extract product title, price, discount, specifications, and availability", or "Extract key article takeaways and author").

## Response Guidelines:
1. Parse the JSON returned by the scraper.
2. Format the response cleanly for Telegram using emojis, bullet points, or tables.
3. If the scraper returns prices or deals, present exact numbers, conditions, and currency.
