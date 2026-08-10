// scripts/prepare.js
// تحضير مسبق (offline) لفصول محددة يدويًا — يعمل فقط عند تشغيله يدويًا (workflow_dispatch)
// ولا يعمل بجدولة تلقائية أو استخراج جماعي لمكتبة كاملة، بما يتوافق مع النطاق المتفق عليه.

const { chromium } = require('playwright');
const sharp = require('sharp');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const MAX_CHAPTERS_PER_RUN = 10;
const WIDTH = parseInt(process.env.IMG_WIDTH || '800', 10);
const QUALITY = parseInt(process.env.IMG_QUALITY || '65', 10);
const NAV_TIMEOUT_MS = 45000;
const OUT_ROOT = path.join(__dirname, '..', 'docs');

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36';

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function slugForUrl(url) {
  try {
    const u = new URL(url);
    const parts = u.pathname.split('/').filter(Boolean);
    const tail = parts.slice(-2).join('-').toLowerCase()
      .replace(/[^a-z0-9\-]+/g, '-').replace(/-+/g, '-').replace(/(^-|-$)/g, '');
    const hash = crypto.createHash('md5').update(url).digest('hex').slice(0, 8);
    return (tail || 'chapter') + '-' + hash;
  } catch {
    return crypto.createHash('md5').update(url).digest('hex');
  }
}

// نفس منطق تصفية الصور غير المرغوبة الموجود بالتطبيق الأصلي (شعارات/أيقونات/صور بديلة)
function isJunkImageUrl(u) {
  return /logo|icon|avatar|sprite|placeholder|loading\.gif|banner-ad/i.test(u);
}

async function extractImageUrls(page) {
  // تمرير تدريجي لتفعيل أي صور بتحميل كسول (lazy load) قبل الاستخراج
  await page.evaluate(async () => {
    await new Promise((resolve) => {
      let total = 0;
      const step = 600;
      const timer = setInterval(() => {
        window.scrollBy(0, step);
        total += step;
        if (total >= document.body.scrollHeight) {
          clearInterval(timer);
          resolve();
        }
      }, 120);
    });
  });
  await page.waitForTimeout(1200);

  const urls = await page.evaluate(() => {
    const set = new Set();
    // 1) أي <img> ظاهرة فعليًا بالـ DOM بعد تنفيذ الجافاسكربت (يشمل lazy-load المحلولة)
    document.querySelectorAll('img').forEach(img => {
      const src = img.currentSrc || img.src;
      if (src && !src.startsWith('data:')) set.add(src);
    });
    // 2) احتياطي: أي <noscript> متبقٍ يحوي صور لم تُفعَّل
    document.querySelectorAll('noscript').forEach(ns => {
      const tmp = document.createElement('div');
      tmp.innerHTML = ns.textContent || '';
      tmp.querySelectorAll('img').forEach(img => {
        const src = img.getAttribute('src');
        if (src && !src.startsWith('data:')) set.add(src);
      });
    });
    return [...set];
  });

  return urls.filter(u => !isJunkImageUrl(u));
}

async function downloadAndCompress(context, imgUrl, referer, outPath) {
  const res = await context.request.get(imgUrl, {
    headers: { referer },
    timeout: 30000,
  });
  if (!res.ok()) throw new Error('HTTP ' + res.status() + ' عند تنزيل ' + imgUrl);
  const buffer = await res.body();

  const meta = await sharp(buffer).metadata();
  let pipeline = sharp(buffer);
  if (meta.width && meta.width > WIDTH) {
    pipeline = pipeline.resize({ width: WIDTH });
  }
  const outBuffer = await pipeline.webp({ quality: QUALITY }).toBuffer();
  fs.writeFileSync(outPath, outBuffer);
  return { originalBytes: buffer.length, compressedBytes: outBuffer.length };
}

async function processChapter(browser, chapterUrl) {
  const slug = slugForUrl(chapterUrl);
  const outDir = path.join(OUT_ROOT, slug);
  fs.mkdirSync(outDir, { recursive: true });

  const context = await browser.newContext({
    userAgent: UA,
    viewport: { width: 1280, height: 1800 },
  });
  const page = await context.newPage();

  console.log('→ فتح الفصل:', chapterUrl);
  await page.goto(chapterUrl, { waitUntil: 'networkidle', timeout: NAV_TIMEOUT_MS }).catch(async () => {
    // بعض المواقع لا تصل أبدًا لحالة networkidle الكاملة بسبب طلبات دائمة بالخلفية؛
    // نكتفي بحالة تحميل أضعف كخطة بديلة
    await page.goto(chapterUrl, { waitUntil: 'domcontentloaded', timeout: NAV_TIMEOUT_MS });
  });

  const imageUrls = await extractImageUrls(page);
  console.log('  تم العثور على', imageUrls.length, 'صورة');

  if (imageUrls.length === 0) {
    await context.close();
    return { chapterUrl, slug, status: 'no-images', imageCount: 0 };
  }

  let totalOriginal = 0;
  let totalCompressed = 0;
  let index = 1;
  for (const imgUrl of imageUrls) {
    const fileName = String(index).padStart(3, '0') + '.webp';
    const outPath = path.join(outDir, fileName);
    try {
      const { originalBytes, compressedBytes } = await downloadAndCompress(context, imgUrl, chapterUrl, outPath);
      totalOriginal += originalBytes;
      totalCompressed += compressedBytes;
      index++;
    } catch (err) {
      console.warn('  تعذّر تنزيل/ضغط صورة:', imgUrl, '-', err.message);
    }
    await sleep(300 + Math.random() * 400); // فاصل زمني لطيف بين كل صورة والتالية
  }

  await context.close();

  const chapterManifest = {
    sourceUrl: chapterUrl,
    imageCount: index - 1,
    originalBytes: totalOriginal,
    compressedBytes: totalCompressed,
    preparedAt: new Date().toISOString(),
  };
  fs.writeFileSync(path.join(outDir, 'manifest.json'), JSON.stringify(chapterManifest, null, 2));

  return { chapterUrl, slug, status: 'ok', imageCount: index - 1, totalOriginal, totalCompressed };
}

function updateGlobalManifest(results) {
  const globalPath = path.join(OUT_ROOT, 'manifest.json');
  let global = {};
  if (fs.existsSync(globalPath)) {
    try { global = JSON.parse(fs.readFileSync(globalPath, 'utf8')); } catch { global = {}; }
  }
  for (const r of results) {
    if (r.status === 'ok') {
      global[r.chapterUrl] = {
        slug: r.slug,
        imageCount: r.imageCount,
        preparedAt: new Date().toISOString(),
      };
    }
  }
  fs.mkdirSync(OUT_ROOT, { recursive: true });
  fs.writeFileSync(globalPath, JSON.stringify(global, null, 2));
}

async function main() {
  const raw = process.env.CHAPTER_URLS || '';
  const urls = raw.split('\n').map(s => s.trim()).filter(Boolean).slice(0, MAX_CHAPTERS_PER_RUN);

  if (urls.length === 0) {
    console.error('لا يوجد أي رابط فصل بمُدخل CHAPTER_URLS');
    process.exit(1);
  }

  console.log('سيتم تحضير', urls.length, 'فصل (الحد الأقصى', MAX_CHAPTERS_PER_RUN, 'لكل تشغيلة)');

  const browser = await chromium.launch();
  const results = [];
  for (const url of urls) {
    try {
      const r = await processChapter(browser, url);
      results.push(r);
    } catch (err) {
      console.error('فشل تحضير الفصل:', url, '-', err.message);
      results.push({ chapterUrl: url, status: 'error', error: err.message });
    }
  }
  await browser.close();

  updateGlobalManifest(results);

  console.log('\n=== ملخص التشغيلة ===');
  for (const r of results) {
    if (r.status === 'ok') {
      const savedPct = r.totalOriginal > 0
        ? Math.round((1 - r.totalCompressed / r.totalOriginal) * 100)
        : 0;
      console.log(`✓ ${r.slug} — ${r.imageCount} صورة — توفير ${savedPct}%`);
    } else {
      console.log(`✗ ${r.chapterUrl} — ${r.status}${r.error ? ': ' + r.error : ''}`);
    }
  }
}

main().catch(err => {
  console.error('خطأ عام غير متوقع:', err);
  process.exit(1);
});
