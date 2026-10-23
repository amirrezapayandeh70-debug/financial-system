"""Self-contained Persian RTL report; no remote assets or scripts."""
from html import escape


def render(result):
    def fmt(value, percent=False):
        if value is None:
            return "داده کافی نیست"
        text = f"{value * 100:,.2f}٪" if percent else f"{value:,.2f}"
        return text.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))

    meta = result["metadata"]
    cards = [
        ("آخرین قیمت (ریال)", fmt(result["close_irr"])),
        ("ارزش بازار (میلیارد ریال)", fmt(result["market_cap_irr"] / 1e9)),
        ("سود هر سهم TTM (ریال)", fmt(result["eps_ttm_irr"])),
        ("P/E", fmt(result["pe_ttm"])), ("P/B", fmt(result["pb"])),
        ("حاشیه سود خالص", fmt(result["net_margin"], True)),
        ("نسبت بدهی‌ها به دارایی‌ها", fmt(result["liabilities_to_assets"], True)),
        ("بیشترین افت در دوره داده", fmt(result["max_drawdown"], True)),
        ("حجم نسبت به میانگین ۲۰ جلسه قبل", fmt(result["volume_ratio"])),
    ]
    cards.extend((f"بازده {n} جلسه معاملاتی", fmt(result["returns"][str(n)], True)) for n in (1, 5, 20, 60))
    tiles = "".join(f"<article><span>{escape(label)}</span><strong>{escape(value)}</strong></article>" for label, value in cards)
    values = [p["adjusted_close_irr"] for p in result["prices"]]
    low, high = min(values), max(values)
    points = " ".join(f"{20 + i * 760 / (len(values) - 1):.2f},{210 - (v - low) * 180 / (high - low or 1):.2f}" for i, v in enumerate(values))
    rows = "".join(f'<tr><td>{escape(p["date"])}</td><td>{fmt(p["close_irr"])}</td><td>{fmt(p["adjusted_close_irr"])}</td><td>{fmt(p["volume"])}</td></tr>' for p in reversed(result["prices"]))
    data_label = "داده ساختگی برای آزمایش؛ اطلاعات واقعی فملی نیست" if meta["data_kind"] == "synthetic" else "داده واردشده توسط کاربر؛ صحت منبع مستقلاً تأیید نشده"
    alert = "حجم حداقل دو برابر میانگین ۲۰ جلسه قبل است؛ علت نیازمند بررسی است." if result["volume_alert"] else "هشدار حجم فعال نیست." if result["volume_alert"] is False else "برای بررسی حجم، ۲۱ مشاهده و میانگین حجم غیرصفر لازم است."
    return f'''<!doctype html>
<html lang="fa" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>گزارش {escape(meta['symbol'])}</title>
<style>body{{margin:0;background:#0c1424;color:#e7edf7;font:16px Tahoma,Arial;line-height:1.9}}main{{max-width:1100px;margin:auto;padding:28px}}h1{{margin-bottom:4px}}.muted,span{{color:#acbdd4}}.notice{{background:#47371b;padding:16px;border-radius:12px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px;margin:24px 0}}article,section{{background:#17243a;padding:18px;border-radius:12px}}strong{{display:block;font-size:25px}}svg{{width:100%;height:auto;direction:ltr}}table{{border-collapse:collapse;width:100%;white-space:nowrap}}td,th{{padding:10px;text-align:right;border-bottom:1px solid #34445b}}.scroll{{overflow:auto}}a{{color:#72ddca}}@media print{{body{{background:white;color:black}}article,section,.notice{{background:#eee;color:black}}span,.muted{{color:#333}}}}</style>
<main><p class="muted">سیستم تحلیل مالی و سرمایه‌گذاری · نسخه اولیه</p>
<h1>{escape(meta['symbol'])} | {escape(meta['company'])}</h1>
<p>تاریخ قیمت: <bdi>{escape(result['as_of'])}</bdi> · تعداد مشاهدات: {result['observations']}</p>
<p class="notice">{data_label}</p><div class="grid">{tiles}</div>
<section><h2>روند قیمت تعدیل‌شده</h2><p>از <bdi>{escape(result['prices'][0]['date'])}</bdi> تا <bdi>{escape(result['as_of'])}</bdi>؛ حداقل {fmt(low)} و حداکثر {fmt(high)} ریال. محور عمودی از صفر شروع نمی‌شود.</p>
<svg viewBox="0 0 800 240" role="img" aria-label="روند قیمت تعدیل‌شده از قدیمی‌ترین به جدیدترین مشاهده"><polyline points="{points}" fill="none" stroke="#42dbc0" stroke-width="3"/></svg></section>
<h2>یادداشت تحلیل</h2><p>{alert} این هشدار به‌تنهایی سیگنال خرید یا نشانه ورود پول هوشمند نیست.</p>
<p>بازده از نسبت قیمت تعدیل‌شده محاسبه شده است. اعتبار آن به روش تعدیل منبع وابسته است؛ بازده کل شامل سود نقدی فقط با تعدیل مناسب سود نقدی قابل محاسبه است. ارزش بازار و نسبت‌های ارزش‌گذاری از قیمت تعدیل‌نشده استفاده می‌کنند.</p>
<p>مبنای مالی: TTM؛ پایان دوره: <bdi>{escape(meta['period_end'])}</bdi>؛ تاریخ دسترسی به گزارش: <bdi>{escape(meta['available_on'])}</bdi>.</p>
<p>منبع مالی: {escape(meta['source'])}<br>منبع قیمت: {escape(meta['price_source'])}<br>روش تعدیل: {escape(meta['adjustment_method'])}</p>
<h2>مشاهدات ورودی</h2><div class="scroll"><table><thead><tr><th>تاریخ میلادی</th><th>قیمت (ریال)</th><th>قیمت تعدیل‌شده (ریال)</th><th>حجم (سهم)</th></tr></thead><tbody>{rows}</tbody></table></div>
<p class="muted">اتصال زنده، مقایسه با شاخص، پرتفوی و پیشنهاد سرمایه‌گذاری در این نسخه پیاده‌سازی نشده‌اند.</p></main></html>'''
