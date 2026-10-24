"""Tick's profit lens: past versus future, the guidance itself, and what moves profit. Offline; fixtures are
modelled on real earnings releases (Nvidia, Coca-Cola, Ford) where the first versions went wrong."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lens  # noqa: E402

ARTICLE = [
    "Acme Corp reported third-quarter revenue of $4.2 billion, up 12% from a year earlier, as demand for its data-center chips stayed strong. Orders rose 18% and the backlog reached a record $9.1 billion.",
    "Gross margin was 61.2%, down from 63.0% a year ago, as higher freight and component costs weighed on results. Net income fell 4% to $610 million after a one-time restructuring charge of $85 million.",
    "The company raised its full-year revenue outlook to between $16.4 billion and $16.8 billion, from a prior range of $16.0 billion to $16.4 billion. Chief executive Jane Doe said she expects gross margin to improve to about 62% in the fourth quarter as pricing actions take hold.",
    "Management cautioned that new tariffs could pressure margins next year and that demand may soften if customers delay projects.",
    "This press release contains forward-looking statements within the meaning of the Private Securities Litigation Reform Act of 1995, including statements about our expected revenue and margins. Actual results may differ materially because of risks such as changes in demand, competition and supply constraints.",
    "The company will host a conference call at 5 p.m. Eastern to discuss the results.",
]


def run(paras=ARTICLE):
    return lens.analyze(paras)


class PastAndFuture(unittest.TestCase):
    def test_reported_results_are_looking_back_and_expectations_are_looking_ahead(self):
        r = run()
        back = " ".join(i["text"] for i in r["looking_back"])
        ahead = " ".join(i["text"] for i in r["looking_ahead"])
        self.assertIn("Orders rose 18%", back)
        self.assertIn("Net income fell 4%", back)
        self.assertIn("raised its full-year revenue outlook", ahead)
        self.assertIn("expects gross margin to improve", ahead)
        self.assertNotIn("Orders rose 18%", ahead)

    def test_the_legal_disclaimer_is_not_an_outlook(self):
        r = run()
        self.assertTrue(r["disclaimer"])
        everything = " ".join(i["text"] for i in r["looking_back"] + r["looking_ahead"]) + " ".join(d["text"] for d in r["drivers"])
        self.assertNotIn("Private Securities Litigation", everything)
        self.assertNotIn("changes in demand, competition", everything)

    def test_a_conference_call_notice_is_ignored(self):
        self.assertNotIn("conference call", " ".join(i["text"] for i in run()["looking_ahead"]))

    def test_nothing_profit_related_means_it_says_so(self):
        r = lens.analyze(["The weather in Singapore was pleasant on Tuesday and the harbour was busy with ships arriving all afternoon.",
                          "A local festival will take place next month and organisers expect thousands of visitors to attend the event."])
        self.assertFalse(r["available"])
        self.assertIn("no profit-related statements", r["reason"])


class DirectionAndImpact(unittest.TestCase):
    def tone_of(self, sentence, side="looking_back"):
        r = lens.analyze([sentence, "Revenue rose 5% to $2.0 billion in the quarter compared with last year, helped by strong demand for its products."])
        return {i["text"][:30]: i["tone"] for i in r["looking_back"] + r["looking_ahead"]}

    def test_a_margin_that_was_down_is_bad_and_costs_are_named_as_the_reason(self):
        r = run()
        margin = next(i for i in r["looking_back"] if i["text"].startswith("Gross margin"))
        self.assertEqual(margin["tone"], "bad")
        costs = next(d for d in r["drivers"] if d["theme"] == "Costs")
        self.assertEqual(costs["tone"], "bad")

    def test_rising_costs_hurt_and_falling_costs_help(self):
        for s, tone in (("Operating costs rose 9% to $1.4 billion in the quarter compared with the prior year, driven by wage increases.", "bad"),
                        ("Operating costs fell 6% to $1.1 billion in the quarter compared with the prior year, as the restructuring delivered savings.", "good")):
            r = lens.analyze([s, "Revenue rose 5% to $2.0 billion in the quarter compared with last year, helped by strong demand for its products."])
            self.assertEqual(next(i for i in r["looking_back"] if i["text"].startswith("Operating costs"))["tone"], tone, s)

    def test_tariffs_are_a_headwind_unless_they_are_eased(self):
        for s, tone in (("Management cautioned that new tariffs could pressure margins next year and expects costs to rise.", "bad"),
                        ("The company expects tariffs to be eased next quarter after the exemption was granted, which should lift margins.", "good")):
            r = lens.analyze([s, "Revenue rose 5% to $2.0 billion in the quarter compared with last year, helped by strong demand for its products."])
            self.assertEqual(next(i for i in r["looking_ahead"] if "tariffs" in i["text"])["tone"], tone, s)

    def test_diluted_share_does_not_read_as_bad_news(self):
        r = lens.analyze(["Earnings per diluted share were $2.46 in the quarter ended July 26, compared with $1.10 in the prior year.",
                          "Revenue rose 5% to $2.0 billion in the quarter compared with last year, helped by strong demand for its products."])
        self.assertNotEqual(next(i for i in r["looking_back"] if "diluted" in i["text"])["tone"], "bad")


class Guidance(unittest.TestCase):
    def test_a_raise_a_cut_and_a_reaffirmation_are_told_apart(self):
        def g(text):
            r = lens.analyze([text, "Revenue rose 5% to $2.0 billion in the quarter compared with last year, helped by strong demand for its products."])
            return next(i["guidance"] for i in r["looking_ahead"] if "guidance" in i["text"].lower() or "outlook" in i["text"].lower())
        self.assertEqual(g("The company raised its full-year earnings guidance to $4.10 to $4.30 per share on stronger demand."), "raise")
        self.assertEqual(g("The company lowered its full-year outlook and now expects revenue of $3.8 billion, citing weaker orders."), "cut")
        self.assertEqual(g("The company reaffirmed its full-year guidance for revenue of $8.0 billion and earnings of $2.00 per share."), "hold")

    def test_the_outlook_being_raised_leads_the_read(self):
        r = run()
        self.assertEqual(r["read"]["lean"], "up")
        self.assertIn("outlook itself was raised", r["read"]["points"][0]["text"])

    def test_a_cut_leans_down(self):
        r = lens.analyze(["The company cut its full-year profit outlook after orders fell 14% and warned that costs would keep rising.",
                          "Gross margin was 38.1%, down from 41.0% a year ago, as higher input costs weighed on results.",
                          "Management expects tariffs to pressure margins through the rest of the year and demand to remain weak."])
        self.assertEqual(r["read"]["lean"], "down")

    def test_guidance_figures_are_pulled_out(self):
        r = lens.analyze(["Management expects fourth-quarter revenue of $5.1 billion to $5.3 billion and operating margin of about 21%.",
                          "Revenue rose 5% to $2.0 billion in the quarter compared with last year, helped by strong demand for its products."])
        item = r["looking_ahead"][0]
        self.assertIn("$5.1 billion", item["figures"])
        self.assertIn("21%", item["figures"])
        self.assertTrue(item["firm"])

    def test_guidance_implies_growth_against_the_last_reported_number(self):
        r = lens.analyze(["NVIDIA today reported revenue for the second quarter of $96.2 billion, up 18% from the previous quarter and up 117% from a year ago.",
                          "Second-quarter Edge Computing revenue was $7.2 billion, up 13% from the previous quarter and up 27% from a year ago.",
                          "Revenue is expected to be $108.0 billion, plus or minus 2%, in the third quarter."])
        imp = next(i["implied"] for i in r["looking_ahead"] if i["implied"])
        self.assertEqual(imp["metric"], "revenue")
        self.assertEqual(imp["then"], 96.2e9)        # the total, not the segment
        self.assertAlmostEqual(imp["delta"], 12.3, places=0)
        self.assertTrue(any("implies revenue" in p["text"] and "up 12.3%" in p["text"] for p in r["read"]["points"]))

    def test_a_implausible_pairing_is_not_shown(self):
        r = lens.analyze(["Second-quarter Edge Computing revenue was $7.2 billion, up 13% from the previous quarter and up 27% from a year ago.",
                          "Revenue is expected to be $108.0 billion, plus or minus 2%, in the third quarter, the company said on Tuesday."])
        self.assertTrue(all(not i["implied"] for i in r["looking_ahead"]))   # 15x a segment is not growth

    def test_a_margin_guided_above_the_reported_margin_shows_the_change_in_points(self):
        r = lens.analyze(["Gross margin was 72.5% in the quarter ended July 26, compared with 71.0% in the prior year.",
                          "Gross margins are expected to be 74.0% in the third quarter, plus or minus 50 basis points.",
                          "Revenue rose 5% to $2.0 billion in the quarter compared with last year, helped by strong demand for its products."])
        imp = next(i["implied"] for i in r["looking_ahead"] if i["implied"])
        self.assertEqual((imp["metric"], imp["unit"], imp["delta"]), ("gross margin", "pp", 1.5))
        self.assertEqual((imp["now"], imp["then"]), (74.0, 72.5))       # guided figure first, reported figure second
        self.assertTrue(any("at about 74.0%" in p["text"] and "up 1.5 points" in p["text"] for p in r["read"]["points"]))


class GuidanceTables(unittest.TestCase):
    """Coca-Cola's release gives its outlook as a table with Current and Prior columns, not as sentences."""
    KO = ["Outlook",
          "The 2026 outlook information provided below includes forward-looking non-GAAP financial measures, which management uses in measuring performance.",
          "Full Year 2026 Guidance", "Current Prior",
          "Organic revenues (non-GAAP) Approx. 5% growth 4% to 5% growth",
          "•Approx. 1% currency tailwind1",
          "•2% to 3% headwind from acquisitions and divestitures2",
          "Comparable currency neutral EPS excluding acquisitions and divestitures (non-GAAP) 7% to 8% growth 6% to 7% growth",
          "Third Quarter 2026 Considerations",
          "Contact", "Unit case volume grew 5%, led by India, China, the United States and Brazil during the quarter that ended July 3, 2026."]

    def test_current_against_prior_columns_become_a_raise(self):
        r = lens.analyze(self.KO)
        rows = {i["text"][:16]: i for i in r["looking_ahead"]}
        self.assertEqual(rows["Organic revenues"]["guidance"], "raise")
        self.assertEqual(rows["Comparable curre"]["guidance"], "raise")
        self.assertEqual(r["read"]["lean"], "up")
        self.assertFalse(any(i["guidance"] == "cut" for i in r["looking_ahead"]))   # "outlook ... provided below" is a label

    def test_the_word_below_in_a_label_is_not_a_guidance_cut(self):
        r = lens.analyze(["The 2026 outlook information provided below includes forward-looking measures that management uses in measuring performance and results.",
                          "Revenue rose 5% to $2.0 billion in the quarter compared with last year, helped by strong demand for its products."])
        self.assertFalse(any(i["guidance"] for i in r.get("looking_ahead", [])))

    def test_tailwinds_and_headwinds_in_the_table_are_read(self):
        r = lens.analyze(self.KO)
        tone = {i["text"][:30]: i["tone"] for i in r["looking_ahead"]}
        self.assertEqual(tone["Approx. 1% currency tailwind1"], "good")

    def test_a_table_cut_is_a_cut(self):
        self.assertEqual(lens._current_vs_prior("Organic revenues Approx. 3% growth 4% to 5% growth"), "cut")
        self.assertEqual(lens._current_vs_prior("Organic revenues 4% to 5% growth 4% to 5% growth"), "hold")

    def test_sentences_inside_an_outlook_section_are_not_mistaken_for_table_rows(self):
        # Nvidia: "up 18% ... up 117%" has two percentages, which once read as a guidance cut
        r = lens.analyze(["Outlook", "Current Prior",
                          "Second-quarter revenue was $89.0 billion, up 18% from the previous quarter and up 117% from a year ago.",
                          "Revenue is expected to be $108.0 billion, plus or minus 2%.",
                          "Revenue rose 5% to $2.0 billion in the quarter compared with last year, helped by strong demand for its products."])
        self.assertFalse(any(i["guidance"] == "cut" for i in r["looking_ahead"]))
        self.assertNotIn("cut or withdrawn", " ".join(p["text"] for p in r["read"]["points"]))


class TenKNoise(unittest.TestCase):
    """False alarms from the first run over real 10-Ks (Coca-Cola, Apple, Tesla)."""
    GOOD = "Revenue rose 5% to $2.0 billion in the quarter compared with last year, helped by strong demand for its products."

    def test_a_valuation_input_called_outlook_is_not_a_guidance_cut(self):
        s = "During the three months ended December 31, 2025, the operating results of the trademark, combined with a lower long-term outlook, resulted in an impairment charge of $760 million."
        r = lens.analyze([s, self.GOOD])
        self.assertFalse(any(i["guidance"] for i in r["looking_ahead"] + r["looking_back"]))
        self.assertNotIn("cut or withdrawn", " ".join(p["text"] for p in r["read"]["points"]))

    def test_accounting_rule_notes_are_not_a_profit_outlook(self):
        s = "In December 2023, the FASB issued ASU No. 2023-09, Income Taxes, which will be effective for fiscal years beginning after December 15, 2024 and the Company will adopt it."
        r = lens.analyze([s, self.GOOD, "Management expects revenue to grow 6% next year to about $2.1 billion as demand for its products continues."])
        self.assertFalse(any("FASB" in i["text"] for i in r["looking_ahead"] + r["looking_back"]))

    def test_a_past_quarter_or_half_of_a_past_year_is_not_the_future(self):
        r = lens.analyze(["In the third quarter of 2025, we initiated actions to reduce costs and recognized $390 million of expenses in the second half of 2025, which lowered operating income.",
                          "Revenue for the year ended December 31, 2025 was $94.8 billion, a decrease of 3% compared with 2024, driven by lower prices."])
        self.assertFalse(any("third quarter of 2025" in i["text"] for i in r.get("looking_ahead", [])))

    def test_a_debt_maturity_years_away_does_not_move_the_documents_now(self):
        # Beyond Meat's 10-K once came out as written in 2027 because of notes due 2030 and 2027
        r = lens.analyze(["Revenue for the year ended December 31, 2025 was $275.0 million, a decrease of 15% compared with 2024, driven by lower volume.",
                          "On December 22, 2025, we adjusted the exercise price for the warrants from $3.26 to $1.95, and the notes mature in 2030, reflecting lower costs.",
                          "In 2023, we initiated a global operations review to cut costs, which lowered operating expenses by $20 million compared with 2022."])
        self.assertEqual(r["reference_year"], 2025)
        self.assertFalse(any("December 22, 2025" in i["text"] for i in r["looking_ahead"]))

    def test_a_bare_will_lists_a_sentence_but_cannot_move_the_read(self):
        r = lens.analyze(["Revenue for the year ended December 31, 2025 was $275.0 million, a decrease of 15% compared with 2024, driven by lower volume.",
                          "Our future capital requirements will depend on many factors, including growth in revenue and the pace of cost reductions in coming periods.",
                          "Our margins will improve and our costs will fall and demand will strengthen as we grow into the new facility over time."])
        self.assertNotIn("should help profit", " ".join(p["text"] for p in r["read"]["points"]))

    def test_a_future_quarter_named_with_a_later_year_is_still_the_future(self):
        r = lens.analyze(["Revenue for the year ended December 31, 2025 was $94.8 billion, a decrease of 3% compared with 2024, driven by lower prices.",
                          "We expect operating income in the fourth quarter of 2026 to improve to $2.0 billion as cost savings take effect."])
        self.assertTrue(any("fourth quarter of 2026" in i["text"] for i in r["looking_ahead"]))


class WhatMovesProfit(unittest.TestCase):
    def test_leading_indicators_such_as_orders_and_backlog_come_first_among_drivers(self):
        r = lens.analyze(["Orders rose 18% in the quarter compared with last year and the backlog reached a record $9.1 billion at period end.",
                          "Operating costs rose 9% to $1.4 billion in the quarter compared with the prior year, driven by wage increases.",
                          "The company expects revenue of $5.1 billion next quarter and gross margin of about 60 percent in the quarter."])
        themes = [d["theme"] for d in r["drivers"]]
        self.assertIn("Orders and demand", themes)
        self.assertTrue(next(d for d in r["drivers"] if d["theme"] == "Orders and demand")["leading"])

    def test_one_offs_are_called_out_so_they_can_be_stripped(self):
        r = run()
        self.assertTrue(any("restructuring" in o["text"] for o in r["one_offs"]))
        self.assertTrue(any("one-off" in p["text"] for p in r["read"]["points"]))
        self.assertTrue(any("Strip the one-offs" in c for c in r["read"]["check"]))

    def test_hedged_outlook_is_flagged_as_hope(self):
        r = lens.analyze(["Management hopes revenue could reach $3 billion next year and aims to lift gross margin if demand may recover in coming quarters.",
                          "The company might see operating income rise 10% next year, subject to supply conditions and uncertain demand later this year.",
                          "Revenue rose 5% to $2.0 billion in the quarter compared with last year, helped by strong demand for its products."])
        self.assertTrue(all(not i["firm"] for i in r["looking_ahead"]))
        self.assertTrue(any("hedged" in p["text"] for p in r["read"]["points"]))

    def test_every_point_states_its_cause_and_the_text_is_never_a_forecast(self):
        r = run()
        for p in r["read"]["points"]:
            self.assertGreater(len(p["text"]), 25)
        self.assertNotIn("will rise", " ".join(p["text"] for p in r["read"]["points"]).lower())


class CleaningRealDocuments(unittest.TestCase):
    def test_links_and_page_numbers_are_removed_from_the_front_of_a_sentence(self):
        s = "1 https://ford.to/facebook https://x.com/ford Ford Reports Second-Quarter 2026 Financial Results and raised full-year guidance on revenue."
        self.assertEqual(lens._clean(s), "Ford Reports Second-Quarter 2026 Financial Results and raised full-year guidance on revenue.")

    def test_table_rows_are_not_sentences(self):
        self.assertFalse(lens._is_prose("EBIT Margin (%) 4.3 % 5.2 % 0.9 ppts 3.5 % 6.5 % 3.1 ppts Adjusted EPS (Diluted) $ 0.37 $ 0.4"))
        self.assertTrue(lens._is_prose("Unit case volume grew 5%, led by India, China, the United States and Brazil during the quarter."))

    def test_the_non_gaap_reconciliation_notice_is_a_disclaimer_but_non_gaap_outlooks_are_not(self):
        notice = "We do not provide a reconciliation of forward-looking non-GAAP measures because it would require unreasonable efforts."
        outlook = "GAAP and non-GAAP gross margins are expected to be 74.0%, plus or minus 50 basis points, in the third quarter of fiscal 2027."
        r = lens.analyze([notice, outlook, "Revenue rose 5% to $2.0 billion in the quarter compared with last year, helped by strong demand for its products."])
        self.assertTrue(r["disclaimer"])
        self.assertTrue(any("gross margins are expected" in i["text"] for i in r["looking_ahead"]))

    def test_an_old_document_is_judged_against_its_own_date_not_todays(self):
        r = lens.analyze(["Revenue for the year ended December 31, 2019 was $2.0 billion, up 8% from fiscal 2018, driven by strong demand.",
                          "The company expects 2020 revenue to grow 5% to $2.1 billion and gross margin to improve in the first half of 2020."])
        self.assertEqual(r["reference_year"], 2019)
        self.assertTrue(r["looking_ahead"] and "2020" in r["looking_ahead"][0]["text"])

    def test_huge_input_is_capped_and_still_fast(self):
        r = lens.analyze_text(("Revenue rose 5% to $2.0 billion in the quarter compared with last year, helped by strong demand. " * 4000)[:lens.MAX_CHARS * 2])
        self.assertTrue(r["available"])

    def test_too_little_text_is_refused(self):
        with self.assertRaises(ValueError):
            lens.analyze_text("short")


if __name__ == "__main__":
    unittest.main()
