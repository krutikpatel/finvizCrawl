import json
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict

PT = ZoneInfo("America/Los_Angeles")
analyzed_at = datetime.now(PT).isoformat()

new_records = [
    {
        "article_id": "012001be8fef8a6a74b077d4",
        "ticker": "TSLA",
        "run_date": "2026-06-10",
        "analyzed_at": analyzed_at,
        "headline": "This Tesla bull makes a bold claim: The company has solved the 'self-driving puzzle'",
        "publisher": "(MarketWatch)",
        "url": "https://www.marketwatch.com/story/this-tesla-bull-makes-a-bold-claim-the-company-has-solved-the-self-driving-puzzle-d723edca?mod=mw_FV",
        "sentiment": "bullish",
        "score": 0.75,
        "summary": "Piper Sandler's claim that Tesla has effectively achieved Level 4 autonomy with FSD, with 30% upside seen, represents a significant potential re-rating catalyst for TSLA's autonomous driving narrative.",
        "analysis_error": None,
    },
    {
        "article_id": "18252dad4754b4ef98caf211",
        "ticker": "TSLA",
        "run_date": "2026-06-10",
        "analyzed_at": analyzed_at,
        "headline": "Tesla Slips as BYD Raises Global Ambitions",
        "publisher": "(GuruFocus.com)",
        "url": "https://finance.yahoo.com/markets/stocks/articles/tesla-slips-byd-raises-global-194542675.html",
        "sentiment": "bearish",
        "score": -0.45,
        "summary": "BYD's stated ambition to surpass Toyota in total vehicle volume within five years, combined with having already overtaken Tesla in global BEV sales in 2025, reinforces competitive headwinds for TSLA.",
        "analysis_error": None,
    },
    {
        "article_id": "28a59e7c6879f7cf4a18acd4",
        "ticker": "TSLA",
        "run_date": "2026-06-10",
        "analyzed_at": analyzed_at,
        "headline": "Tesla Challenger XPengs CEO Takes Over Robotics Division After Key Executive Departure  XPEV Slides For Sixth Straight Session",
        "publisher": "(Stocktwits)",
        "url": "https://finance.yahoo.com/m/fe793572-8bb0-3060-aa7e-930b9319188f/tesla-challenger-xpeng-ceo.html",
        "sentiment": "neutral",
        "score": -0.10,
        "summary": "XPeng's robotics leadership reshuffle and continued share decline suggests Tesla's Chinese humanoid robot competitor is losing ground, a marginal positive for Tesla's robotics positioning.",
        "analysis_error": None,
    },
    {
        "article_id": "5b364a7644b4d6eb20473438",
        "ticker": "TSLA",
        "run_date": "2026-06-10",
        "analyzed_at": analyzed_at,
        "headline": "SpaceX IPO Faces Last-Minute Challenge From US Senator Elizabeth Warren",
        "publisher": "(BeInCrypto)",
        "url": "https://finance.yahoo.com/m/7452ee24-6cd4-3c1c-b29d-fa4b6d8a9162/spacex-ipo-faces-last-minute.html",
        "sentiment": "bearish",
        "score": -0.20,
        "summary": "SpaceX's record $75B IPO at a valuation surpassing Tesla raises near-term capital rotation risks for TSLA as investors reallocate toward Musk's higher-growth rocket and satellite venture.",
        "analysis_error": None,
    },
    {
        "article_id": "5bfb68c24fb9eaffa29ce28e",
        "ticker": "TSLA",
        "run_date": "2026-06-10",
        "analyzed_at": analyzed_at,
        "headline": "GM Follows Teslas Playbook  Expands Into Energy Storage With Peak Partnership",
        "publisher": "(Stocktwits)",
        "url": "https://finance.yahoo.com/m/2f00466f-4df9-3454-ba51-b54afc37e74f/gm-follows-tesla-playbook.html",
        "sentiment": "neutral",
        "score": -0.10,
        "summary": "GM's entry into sodium-ion grid-scale energy storage following Ford validates Tesla's energy strategy but adds incremental competition to a segment Tesla currently dominates.",
        "analysis_error": None,
    },
    {
        "article_id": "824d8de4909355f12d1e6075",
        "ticker": "TSLA",
        "run_date": "2026-06-10",
        "analyzed_at": analyzed_at,
        "headline": "Chanos says SpaceX is not worth $1.75 trillion",
        "publisher": "(Investing.com)",
        "url": "https://finance.yahoo.com/markets/stocks/articles/chanos-says-spacex-not-worth-221835794.html",
        "sentiment": "neutral",
        "score": 0.05,
        "summary": "Chanos's SpaceX valuation skepticism could deter capital rotation from Tesla into SpaceX, providing marginal support for TSLA while not directly addressing Tesla's own fundamentals.",
        "analysis_error": None,
    },
    {
        "article_id": "8c028cca033194ce20e4939d",
        "ticker": "TSLA",
        "run_date": "2026-06-10",
        "analyzed_at": analyzed_at,
        "headline": "General Motors follows Ford's lead into the battery business",
        "publisher": "(Yahoo Finance Video)",
        "url": "https://finance.yahoo.com/video/general-motors-follows-fords-lead-into-the-battery-business-152500628.html",
        "sentiment": "neutral",
        "score": -0.10,
        "summary": "GM's sodium-ion battery partnership with Peak Energy follows Ford's energy pivot, signaling growing legacy automaker competition against Tesla's first-mover Energy segment.",
        "analysis_error": None,
    },
    {
        "article_id": "aa430a92735296449c516cce",
        "ticker": "TSLA",
        "run_date": "2026-06-10",
        "analyzed_at": analyzed_at,
        "headline": "The big question facing SpaceX investors: What are you really buying?",
        "publisher": "(MarketWatch)",
        "url": "https://www.marketwatch.com/story/the-big-question-facing-spacex-investors-what-are-you-really-buying-8c5c2a10?mod=mw_FV",
        "sentiment": "neutral",
        "score": -0.05,
        "summary": "Pre-IPO analysis of SpaceX's identity as rocket vs. satellite vs. AI company underscores valuation complexity and may steer some capital away from TSLA toward the SpaceX narrative ahead of its Nasdaq debut.",
        "analysis_error": None,
    },
    {
        "article_id": "c2533f05dde1587edf59b3b2",
        "ticker": "TSLA",
        "run_date": "2026-06-10",
        "analyzed_at": analyzed_at,
        "headline": "S&P 500, Nasdaq, Dow Drop As US-Iran War Jitters, Inflation Risk Spur Tech Selloffs   SMCI, AMZN, OPEN, SEGG, TSLA In Focus",
        "publisher": "(Stocktwits)",
        "url": "https://finance.yahoo.com/m/b5df80ec-3ee8-349e-b267-261bb9a4c056/sp500-nasdaq-dow-drop.html",
        "sentiment": "bearish",
        "score": -0.55,
        "summary": "A broad 1.6-2% market selloff driven by Iran geopolitical risk and sticky inflation is a direct near-term headwind for TSLA, which as a high-beta tech-adjacent stock typically amplifies broader market declines.",
        "analysis_error": None,
    },
    {
        "article_id": "d5d0e0529b27380c0f179b2e",
        "ticker": "TSLA",
        "run_date": "2026-06-10",
        "analyzed_at": analyzed_at,
        "headline": "Tesla gets go-ahead to sell self-driving technology in Belgium",
        "publisher": "(Reuters)",
        "url": "https://finance.yahoo.com/sectors/technology/articles/tesla-gets-ahead-sell-self-180112390.html",
        "sentiment": "bullish",
        "score": 0.55,
        "summary": "Belgium's FSD approval, making it the third European country to authorize the technology, strengthens the case for accelerating international expansion of Tesla's high-margin autonomous driving business.",
        "analysis_error": None,
    },
    {
        "article_id": "f10eacec6be479d5fbae12e7",
        "ticker": "TSLA",
        "run_date": "2026-06-10",
        "analyzed_at": analyzed_at,
        "headline": "The Massive SpaceX IPO Is Almost Here. We've Got the Basics for Investors",
        "publisher": "(Investopedia)",
        "url": "https://finance.yahoo.com/m/da782f89-d345-3ab7-8844-d3af762a7de9/the-massive-spacex-ipo-is.html",
        "sentiment": "neutral",
        "score": -0.10,
        "summary": "Mass investor education around SpaceX's record IPO raises short-term capital rotation risk for TSLA as retail attention shifts to the Nasdaq's newest high-profile Musk-affiliated listing.",
        "analysis_error": None,
    },
    {
        "article_id": "fe3eb0670f2a0b785e4086f6",
        "ticker": "TSLA",
        "run_date": "2026-06-10",
        "analyzed_at": analyzed_at,
        "headline": "TSLA Stock Watches SpaceX IPO While Cheapest Cybertruck Hits Driveways After Long Wait",
        "publisher": "(Stocktwits)",
        "url": "https://finance.yahoo.com/m/da31756d-c94a-3392-a74f-d31e93cd1775/tsla-stock-watches-spacex-ipo.html",
        "sentiment": "neutral",
        "score": 0.15,
        "summary": "Deliveries of the more affordable $59,990 Cybertruck expand Tesla's addressable pickup truck market, though SpaceX IPO uncertainty and investor distraction cloud TSLA's near-term trading outlook.",
        "analysis_error": None,
    },
    {
        "article_id": "ff3f8491f8801d98e31ec73d",
        "ticker": "TSLA",
        "run_date": "2026-06-10",
        "analyzed_at": analyzed_at,
        "headline": "Tesla Stock Surges Into Bull Case as JPMorgan Lifts Target 227%",
        "publisher": "(GuruFocus.com)",
        "url": "https://finance.yahoo.com/markets/stocks/articles/tesla-stock-surges-bull-case-193621115.html",
        "sentiment": "bullish",
        "score": 0.85,
        "summary": "JPMorgan's 227% price target hike from $145 to $475 and upgrade from Underweight reflects a major institutional re-rating of Tesla as a multi-segment technology company spanning autos, energy, robotaxis, and robotics.",
        "analysis_error": None,
    },
]

print(f"Appending {len(new_records)} new records...")

log_path = "data/TSLA/sentiment_log.jsonl"
with open(log_path, "a") as f:
    for rec in new_records:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

print("Log updated.")

all_records = []
with open(log_path) as f:
    for line in f:
        line = line.strip()
        if line:
            all_records.append(json.loads(line))

print(f"Total log entries: {len(all_records)}")

by_date = defaultdict(list)
for rec in all_records:
    by_date[rec["run_date"]].append(rec)


def dominant_sentiment(recs):
    avg = sum(r["score"] for r in recs) / len(recs)
    if avg >= 0.1:
        return "bullish"
    elif avg <= -0.1:
        return "bearish"
    return "neutral"


def score_avg(recs):
    return round(sum(r["score"] for r in recs) / len(recs), 4)


def top_headlines(recs, n=5):
    sorted_recs = sorted(recs, key=lambda r: abs(r["score"]), reverse=True)
    result = []
    for r in sorted_recs[:n]:
        entry = {
            "article_id": r["article_id"],
            "headline": r["headline"],
            "publisher": r["publisher"],
            "sentiment": r["sentiment"],
            "score": r["score"],
            "summary": r.get("summary", ""),
        }
        result.append(entry)
    return result


sorted_dates = sorted(by_date.keys(), reverse=True)

by_date_list = []
for date in sorted_dates:
    recs = by_date[date]
    counts = {"bullish": 0, "neutral": 0, "bearish": 0}
    for r in recs:
        counts[r["sentiment"]] = counts.get(r["sentiment"], 0) + 1
    by_date_list.append({
        "date": date,
        "analyzed": len(recs),
        "sentiment": dominant_sentiment(recs),
        "score_avg": score_avg(recs),
        "sentiment_distribution": counts,
        "top_headlines": top_headlines(recs),
    })

overall_avg = round(sum(r["score"] for r in all_records) / len(all_records), 4)
overall_dist = {"bullish": 0, "neutral": 0, "bearish": 0}
for r in all_records:
    overall_dist[r["sentiment"]] = overall_dist.get(r["sentiment"], 0) + 1

if overall_avg >= 0.1:
    overall_sent = "bullish"
elif overall_avg <= -0.1:
    overall_sent = "bearish"
else:
    overall_sent = "neutral"

summary = {
    "schema_version": "1.0",
    "ticker": "TSLA",
    "generated_at": analyzed_at,
    "total_analyzed": len(all_records),
    "overall_sentiment": overall_sent,
    "overall_score_avg": overall_avg,
    "sentiment_distribution": overall_dist,
    "by_date": by_date_list,
}

summary_path = "data/TSLA/sentiment_summary.json"
with open(summary_path, "w") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)
    f.write("\n")

print("Summary written.")

today_recs = by_date["2026-06-10"]
today_sent = dominant_sentiment(today_recs)
today_avg = score_avg(today_recs)
print(f"TSLA 2026-06-10: 13 new analyzed, 4 skipped, overall={today_sent} ({today_avg:.2f})")
